import { test, expect } from './fixtures';
import { openSection } from './helpers';

// Visits the patient adds themselves, on the History page (the shared test patient).

async function setHealthConsent(request: import('@playwright/test').APIRequestContext, value: boolean) {
  const response = await request.patch('/api/backend/users/me/consent', { data: { treatment_processing: value } });
  expect(response.ok()).toBeTruthy();
}

test.describe('Interview — Medical Records', () => {
  test('adding a past visit shows it as self-reported and updates the summary', async ({ page }) => {
    await setHealthConsent(page.request, true);
    const facility = `Black Lion ${Date.now().toString(36)}`;
    await openSection(page, 'Medical Record', 'medical-record-view');
    // The summary has numbers once the history has loaded.
    await expect(page.locator('[data-purpose="stat-total"] p').last()).toHaveText(/^\d+$/);
    const before = Number(await page.locator('[data-purpose="stat-total"] p').last().textContent());
    const selfBefore = Number(await page.locator('[data-purpose="stat-self"] p').last().textContent());

    await page.locator('[data-purpose="add-record"]').click();
    const modal = page.locator('[data-purpose="record-modal"]');
    await modal.locator('#record-facility').fill(facility);
    await modal.locator('#record-department').fill('Cardiology');
    await modal.locator('#record-diagnosis').fill('High blood pressure');
    await modal.locator('#record-medications').fill('Amlodipine, Aspirin');
    await modal.locator('#record-follow-up').fill('30');
    await modal.getByRole('button', { name: 'Save visit' }).click();
    await expect(modal).toHaveCount(0);

    const row = page.locator('[data-purpose="history-item"]', { hasText: facility });
    await expect(row.locator('[data-purpose="record-source"]')).toHaveText('Self-reported');
    await row.getByRole('button', { expanded: false }).click();
    const detail = page.locator('[data-purpose="medical-record-detail"]');
    await expect(detail).toBeVisible();
    await expect(detail).toContainText('High blood pressure');
    await expect(detail).toContainText('Amlodipine, Aspirin');
    await expect(detail).toContainText('30 days');

    await page.locator('[data-purpose="back-link"]').click();
    await expect(page.locator('[data-purpose="medical-record-view"]')).toBeVisible();

    await expect(page.locator('[data-purpose="stat-total"] p').last()).toHaveText(String(before + 1));
    await expect(page.locator('[data-purpose="stat-self"] p').last()).toHaveText(String(selfBefore + 1));

    // The Self-reported tab keeps the patient's own entries.
    await page.locator('[data-purpose="history-tab-self"]').click();
    await expect(row).toBeVisible();
    await expect(page.locator('[data-purpose="history-item"] [data-purpose="record-source"]', { hasText: 'Verified' })).toHaveCount(0);
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
