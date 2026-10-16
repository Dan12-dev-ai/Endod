import { test, expect } from '@playwright/test';
import { openSection } from './helpers';

// Settings against the real backend. These change the shared test patient,
// so every test puts back what it changed.

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
    // Removed: the fake location detection and the meaningless email badge.
    await expect(page.getByRole('button', { name: 'Detect Current Location' })).toHaveCount(0);
  });

  test('saving the profile persists and updates the header', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    await page.locator('#first-name').fill('Testa');
    await page.getByRole('button', { name: 'Save Changes' }).click();
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Profile Saved');
    await expect(page.locator('header')).toContainText('Testa Patient');

    await page.reload();
    await page.locator('aside').getByRole('link', { name: 'Setting' }).click();
    await expect(page.locator('#first-name')).toHaveValue('Testa');

    await page.locator('#first-name').fill('Test');
    await page.getByRole('button', { name: 'Save Changes' }).click();
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Profile Saved');
  });

  test('location and radius are saved', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    await page.locator('#city').fill('Hawassa');
    await page.locator('#country').selectOption('ET');
    await page.locator('#radius-slider').fill('40');
    await page.getByRole('button', { name: 'Update Location' }).click();
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Location Updated');

    const profile = await (await page.request.get('/api/backend/users/me')).json();
    expect(profile.city).toBe('Hawassa');
    expect(profile.preferences.care_search_radius_km).toBe(40);
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

  test('health card details need consent, then save', async ({ page }) => {
    await page.request.patch('/api/backend/users/me/consent', { data: { treatment_processing: false } });
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
  });

  test('notification preferences are saved', async ({ page }) => {
    await openSection(page, 'Setting', 'settings-view');
    const email = page.locator('[data-purpose="pref-email"]');
    const before = await email.isChecked();
    await email.setChecked(!before);
    await expect(email).toBeEnabled();
    const prefs = await (await page.request.get('/api/backend/users/me/preferences')).json();
    expect(prefs.email_notifications).toBe(!before);
    await email.setChecked(before);
    await expect(email).toBeEnabled();
  });
});
