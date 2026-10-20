import { test, expect, type Page } from './fixtures';
import { createAppointment, futureSlot, openSection } from './helpers';

// The in-app inbox against the real backend: booking and cancelling
// appointments create inbox items, and a unique location tells them apart.

function uniquePlace(label: string) {
  return `${label} Clinic ${Date.now().toString(36)}`;
}

function notification(page: Page, text: string) {
  return page.locator('[data-purpose^="notif-"][data-kind]', { hasText: text });
}

test.describe('Interview — Notifications', () => {
  test('a booked appointment notifies and links to its card', async ({ page }) => {
    const place = uniquePlace('Booked');
    const appointment = await createAppointment(page.request, { scheduled_at: futureSlot(21).iso, location: place });
    await openSection(page, 'Notification', 'notification-view');

    const item = notification(page, place);
    await expect(item).toContainText('Appointment booked');
    await expect(item.locator('[data-purpose="unread-dot"]')).toBeVisible();
    await item.click();

    await expect(page.locator('[data-purpose="appointment-view"]')).toBeVisible();
    const card = page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`);
    await expect(card).toBeVisible();
    await expect(card).toHaveClass(/ring-2/);

    // Opening it marked it read.
    await page.locator('aside').getByRole('link', { name: 'Notification' }).click();
    await expect(notification(page, place).locator('[data-purpose="unread-dot"]')).toHaveCount(0);
  });

  test('a cancellation opens the Cancelled tab', async ({ page }) => {
    const place = uniquePlace('Cancelled');
    const appointment = await createAppointment(page.request, { scheduled_at: futureSlot(22).iso, location: place });
    const cancel = await page.request.patch(`/api/backend/users/me/appointments/${appointment.appointment_id}/status`, {
      data: { status: 'CANCELLED' },
    });
    expect(cancel.ok()).toBeTruthy();
    await openSection(page, 'Notification', 'notification-view');

    await notification(page, place).filter({ hasText: 'Appointment cancelled' }).click();
    await expect(page.locator('[data-purpose="appointment-tab-cancelled"]')).toHaveClass(/bg-white/);
    const card = page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`);
    await expect(card).toContainText('Cancelled');
    await expect(card).toHaveClass(/ring-2/);
  });

  test('dismiss removes an item, and it stays gone', async ({ page }) => {
    const place = uniquePlace('Dismissed');
    await createAppointment(page.request, { scheduled_at: futureSlot(23).iso, location: place });
    await openSection(page, 'Notification', 'notification-view');

    const item = notification(page, place);
    await item.getByRole('button', { name: 'Dismiss' }).click();
    await expect(item).toHaveCount(0);
    await page.reload();
    await page.locator('aside').getByRole('link', { name: 'Notification' }).click();
    await expect(page.locator('[data-purpose="notification-view"]')).toBeVisible();
    await expect(notification(page, place)).toHaveCount(0);
  });

  test('mark all as read clears the unread count', async ({ page }) => {
    await createAppointment(page.request, { scheduled_at: futureSlot(24).iso, location: uniquePlace('Unread') });
    await openSection(page, 'Notification', 'notification-view');
    await expect(page.locator('[data-purpose="unread-count"]')).not.toHaveText('0 unread');
    await page.getByRole('button', { name: 'Mark all as read' }).click();
    await expect(page.locator('[data-purpose="unread-count"]')).toHaveText('0 unread');
    await expect(page.locator('[data-purpose="unread-dot"]')).toHaveCount(0);
  });

  test('category filters show only that category', async ({ page }) => {
    await createAppointment(page.request, { scheduled_at: futureSlot(25).iso, location: uniquePlace('Filter') });
    await openSection(page, 'Notification', 'notification-view');
    await page.locator('[data-purpose="notif-filter-security"]').click();
    await expect(page.locator('[data-purpose="notif-group-appointments"]')).toHaveCount(0);
    await page.locator('[data-purpose="notif-filter-appointments"]').click();
    await expect(page.locator('[data-purpose="notif-group-appointments"]')).toBeVisible();
  });
});
