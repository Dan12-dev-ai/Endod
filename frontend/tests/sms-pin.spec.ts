import { test, expect, type Page } from './fixtures';
import { openSection } from './helpers';

// Settings > SMS PIN (app/interview/sms-pin-section.tsx), against the real
// backend (GET/PUT /users/me/sms-pin). The test backend has SMS commands off
// (no SMS_INBOUND_ENABLED, no short code), so "commands on" is a mocked GET.

const PIN_URL = '**/api/backend/users/me/sms-pin';

type PinState = { has_pin: boolean; locked_until: string | null; short_code: string | null; commands_enabled: boolean };

/** Answer GET /users/me/sms-pin with `state` (a PUT still reaches the backend). */
async function mockPinState(page: Page, state: Partial<PinState>) {
  await page.route(PIN_URL, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const real = (await (await route.fetch()).json()) as PinState;
    await route.fulfill({ json: { ...real, ...state } });
  });
}

async function setPinByApi(page: Page, pin: string) {
  const response = await page.request.put('/api/backend/users/me/sms-pin', { data: { pin } });
  expect(response.ok(), await response.text()).toBeTruthy();
}

const section = (page: Page) => page.locator('[data-purpose="sms-pin-section"]');

async function fillPins(page: Page, pin: string, confirm = pin) {
  await section(page).locator('#sms-pin-new').fill(pin);
  await section(page).locator('#sms-pin-confirm').fill(confirm);
}

