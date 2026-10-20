import { test, expect, type Page } from './fixtures';

// While a page's data loads, it shows a placeholder in the shape of what is
// coming (data-purpose="skeleton"), never "Loading…" or a blank area; the
// content then takes its place. Each test holds the data back on purpose.

/** Hold back responses matching `pattern` until `release()` is called. */
async function holdBack(page: Page, pattern: string | RegExp) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route(pattern, async (route) => {
    await gate;
    await route.continue();
  });
  return release;
}

/** "Loading" text a sighted user would see (screen-reader-only text excluded). */
async function visibleLoadingText(page: Page, scope = 'body') {
  return page.locator(scope).evaluate((root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let count = 0;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (/Loading/.test(node.textContent ?? '') && !node.parentElement?.closest('.sr-only')) count += 1;
    }
    return count;
  });
}

test.describe('Loading placeholders', () => {
  test('home: the summary cards', async ({ page }) => {
    const release = await holdBack(page, '**/api/backend/users/me/appointments**');
    await page.goto('/interview', { waitUntil: 'domcontentloaded' });
    const card = page.locator('[data-purpose="home-next-appointment"]');
    await expect(card.locator('[data-purpose="skeleton"]')).toBeVisible();
    expect(await visibleLoadingText(page)).toBe(0);
    release();
    await expect(card.locator('[data-purpose="skeleton"]')).toHaveCount(0);
    await expect(card.locator('h2')).toBeVisible();
  });

  for (const [nav, endpoint, done] of [
    ['Appointment', '**/api/backend/users/me/appointments**', '[data-purpose^="appointment-card-"], [data-purpose="appointment-empty"]'],
    ['Medical Record', '**/api/backend/users/me/records**', '[data-purpose="record-source"], [data-purpose="records-empty"]'],
    ['Notification', '**/api/backend/users/me/inbox**', '[data-purpose^="notif-group-"], [data-purpose="notif-empty"]'],
    ['Booking', '**/api/backend/users/me/care/facilities**', '[data-purpose="hospital-grid"]'],
    ['Setting', '**/api/backend/users/me', '[data-purpose="digital-card-section"]'],
  ] as const) {
    test(`${nav}: a placeholder until the data arrives`, async ({ page }) => {
      await page.goto('/interview', { waitUntil: 'networkidle' });
      const release = await holdBack(page, endpoint);
      await page.locator('aside').getByRole('link', { name: nav }).click();
      await expect(page.locator('main [data-purpose="skeleton"]').first()).toBeAttached();
      // Screen readers hear one "Loading" status; nothing visible says it.
      await expect(page.locator('main').getByRole('status').first()).toHaveText(/\S/);
      expect(await visibleLoadingText(page, 'main')).toBe(0);
      release();
      await expect(page.locator(done).first()).toBeVisible();
      await expect(page.locator('main [data-purpose="skeleton"]')).toHaveCount(0);
    });
  }

  test('health card: a card-shaped placeholder', async ({ page }) => {
    const release = await holdBack(page, '**/api/backend/users/me');
    await page.goto('/health-card', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-purpose="skeleton"]')).toBeVisible();
    release();
    await expect(page.locator('[data-purpose="skeleton"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="download-image"]')).toBeVisible();
  });

  test('a failed load shows the error, not an endless placeholder', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.route('**/api/backend/users/me/records**', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"Records are unavailable."}' }));
    await page.locator('aside').getByRole('link', { name: 'Medical Record' }).click();
    await expect(page.locator('main').getByRole('alert')).toContainText('Records are unavailable.');
    await expect(page.locator('main [data-purpose="skeleton"]')).toHaveCount(0);
  });

  test('placeholders pulse, and hold still for people who ask for less motion', async ({ browser }) => {
    for (const [reducedMotion, expected] of [['no-preference', 'pulse'], ['reduce', 'none']] as const) {
      const context = await browser.newContext({ reducedMotion, storageState: 'tests/.auth/patient.json' });
      const page = await context.newPage();
      await page.route('**/api/backend/users/me/appointments**', () => new Promise(() => undefined));
      await page.goto('/interview', { waitUntil: 'domcontentloaded' });
      const bone = page.locator('[data-purpose="home-next-appointment"] [data-purpose="skeleton"] span[aria-hidden]').first();
      await expect(bone).toBeVisible();
      expect(await bone.evaluate((el) => getComputedStyle(el).animationName)).toBe(expected);
      await context.close();
    }
  });

  test('records totals wait for the data instead of showing 0', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.route('**/api/backend/users/me/records**', () => new Promise(() => undefined));
    await page.locator('aside').getByRole('link', { name: 'Medical Record' }).click();
    await expect(page.locator('[data-purpose="stat-total-visits"] [aria-hidden]')).toBeVisible();
    await expect(page.locator('[data-purpose="stat-total-visits"]')).not.toContainText('0');
  });

  test('a booking search dims the current results and a failure clears them', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.locator('aside').getByRole('link', { name: 'Booking' }).click();
    await expect(page.locator('#hospital-grid .hospital-card').first()).toBeVisible();
    const release = await holdBack(page, '**/api/backend/users/me/care/facilities**');
    await page.locator('[data-purpose="hospital-search"]').fill('Tikur');
    await expect(page.locator('[data-purpose="hospital-grid"]')).toHaveAttribute('aria-busy', 'true');
    release();
    await expect(page.locator('[data-purpose="hospital-grid"]')).toHaveAttribute('aria-busy', 'false');
    await page.unroute('**/api/backend/users/me/care/facilities**');
    await page.route('**/api/backend/users/me/care/facilities**', (route) =>
      route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"Directory unavailable."}' }));
    await page.locator('[data-purpose="hospital-search"]').fill('Peter');
    await expect(page.locator('main').getByRole('alert')).toContainText('Directory unavailable.');
    await expect(page.locator('#hospital-grid .hospital-card')).toHaveCount(0);
  });
});
