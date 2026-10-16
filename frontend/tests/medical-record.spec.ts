import { test, expect } from '@playwright/test';
import { openSection } from './helpers';

// Medical records against the real backend (the shared test patient).

async function setHealthConsent(request: import('@playwright/test').APIRequestContext, value: boolean) {
  const response = await request.patch('/api/backend/users/me/consent', { data: { treatment_processing: value } });
  expect(response.ok()).toBeTruthy();
}

test.describe('Interview — Medical Records', () => {
  test('adding a past visit shows it as self-reported and updates the summary', async ({ page }) => {
    await setHealthConsent(page.request, true);
    const facility = `Black Lion ${Date.now().toString(36)}`;
    await openSection(page, 'Medical Record', 'medical-record-view');
    const visitsBefore = Number(await page.locator('[data-purpose="stat-total-visits"] p').last().textContent());

    await page.locator('[data-purpose="add-record"]').click();
    const modal = page.locator('[data-purpose="record-modal"]');
    await modal.locator('#record-facility').fill(facility);
    await modal.locator('#record-department').fill('Cardiology');
    await modal.locator('#record-diagnosis').fill('High blood pressure');
    await modal.locator('#record-medications').fill('Amlodipine, Aspirin');
    await modal.locator('#record-follow-up').fill('30');
    await modal.getByRole('button', { name: 'Save visit' }).click();
    await expect(modal).toHaveCount(0);

    const row = page.locator('[data-purpose^="record-"]', { hasText: facility });
    await expect(row).toContainText('High blood pressure');
    await expect(row).toContainText('Amlodipine, Aspirin');
    await expect(row).toContainText('30 days');
    await expect(row.locator('[data-purpose="record-source"]')).toHaveText('Self-reported');
    await expect(page.locator('[data-purpose="stat-total-visits"] p').last()).toHaveText(String(visitsBefore + 1));
  });

  test('without consent, adding a visit explains why and links to Settings', async ({ page }) => {
    await setHealthConsent(page.request, false);
    try {
      await openSection(page, 'Medical Record', 'medical-record-view');
      await page.locator('[data-purpose="add-record"]').click();
      await page.locator('#record-facility').fill('Any Clinic');
      await page.getByRole('button', { name: 'Save visit' }).click();
      const error = page.locator('[data-purpose="record-error"]');
      await expect(error).toContainText('Consent');
      await error.getByRole('button', { name: 'Open Settings' }).click();
      await expect(page.locator('[data-purpose="settings-view"]')).toBeVisible();
    } finally {
      await setHealthConsent(page.request, true);
    }
  });
});
