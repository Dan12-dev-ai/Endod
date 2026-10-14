import { test, expect, type Page } from '@playwright/test';

async function openNotification(page: Page) {
  await page.locator('aside').getByRole('link', { name: 'Notification' }).click();
  await expect(page.locator('[data-purpose="notification-view"]')).toBeVisible();
}

test.describe('Interview — Notification page (3 categories)', () => {
  test.beforeEach(async ({ page }) => {
    page.on('dialog', (dialog) => dialog.dismiss());
  });

  test('Renders the three notification categories', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    // Page header
    await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible();
    await expect(page.getByText('4 unread')).toBeVisible();

    // Three category sections
    await expect(page.locator('[data-purpose="notif-group-appointments"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-group-records"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-group-messages"]')).toBeVisible();

    // Category titles
    await expect(page.getByText('Appointment updates', { exact: true })).toBeVisible();
    await expect(page.getByText('Medical record updates', { exact: true })).toBeVisible();
    await expect(page.getByText('Messages and general updates', { exact: true })).toBeVisible();

    // Appointment update types (5)
    await expect(page.locator('[data-purpose="notif-n1"]')).toContainText('Appointment confirmed');
    await expect(page.locator('[data-purpose="notif-n2"]')).toContainText('Appointment rescheduled');
    await expect(page.locator('[data-purpose="notif-n3"]')).toContainText('Appointment canceled');
    await expect(page.locator('[data-purpose="notif-n4"]')).toContainText('Upcoming appointment reminder');
    await expect(page.locator('[data-purpose="notif-n5"]')).toContainText('Doctor or clinic updates');

    // Medical record update types (3)
    await expect(page.locator('[data-purpose="notif-n6"]')).toContainText('Lab results available');
    await expect(page.locator('[data-purpose="notif-n7"]')).toContainText('New medical report uploaded');
    await expect(page.locator('[data-purpose="notif-n8"]')).toContainText("Prescription or doctor's notes updated");

    // Message / general update types (3)
    await expect(page.locator('[data-purpose="notif-n9"]')).toContainText('New message from a doctor');
    await expect(page.locator('[data-purpose="notif-n10"]')).toContainText('Account or security alert');
    await expect(page.locator('[data-purpose="notif-n11"]')).toContainText('Important announcement from the clinic');
  });

  test('Filter pills show/hide notifications by category', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    // All: all 11 notifications
    await expect(page.locator('[data-purpose="notif-n1"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-n11"]')).toBeVisible();

    // Appointments filter -> only appointment group
    await page.locator('[data-purpose="notif-filter-appointments"]').click();
    await expect(page.locator('[data-purpose="notif-n1"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-n11"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="notif-group-appointments"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-group-records"]')).toHaveCount(0);

    // Records filter -> only records group
    await page.locator('[data-purpose="notif-filter-records"]').click();
    await expect(page.locator('[data-purpose="notif-n6"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-n1"]')).toHaveCount(0);

    // Messages filter -> only messages group
    await page.locator('[data-purpose="notif-filter-messages"]').click();
    await expect(page.locator('[data-purpose="notif-n9"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-n6"]')).toHaveCount(0);

    // Back to all
    await page.locator('[data-purpose="notif-filter-all"]').click();
    await expect(page.locator('[data-purpose="notif-n1"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-n9"]')).toBeVisible();
  });

  test('Clicking an appointment notification opens the Appointments page with the target card', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    // Click the "Appointment confirmed" notification -> Appointments page
    await page.locator('[data-purpose="notif-n1"]').click();
    await expect(page.locator('[data-purpose="appointment-view"]')).toBeVisible();

    // The relevant appointment card is visible and highlighted
    const card = page.locator('[data-purpose="appointment-card-1"]');
    await expect(card).toBeVisible();
    await expect(card).toContainText('Dr. Marcus Vance');
    await expect(card).toHaveClass(/ring-2/);
  });

  test('Clicking a canceled-appointment notification opens the Cancelled tab', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    await page.locator('[data-purpose="notif-n3"]').click();
    await expect(page.locator('[data-purpose="appointment-view"]')).toBeVisible();

    // Cancelled tab card visible + highlighted
    const card = page.locator('[data-purpose="cancelled-card-1"]');
    await expect(card).toBeVisible();
    await expect(card).toContainText('Cancelled');
    await expect(card).toHaveClass(/ring-2/);
  });

  test('Clicking a medical record notification opens the Medical Records page with the record highlighted', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    // Lab results available -> record-2 (City Care blood panel)
    await page.locator('[data-purpose="notif-n6"]').click();
    await expect(page.locator('[data-purpose="medical-record-view"]')).toBeVisible();

    const row = page.locator('[data-purpose="record-2"]');
    await expect(row).toBeVisible();
    await expect(row).toContainText('City Care Diagnostics Center');
    await expect(row).toHaveClass(/ring-2/);
  });

  test('Messages/general notifications are not clickable links', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    // Clicking a general message stays on the Notification page
    await page.locator('[data-purpose="notif-n10"]').click();
    await expect(page.locator('[data-purpose="notification-view"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-n10"]')).toBeVisible();
  });

  test('Dismiss removes notification', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    // Dismiss n1
    await page.locator('[data-purpose="notif-n1"]').getByRole('button', { name: 'Dismiss' }).click();
    await expect(page.locator('[data-purpose="notif-n1"]')).toHaveCount(0);
    // Others still visible
    await expect(page.locator('[data-purpose="notif-n2"]')).toBeVisible();
    await expect(page.locator('[data-purpose="notif-n9"]')).toBeVisible();
  });

  test('Mark all as read changes badge', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openNotification(page);

    await expect(page.getByText('4 unread')).toBeVisible();
    await page.getByRole('button', { name: 'Mark all as read' }).click();
    await expect(page.getByText('0 unread')).toBeVisible();
  });

  test('Sidebar shows "Notification" not "Message"', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);

    await expect(page.locator('aside').getByRole('link', { name: 'Notification' })).toBeVisible();
    await expect(page.locator('aside').getByRole('link', { name: 'Message' })).toHaveCount(0);
  });
});
