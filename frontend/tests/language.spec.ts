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

  test('fits on a small phone', async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const header = page.locator('header').first();
    await expect(header.locator('[data-purpose="language-select"]')).toBeVisible();
    await expect(page.locator('[data-purpose="sign-out"]')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe('Phone tab bar', () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test('every tab opens its section, and there is no Live tab', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const bar = page.locator('[data-purpose="mobile-nav"]');
    await expect(bar.getByText('Live', { exact: true })).toHaveCount(0);
    await expect(bar.locator('button')).toHaveCount(6);
    await bar.locator('[data-purpose="mobile-nav-setting"]').click();
    await expect(page.locator('[data-purpose="digital-card-section"]')).toBeVisible();
    await expect(bar.locator('[data-purpose="mobile-nav-setting"]')).toHaveAttribute('aria-current', 'page');
    // The dev-only Next.js badge covers this corner in tests; real phones have no badge.
    await bar.locator('[data-purpose="mobile-nav-home"]').dispatchEvent('click');
    await expect(page.getByText('Welcome, Test')).toBeVisible();
  });
});
