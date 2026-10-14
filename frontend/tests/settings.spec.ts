import { test, expect, type Page } from '@playwright/test';

async function openSettings(page: Page) {
  await page.locator('aside').getByRole('link', { name: 'Setting' }).click();
  await expect(page.locator('[data-purpose="settings-view"]')).toBeVisible();
}

test.describe('Interview — Settings page (simplified)', () => {
  test.beforeEach(async ({ page }) => {
    page.on('dialog', (dialog) => dialog.dismiss());
  });

  test('Settings page renders the three sections', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Page header
    await expect(page.getByRole('heading', { name: 'Account Settings' })).toBeVisible();

    // Sections present
    await expect(page.locator('[data-purpose="user-profile-section"]')).toBeVisible();
    await expect(page.locator('[data-purpose="location-settings-section"]')).toBeVisible();
    await expect(page.locator('[data-purpose="security-settings-section"]')).toBeVisible();
    await expect(page.locator('[data-purpose="digital-card-section"]')).toBeVisible();

    // Removed sections should NOT be present
    await expect(page.locator('[data-purpose="privacy-preferences"]')).toHaveCount(0);

    // Profile fields have expected default values
    await expect(page.locator('#first-name')).toHaveValue('Daniel');
    await expect(page.locator('#last-name')).toHaveValue('Everett');
    await expect(page.locator('#patient-id-field')).toHaveValue('DE482731');
    await expect(page.locator('#email-address')).toHaveValue('daniel.everett@healthmail.com');
    await expect(page.locator('#phone-number')).toHaveValue('+1 (617) 555-0198');

    // Removed fields should NOT be present
    await expect(page.locator('#preferred-name')).toHaveCount(0);
    await expect(page.getByText('Two-Factor Authentication')).toHaveCount(0);
  });

  test('Profile save shows toast', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Change first name
    await page.locator('#first-name').fill('Jonathan');
    // Submit form
    await page.getByRole('button', { name: 'Save Changes' }).click();

    // Toast should appear
    const toast = page.locator('[data-purpose="toast-notification"]');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText('Profile Saved');
    await expect(toast).toContainText('Personal details saved and synced.');
  });

  test('Password strength meter updates', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Type a strong password
    await page.locator('#new-password').fill('Str0ng!Pass');
    await expect(page.locator('#strength-label')).toHaveText('Strong');

    // Type a weak password (8+ chars but nothing else = score 1 = Weak)
    await page.locator('#new-password').fill('abcdefgh');
    await expect(page.locator('#strength-label')).toHaveText('Weak');

    // Confirm password match
    await page.locator('#new-password').fill('MyP@ssw0rd');
    await page.locator('#confirm-password').fill('MyP@ssw0rd');
    await expect(page.locator('#match-indicator')).toContainText('Passwords match');
  });

  test('Zip code is optional', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Zip code should not have required attribute
    await expect(page.locator('#zipcode')).not.toHaveAttribute('required', /.*/);
  });

  test('Auto-detect location updates fields', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Click detect location
    await page.getByRole('button', { name: 'Detect Current Location' }).click();

    // Wait for the simulated GPS delay (700ms)
    await page.waitForTimeout(1000);
    await expect(page.locator('#address-line')).toHaveValue('100 Longwood Ave');
    await expect(page.locator('#city')).toHaveValue('Boston');
    await expect(page.locator('#zipcode')).toHaveValue('02115');
  });

  test('Reset on exit: leaving Settings clears state; re-entering shows fresh view', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Change some settings
    await page.locator('#first-name').fill('Changed');
    await page.locator('#new-password').fill('Test123!@#');

    // Leave Settings
    await page.locator('aside').getByRole('link', { name: 'Live Discussion' }).click();
    await expect(page.locator('[data-purpose="settings-view"]')).toHaveCount(0);
    await page.waitForTimeout(300);

    // Re-enter Settings -> fresh values
    await page.locator('aside').getByRole('link', { name: 'Setting' }).click();
    await expect(page.locator('[data-purpose="settings-view"]')).toBeVisible();
    await expect(page.locator('#first-name')).toHaveValue('Daniel');
    await expect(page.locator('#new-password')).toHaveValue('');
  });

  test('Digital card preview toggles visibility', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Preview hidden by default
    await expect(page.locator('[data-purpose="card-preview"]')).toHaveCount(0);

    // Click Show Card Preview
    await page.getByRole('button', { name: 'Show Card Preview' }).click();
    await expect(page.locator('[data-purpose="card-preview"]')).toBeVisible();

    // Click Hide Card Preview
    await page.getByRole('button', { name: 'Hide Card Preview' }).click();
    await expect(page.locator('[data-purpose="card-preview"]')).toHaveCount(0);
  });

  test('Digital card save shows toast', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Change blood group
    await page.locator('#blood-group').selectOption('A-');
    // Save card
    await page.getByRole('button', { name: 'Save Card Details' }).click();

    // Toast should appear
    const toast = page.locator('[data-purpose="toast-notification"]');
    await expect(toast).toBeVisible();
    await expect(toast).toContainText('Card Updated');
  });

  test('Digital card preview reflects edited fields', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openSettings(page);

    // Show preview
    await page.getByRole('button', { name: 'Show Card Preview' }).click();
    const preview = page.locator('[data-purpose="card-preview"]');
    await expect(preview).toBeVisible();
    await expect(preview).toContainText('Daniel Everett');

    // Change allergies
    await page.locator('#allergies').fill('Latex');
    await expect(preview).toContainText('Latex');
  });
});
