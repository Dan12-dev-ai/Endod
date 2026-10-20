import { test, expect } from '@playwright/test';

// The language switch in the dashboard, and the choice following the account.

test.describe('Dashboard language', () => {
  test.afterEach(async ({ page }) => {
    // The shared test patient goes back to English for the other specs.
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'en' } });
  });

  test('the dashboard bar switches language and saves it to the account', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const header = page.locator('header').first();
    await expect(header.locator('[data-purpose="language-select"]')).toContainText('English');

    await header.locator('[data-purpose="language-select"]').click();
    await header.locator('[data-purpose="language-option-am"]').click();
    await expect(header.locator('[data-purpose="language-select"]')).toContainText('አማርኛ');
    await expect(page.locator('html')).toHaveAttribute('lang', 'am');
    // Copy changes without a reload.
    await expect(page.locator('[data-purpose="sign-out"]')).not.toHaveText('Sign out');

    await expect
      .poll(async () => (await (await page.request.get('/api/backend/users/me/preferences')).json()).language)
      .toBe('am');
  });

  test('a device with no choice of its own takes the account language', async ({ page, context }) => {
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'am' } });
    await context.clearCookies({ name: 'endod_language' });
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await expect(page.locator('html')).toHaveAttribute('lang', 'am');
  });

  test('the menu closes on Escape and outside clicks', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const header = page.locator('header').first();
    await header.locator('[data-purpose="language-select"]').click();
    await expect(page.locator('[data-purpose="language-menu"]')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-purpose="language-menu"]')).toHaveCount(0);
    await header.locator('[data-purpose="language-select"]').click();
    await page.locator('main').first().click({ position: { x: 5, y: 5 } });
    await expect(page.locator('[data-purpose="language-menu"]')).toHaveCount(0);
  });

  test('fits on a small phone, in both languages', async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    for (const language of ['en', 'am']) {
      await page.request.patch('/api/backend/users/me/preferences', { data: { language } });
      await page.goto('/interview', { waitUntil: 'networkidle' });
      await expect(page.locator('html')).toHaveAttribute('lang', language);
      const box = await page.locator('[data-purpose="sign-out"]').boundingBox();
      expect(box, language).not.toBeNull();
      expect(box!.x + box!.width, language).toBeLessThanOrEqual(360);
      expect(box!.height, `${language}: sign out on one line`).toBeLessThan(40);
    }
  });

  test('a device that already has a language follows the account', async ({ page }) => {
    // This device last showed English; the patient then chose Amharic elsewhere.
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'am' } });
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await expect(page.locator('html')).toHaveAttribute('lang', 'am');
  });

  test('the menu works from the keyboard', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const trigger = page.locator('header [data-purpose="language-select"]');
    await expect(trigger).toHaveAttribute('aria-label', /English/);
    await trigger.focus();
    await page.keyboard.press('ArrowDown');
    await expect(page.locator('[data-purpose="language-option-en"]')).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(page.locator('[data-purpose="language-option-am"]')).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-purpose="language-menu"]')).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.press('Enter');
    await page.keyboard.press('End');
    await page.keyboard.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('lang', 'am');
    // The account save runs in the background: let it land before afterEach
    // resets the account, or it could land after and leak into the next test.
    await expect
      .poll(async () => (await (await page.request.get('/api/backend/users/me/preferences')).json()).language)
      .toBe('am');
  });
});

test.describe('Phone tab bar', () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test('every tab opens its section, and there is no Live tab', async ({ page }) => {
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'en' } });
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const bar = page.locator('[data-purpose="mobile-nav"]');
    await expect(bar.getByText('Live', { exact: true })).toHaveCount(0);
    await expect(bar.locator('button')).toHaveCount(7);
    await bar.locator('[data-purpose="mobile-nav-setting"]').click();
    await expect(page.locator('[data-purpose="digital-card-section"]')).toBeVisible();
    await expect(bar.locator('[data-purpose="mobile-nav-setting"]')).toHaveAttribute('aria-current', 'page');
    // The dev-only Next.js badge covers this corner in tests; real phones have no badge.
    await bar.locator('[data-purpose="mobile-nav-home"]').dispatchEvent('click');
    await expect(page.getByText('Welcome, Test')).toBeVisible();
  });
});

test.describe('A choice made while signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('is copied to the account at sign-in', async ({ page }) => {
    const { email, password } = JSON.parse(
      (await import('node:fs')).readFileSync('tests/.auth/credentials.json', 'utf8'),
    ) as { email: string; password: string };
    await page.goto('/', { waitUntil: 'networkidle' });
    await page.locator('[data-purpose="language-select"]').click();
    await page.locator('[data-purpose="language-option-am"]').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'am');

    await page.goto('/login', { waitUntil: 'networkidle' });
    await page.locator('input[type="password"]').fill(password);
    await page.locator('input:not([type=password])').first().fill(email);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/interview$/);
    await expect(page.locator('html')).toHaveAttribute('lang', 'am');
    const prefs = await (await page.request.get('/api/backend/users/me/preferences')).json();
    expect(prefs.language).toBe('am');
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'en' } });
  });
});