test.describe('Settings — SMS PIN', () => {
  test('a patient without a PIN sets one', async ({ page }) => {
    await mockPinState(page, { has_pin: false });
    await openSection(page, 'Setting', 'settings-view');
    const pin = section(page);
    await expect(pin.getByRole('heading', { name: 'SMS PIN' })).toBeVisible();
    await expect(pin).toContainText('only you can get the reply');
    await expect(pin.locator('[data-purpose="sms-pin-status"]')).toHaveText('No PIN yet');

    // Masked, numeric, four digits, never offered for autofill; labelled.
    for (const name of ['PIN', 'Confirm PIN']) {
      const input = pin.getByLabel(name, { exact: true });
      await expect(input).toHaveAttribute('type', 'password');
      await expect(input).toHaveAttribute('inputmode', 'numeric');
      await expect(input).toHaveAttribute('maxlength', '4');
      await expect(input).toHaveAttribute('autocomplete', 'off');
    }
    // Letters are dropped as they are typed.
    await pin.locator('#sms-pin-new').fill('4a8b');
    await expect(pin.locator('#sms-pin-new')).toHaveValue('48');

    // Caught before anything is sent.
    await fillPins(page, '4821', '4822');
    await pin.getByRole('button', { name: 'Set PIN' }).click();
    await expect(pin.locator('[data-purpose="sms-pin-error"]')).toHaveText('The two PINs do not match.');
    await fillPins(page, '1111');
    await pin.getByRole('button', { name: 'Set PIN' }).click();
    await expect(pin.locator('[data-purpose="sms-pin-error"]')).toContainText('too easy to guess');
    await fillPins(page, '48');
    await pin.getByRole('button', { name: 'Set PIN' }).click();
    await expect(pin.locator('[data-purpose="sms-pin-error"]')).toHaveText('Enter exactly 4 digits.');

    await fillPins(page, '4821');
    const saved = page.waitForResponse((r) => r.url().endsWith('/users/me/sms-pin') && r.request().method() === 'PUT');
    await pin.getByRole('button', { name: 'Set PIN' }).click();
    expect((await saved).status()).toBe(200);
    await expect(pin.locator('[data-purpose="sms-pin-success"]')).toHaveText('Your SMS PIN is set.');
    await expect(pin.locator('[data-purpose="sms-pin-error"]')).toHaveCount(0);
    await expect(pin.locator('[data-purpose="sms-pin-status"]')).toHaveText('PIN set');
    await expect(pin.locator('#sms-pin-new')).toHaveValue('');
    // The PIN itself is never shown back.
    await expect(pin).not.toContainText('4821');
  });

  test('a patient with a PIN changes it', async ({ page }) => {
    await setPinByApi(page, '5739');
    await openSection(page, 'Setting', 'settings-view');
    const pin = section(page);
    await expect(pin.locator('[data-purpose="sms-pin-status"]')).toHaveText('PIN set');
    // The account's session is the proof: no current PIN is asked for (a
    // forgotten PIN can be replaced here).
    await expect(pin.getByLabel('New PIN', { exact: true })).toBeVisible();
    await fillPins(page, '3907');
    await pin.getByRole('button', { name: 'Change PIN' }).click();
    await expect(pin.locator('[data-purpose="sms-pin-success"]')).toHaveText('Your SMS PIN has been changed.');
    expect((await (await page.request.get('/api/backend/users/me/sms-pin')).json()).has_pin).toBe(true);
  });

  test('a PIN the server refuses shows its reason, and a locked PIN says so', async ({ page }) => {
    const until = new Date(Date.now() + 45 * 60_000).toISOString();
    await mockPinState(page, { has_pin: true, locked_until: until });
    await page.route(PIN_URL, async (route) => {
      if (route.request().method() !== 'PUT') return route.fallback();
      await route.fulfill({ status: 422, json: { detail: 'Choose 4 digits that are not all the same and not a sequence like 1234.' } });
    });
    await openSection(page, 'Setting', 'settings-view');
    const pin = section(page);
    await expect(pin.locator('[data-purpose="sms-pin-locked"]')).toContainText('locked until');
    await expect(pin.locator('[data-purpose="sms-pin-locked"]')).toContainText('Choose a new PIN below to unlock it');
    await fillPins(page, '5739');
    await pin.getByRole('button', { name: 'Change PIN' }).click();
    await expect(pin.locator('[data-purpose="sms-pin-error"]')).toContainText('too easy to guess');
    await expect(pin.locator('[data-purpose="sms-pin-success"]')).toHaveCount(0);
  });

  test('SMS commands and the short code are shown only while they work', async ({ page }) => {
    // Off (the test backend, as production today): "coming soon", no number.
    await openSection(page, 'Setting', 'settings-view');
    const pin = section(page);
    await expect(pin.locator('[data-purpose="sms-commands-soon"]')).toContainText('coming soon');
    await expect(pin.locator('[data-purpose="sms-commands"]')).toHaveCount(0);
    await expect(pin.locator('[data-purpose="sms-short-code"]')).toHaveCount(0);

    // On.
    await mockPinState(page, { commands_enabled: true, short_code: '8123' });
    await openSection(page, 'Setting', 'settings-view');
    const commands = pin.locator('[data-purpose="sms-commands"]');
    await expect(commands).toBeVisible();
    await expect(pin.locator('[data-purpose="sms-commands-soon"]')).toHaveCount(0);
    await expect(commands.locator('[data-purpose="sms-short-code"]')).toHaveText('8123');
    const table = commands.getByRole('table', { name: 'Text commands' });
    await expect(table.getByRole('columnheader')).toHaveText(['Text', 'You get back']);
    await expect(table.locator('tbody tr')).toHaveCount(5);
    for (const [word, reply] of [
      ['CARD', 'Your Endod card number'],
      ['APPT', 'Your next appointments and follow-ups'],
      ['RESULT', 'Your latest lab results'],
      ['REPORT', 'Your latest medical report'],
      ['RX', 'Pickup codes for your prescriptions'],
    ]) {
      const row = table.locator(`[data-purpose="sms-command-${word.toLowerCase()}"]`);
      await expect(row).toContainText(`${word} + your PIN`);
      await expect(row).toContainText(reply);
    }

    // The switch on without a number is still "coming soon".
    await page.unrouteAll({ behavior: 'wait' });
    await mockPinState(page, { commands_enabled: true, short_code: null });
    await openSection(page, 'Setting', 'settings-view');
    await expect(pin.locator('[data-purpose="sms-commands-soon"]')).toBeVisible();
    await expect(pin.locator('[data-purpose="sms-commands"]')).toHaveCount(0);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

    test('the same section works on the phone settings screen', async ({ page }) => {
      await mockPinState(page, { has_pin: false, commands_enabled: true, short_code: '8123' });
      await page.goto('/interview/mobile-setting', { waitUntil: 'networkidle' });
      const pin = section(page);
      await pin.scrollIntoViewIfNeeded();
      await expect(pin.getByRole('heading', { name: 'SMS PIN' })).toBeVisible();
      await expect(pin.locator('[data-purpose="sms-commands"]')).toBeVisible();
      // Nothing wider than the phone, the table included.
      for (const box of [await pin.boundingBox(), await pin.getByRole('table').boundingBox()]) {
        expect(box).not.toBeNull();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(390);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

      await fillPins(page, '6142');
      await pin.getByRole('button', { name: 'Set PIN' }).click();
      await expect(pin.locator('[data-purpose="sms-pin-success"]')).toHaveText('Your SMS PIN is set.');
    });
  });

  test.describe('in Amharic', () => {
    test.beforeEach(async ({ page }) => {
      await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'am' } });
      await page.context().clearCookies({ name: 'endod_language' });
    });
    test.afterEach(async ({ page }) => {
      await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'en' } });
      await page.context().clearCookies({ name: 'endod_language' });
    });

    test('everything in the section is translated', async ({ page }) => {
      await mockPinState(page, { has_pin: false, commands_enabled: true, short_code: '8123' });
      await page.goto('/interview', { waitUntil: 'networkidle' });
      await expect(page.locator('html')).toHaveAttribute('lang', 'am');
      await page.locator('aside').getByRole('link', { name: 'ቅንብር', exact: true }).click();
      const pin = section(page);
      await expect(pin.getByRole('heading', { name: 'የSMS ፒን' })).toBeVisible();
      await expect(pin.locator('[data-purpose="sms-pin-status"]')).toHaveText('ገና ፒን የለም');
      await expect(pin.getByLabel('ፒኑን ያረጋግጡ', { exact: true })).toBeVisible();
      const table = pin.getByRole('table', { name: 'የጽሑፍ መልእክት ትዕዛዞች' });
      await expect(table.getByRole('columnheader')).toHaveText(['የሚልኩት', 'የሚያገኙት']);
      await expect(table.locator('[data-purpose="sms-command-card"]')).toContainText('CARD + ፒንዎ');
      await expect(table.locator('[data-purpose="sms-command-card"]')).toContainText('የEndod ካርድ ቁጥርዎ');

      await fillPins(page, '4821', '4822');
      await pin.getByRole('button', { name: 'ፒን አዘጋጅ' }).click();
      await expect(pin.locator('[data-purpose="sms-pin-error"]')).toHaveText('ሁለቱ ፒኖች አይመሳሰሉም።');
      await fillPins(page, '4821');
      await pin.getByRole('button', { name: 'ፒን አዘጋጅ' }).click();
      await expect(pin.locator('[data-purpose="sms-pin-success"]')).toHaveText('የSMS ፒንዎ ተዘጋጅቷል።');
      await expect(pin.locator('[data-purpose="sms-pin-status"]')).toHaveText('ፒን ተዘጋጅቷል');
    });

    test('commands off: "coming soon" in Amharic, no short code', async ({ page }) => {
      await page.goto('/interview', { waitUntil: 'networkidle' });
      await page.locator('aside').getByRole('link', { name: 'ቅንብር', exact: true }).click();
      const pin = section(page);
      await expect(pin.locator('[data-purpose="sms-commands-soon"]')).toContainText('በቅርቡ ይጀምራል');
      await expect(pin.locator('[data-purpose="sms-short-code"]')).toHaveCount(0);
    });
  });
});
