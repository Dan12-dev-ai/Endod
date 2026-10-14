import { test, expect, type Page } from '@playwright/test';

async function openMedicalRecord(page: Page) {
  await page.locator('aside').getByRole('link', { name: 'Medical Record' }).click();
  await expect(page.locator('[data-purpose="medical-record-view"]')).toBeVisible();
}

test.describe('Interview — Medical Record page (simplified list)', () => {
  test.beforeEach(async ({ page }) => {
    page.on('dialog', (dialog) => dialog.dismiss());
  });

  test('Medical Record page renders the records list', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openMedicalRecord(page);

    // Page header
    await expect(page.getByRole('heading', { name: 'Medical Records' })).toBeVisible();

    // Records table with 3 rows
    const rows = page.locator('[data-purpose^="record-"]');
    await expect(rows).toHaveCount(3);

    // Row 1: Apex Heart
    const r1 = page.locator('[data-purpose="record-1"]');
    await expect(r1).toContainText('Apex Heart & Health Institute');
    await expect(r1).toContainText('Aug 24, 2026');
    await expect(r1).toContainText('Chest Discomfort');
    await expect(r1).toContainText('Atorvastatin 20mg');
    await expect(r1).toContainText('7 days');

    // Row 2: City Care
    const r2 = page.locator('[data-purpose="record-2"]');
    await expect(r2).toContainText('City Care Diagnostics Center');
    await expect(r2).toContainText('May 19, 2026');
    await expect(r2).toContainText('Blood Panel Screening');
    await expect(r2).toContainText('No follow-up');

    // Row 3: Walgreens
    const r3 = page.locator('[data-purpose="record-3"]');
    await expect(r3).toContainText('Walgreens Pharmacy #4102');
    await expect(r3).toContainText('Jan 14, 2026');
    await expect(r3).toContainText('Seasonal Bronchitis');
    await expect(r3).toContainText('Azithromycin 500mg');

    // Table headers present
    await expect(page.locator('[data-purpose="medical-records-table"] thead')).toContainText('Date');
    await expect(page.locator('[data-purpose="medical-records-table"] thead')).toContainText('Hospital');
    await expect(page.locator('[data-purpose="medical-records-table"] thead')).toContainText('Disease');
    await expect(page.locator('[data-purpose="medical-records-table"] thead')).toContainText('Drug');
    await expect(page.locator('[data-purpose="medical-records-table"] thead')).toContainText('Followup');

    // Removed sections should NOT exist
    await expect(page.locator('[data-purpose="patient-summary-card"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="history-category-tabs"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="chronic-family-summary"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="record-detail-modal"]')).toHaveCount(0);
  });

  test('Sidebar shows "Medical Record" not "Followup"', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);

    await expect(page.locator('aside').getByRole('link', { name: 'Medical Record' })).toBeVisible();
    await expect(page.locator('aside').getByRole('link', { name: 'Followup' })).toHaveCount(0);
  });
});
