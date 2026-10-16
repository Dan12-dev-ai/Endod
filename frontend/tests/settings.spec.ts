import { test, expect, type APIRequestContext } from '@playwright/test';
import { openSection } from './helpers';

// Settings against the real backend. These change the shared test patient,
// so every test puts back what it changed, even when it fails.

async function patch(request: APIRequestContext, path: string, data: Record<string, unknown>) {
  const response = await request.patch(`/api/backend/users/me${path}`, { data });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test.describe('Interview — Settings', () => {
  test('shows the signed-in patient', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    await expect(page.getByRole('heading', { name: 'Account Settings' })).toBeVisible();
    for (const section of ['user-profile-section', 'location-settings-section', 'privacy-section', 'security-settings-section', 'digital-card-section']) {
      await expect(page.locator(`[data-purpose="${section}"]`)).toBeVisible();
    }
    await expect(page.locator('#first-name')).toHaveValue('Test');
    await expect(page.locator('#last-name')).toHaveValue('Patient');
    await expect(page.locator('#patient-id-field')).toHaveValue(/^DE\d{6}$/);
    await expect(page.locator('#email-address')).toHaveValue(/^e2e-\d+@example\.com$/);
    // Removed: the fake location detection.
    await expect(page.getByRole('button', { name: 'Detect Current Location' })).toHaveCount(0);
  });

  test('saving the profile persists and updates the header', async ({ page }) => {
    try {
      await openSection(page, 'Setting', 'settings-view');
      await page.locator('#first-name').fill('Testa');
      await page.getByRole('button', { name: 'Save Changes' }).click();
      await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Profile Saved');
      await expect(page.locator('header')).toContainText('Testa Patient');

      await page.reload();
      await page.locator('aside').getByRole('link', { name: 'Setting' }).click();
      await expect(page.locator('#first-name')).toHaveValue('Testa');
    } finally {
      await patch(page.request, '', { first_name: 'Test' });
    }
  });

  test('saving one section keeps unsaved edits in another', async ({ page }) => {
    try {
      await openSection(page, 'Setting', 'settings-view');
      await page.locator('#address-line').fill('Bole Road 12');
      await page.locator('#first-name').fill('Testb');
      await page.getByRole('button', { name: 'Save Changes' }).click();
      await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Profile Saved');
      await expect(page.locator('#address-line')).toHaveValue('Bole Road 12');
    } finally {
      await patch(page.request, '', { first_name: 'Test' });
    }
  });

  test('the only sign-in email cannot be removed', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    await page.locator('#email-address').fill('');
    await page.getByRole('button', { name: 'Save Changes' }).click();
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Verify a phone number before removing it');
    const profile = await (await page.request.get('/api/backend/users/me')).json();
    expect(profile.email).toMatch(/@example\.com$/);
  });

  test('a phone is added only through a code', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    await expect(page.locator('#phone-number')).toHaveAttribute('readonly', '');
    await page.locator('[data-purpose="change-phone"]').click();
    const phone = `09${String(10_000_000 + Math.floor(Math.random() * 89_999_999)).slice(0, 8)}`;
    await page.locator('#new-phone').fill(phone);
    await page.getByRole('button', { name: 'Send code' }).click();
    await expect(page.locator('#phone-code')).toBeVisible();
    await page.locator('#phone-code').fill('000000');
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('[data-purpose="phone-error"]')).toContainText(/code/i);
    await page.locator('[data-purpose="phone-change"]').getByRole('button', { name: 'Cancel' }).click();
    await expect(page.locator('[data-purpose="phone-change"]')).toHaveCount(0);
  });

  test('location and radius are saved', async ({ page }) => {
    try {
      await openSection(page, 'Setting', 'settings-view');
      await page.locator('#city').fill('Hawassa');
      await page.locator('#country').selectOption('ET');
      await page.locator('#radius-slider').fill('40');
      await page.getByRole('button', { name: 'Update Location' }).click();
      await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Location Updated');

      const profile = await (await page.request.get('/api/backend/users/me')).json();
      expect(profile.city).toBe('Hawassa');
      expect(profile.preferences.care_search_radius_km).toBe(40);
    } finally {
      await patch(page.request, '', { city: null, address_line: null });
      await patch(page.request, '/preferences', { care_search_radius_km: null });
    }
  });

  test('password rules follow the backend and mismatches are caught', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    await page.locator('#new-password').fill('short');
    await expect(page.locator('[data-purpose="req-length"]')).not.toHaveClass(/emerald/);
    await page.locator('#new-password').fill('LongEnoughPass');
    await expect(page.locator('[data-purpose="req-length"]')).toHaveClass(/emerald/);
    await expect(page.locator('[data-purpose="req-upper"]')).toHaveClass(/emerald/);
    await page.locator('#confirm-password').fill('Different1');
    await expect(page.locator('#match-indicator')).toContainText('do not match');

    await page.locator('#current-password').fill('WrongCurrent1');
    await page.locator('#confirm-password').fill('LongEnoughPass');
    await page.getByRole('button', { name: 'Update Password' }).click();
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Current password is incorrect');
  });

  test('health card details need consent, then save; withdrawing clears them', async ({ page }) => {
    try {
      await patch(page.request, '/consent', { treatment_processing: false });
      await openSection(page, 'Setting', 'settings-view');
      await expect(page.locator('[data-purpose="card-needs-consent"]')).toBeVisible();

      await page.locator('[data-purpose="consent-health"]').check();
      await expect(page.locator('#blood-group')).toBeVisible();
      await page.locator('#blood-group').selectOption('A-');
      await page.locator('#allergies').fill('Latex, Penicillin');
      await page.getByRole('button', { name: 'Save Card Details' }).click();
      await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Card Updated');

      await page.getByRole('button', { name: 'Show Card Preview' }).click();
      const preview = page.locator('[data-purpose="card-preview"]');
      await expect(preview).toContainText('Test Patient');
      await expect(preview).toContainText('A-');
      await expect(preview).toContainText('Latex, Penicillin');

      const health = await (await page.request.get('/api/backend/users/me/health-profile')).json();
      expect(health.blood_type).toBe('A-');
      expect(health.allergies).toEqual(['Latex', 'Penicillin']);

      await page.locator('[data-purpose="consent-health"]').uncheck();
      await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Consent Withdrawn');
      await expect(preview).not.toContainText('Latex');
    } finally {
      await patch(page.request, '/consent', { treatment_processing: true });
      await patch(page.request, '/health-profile', { blood_type: null, allergies: [] });
    }
  });

  test('notification preferences are saved', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    const email = page.locator('[data-purpose="pref-email"]');
    const before = await email.isChecked();
    try {
      await email.setChecked(!before);
      await expect(email).toBeEnabled();
      const prefs = await (await page.request.get('/api/backend/users/me/preferences')).json();
      expect(prefs.email_notifications).toBe(!before);
    } finally {
      await patch(page.request, '/preferences', { email_notifications: before });
    }
  });
});
