import { test, expect, type Page } from '@playwright/test';

async function openAppointment(page: Page) {
  await page.locator('aside').getByRole('link', { name: 'Appointment' }).click();
  await expect(page.locator('[data-purpose="appointment-view"]')).toBeVisible();
}

test.describe('Interview — Appointment page (simplified)', () => {
  test.beforeEach(async ({ page }) => {
    page.on('dialog', (dialog) => dialog.dismiss());
  });

  test('Appointment page renders stat cards and appointment list', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openAppointment(page);

    // Page header
    await expect(page.getByRole('heading', { name: 'Appointments' })).toBeVisible();

    // Only 2 stat cards (Next Visit, Virtual Follow-up)
    await expect(page.getByText('Next Appointment')).toBeVisible();
    await expect(page.getByText('Virtual Follow-up')).toBeVisible();
    await expect(page.getByText('Pending Action')).toHaveCount(0);
    await expect(page.getByText('Assigned Providers')).toHaveCount(0);

    // 3 appointment cards
    await expect(page.locator('[data-purpose="appointment-card-1"]')).toBeVisible();
    await expect(page.locator('[data-purpose="appointment-card-2"]')).toBeVisible();
    await expect(page.locator('[data-purpose="appointment-card-3"]')).toBeVisible();
  });

  test('Appointment cards show only name, address, time, miles, est drive', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openAppointment(page);

    const card1 = page.locator('[data-purpose="appointment-card-1"]');
    await expect(card1).toContainText('Dr. Marcus Vance, MD');
    await expect(card1).toContainText('Apex Heart & Health Institute');
    await expect(card1).toContainText('Tomorrow, 10:30 AM');
    await expect(card1).toContainText('3.2 miles');
    await expect(card1).toContainText('Est. 12 min drive');

    // Should NOT contain removed elements
    await expect(card1).not.toContainText('Cardiology Specialist');
    await expect(card1).not.toContainText('Clinical Reason');
    await expect(card1).not.toContainText('Get Directions');
    await expect(card1).not.toContainText('Cancel');

    // Only Reschedule button should exist
    await expect(card1.getByRole('button', { name: 'Reschedule' })).toBeVisible();
    await expect(card1.getByRole('button', { name: 'Cancel' })).toHaveCount(0);
  });

  test('Tab switching: upcoming -> past -> cancelled', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openAppointment(page);

    // Upcoming is default
    await expect(page.locator('[data-purpose="appointment-card-1"]')).toBeVisible();

    // Switch to Past -> shows past cards with same structure
    await page.locator('[data-purpose="appointment-tab-past"]').click();
    await expect(page.locator('[data-purpose="appointment-past-list"]')).toBeVisible();
    await expect(page.locator('[data-purpose="appointment-card-1"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="past-card-1"]')).toContainText('ENDOD AI Emergency Live Consultation');
    await expect(page.locator('[data-purpose="past-card-1"]')).toContainText('Oct 11, 10:24 AM');
    await expect(page.locator('[data-purpose="past-card-2"]')).toContainText('Dr. Marcus Vance, MD');

    // Switch to Cancelled -> shows cancelled card
    await page.locator('[data-purpose="appointment-tab-cancelled"]').click();
    await expect(page.locator('[data-purpose="appointment-cancelled-list"]')).toBeVisible();
    await expect(page.locator('[data-purpose="cancelled-card-1"]')).toContainText('Dr. Sarah Jenkins, MD');
    await expect(page.locator('[data-purpose="cancelled-card-1"]')).toContainText('Cancelled');

    // Back to Upcoming
    await page.locator('[data-purpose="appointment-tab-upcoming"]').click();
    await expect(page.locator('[data-purpose="appointment-card-1"]')).toBeVisible();
  });

  test('Booking modal: open -> fill form -> submit -> success', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openAppointment(page);

    // Open booking modal
    await page.getByRole('button', { name: 'Schedule Visit' }).click();
    await expect(page.locator('[data-purpose="appointment-modal"]')).toBeVisible();

    // Submit form
    await page.getByRole('button', { name: 'Confirm Booking' }).click();

    // Success state
    await expect(page.locator('[data-purpose="appointment-modal-success"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Appointment Confirmed!' })).toBeVisible();
  });

  test('Reschedule modal shows provider name', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openAppointment(page);

    // Click Reschedule on first card
    await page.locator('[data-purpose="appointment-card-1"]').getByRole('button', { name: 'Reschedule' }).click();
    await expect(page.locator('[data-purpose="appointment-modal"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Reschedule with Dr. Marcus Vance' })).toBeVisible();
  });

  test('Past consultations section is removed', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openAppointment(page);

    // Past Completed Consultations should NOT exist
    await expect(page.getByText('Past Completed Consultations')).toHaveCount(0);
    await expect(page.getByText('View Log →')).toHaveCount(0);
  });
});
