import { test, expect } from './fixtures';
import { HOSPITAL_SIGNUP_URL, COMPANY_SIGNUP_URL } from '../app/lib/links';

// The landing page's pointer for clinics and hospitals to the hospital portal.

test.describe('Landing page: facility sign-up', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('links clinics and hospitals to the hospital portal sign-up', async ({ page }) => {
    expect(HOSPITAL_SIGNUP_URL).toBe('https://hospital.endod-health.com/signup');
    await page.goto('/');
    const link = page.locator('[data-purpose="facility-signup-link"]');
    await expect(link).toBeVisible();
    await expect(link).toHaveText('Register your clinic or hospital');
    await expect(link).toHaveAttribute('href', HOSPITAL_SIGNUP_URL);
    await expect(page.locator('[data-purpose="facility-signup"]')).toContainText('Run a clinic or hospital?');
    const company = page.locator('[data-purpose="company-signup-link"]');
    await expect(company).toHaveText('Register your company');
    await expect(company).toHaveAttribute('href', COMPANY_SIGNUP_URL);
  });

  test('is in Amharic too, with the same link', async ({ page, context }) => {
    await context.addCookies([{ name: 'endod_language', value: 'am', url: 'http://localhost:3100' }]);
    await page.goto('/');
    const link = page.locator('[data-purpose="facility-signup-link"]');
    await expect(link).toHaveText('ክሊኒክዎን ወይም ሆስፒታልዎን ያስመዝግቡ');
    await expect(link).toHaveAttribute('href', HOSPITAL_SIGNUP_URL);
  });

  test('fits on a phone', async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await page.goto('/');
    await expect(page.locator('[data-purpose="facility-signup-link"]')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
