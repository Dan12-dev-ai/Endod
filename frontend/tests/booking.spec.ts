import { test, expect } from './fixtures';
import { futureSlot, openSection } from './helpers';

// The hospital directory and booking, against the real backend directory.

test.describe('Interview — Booking page', () => {
  test('lists the care directory and filters it', async ({ page }) => {
    await openSection(page, 'Booking', 'booking-view');
    await expect(page.getByRole('heading', { name: 'Hospital & Clinic Reservation' })).toBeVisible();

    await expect(page.locator('.hospital-card').first()).toBeVisible();
    const all = await page.locator('.hospital-card').count();
    expect(all).toBeGreaterThan(1);

    // Search narrows the list (server-side).
    await page.locator('[data-purpose="hospital-search"]').fill('Anbessa');
    await expect(page.locator('.hospital-card')).toHaveCount(1);
    await expect(page.locator('[data-purpose="hospital-et-addis-black-lion"]')).toContainText('Tikur Anbessa');

    await page.locator('[data-purpose="hospital-search"]').fill('zzzz-no-such-place');
    await expect(page.locator('[data-purpose="hospital-empty"]')).toBeVisible();

    // Department filter.
    await page.locator('[data-purpose="hospital-search"]').fill('');
    await page.locator('[data-purpose="department-filter"]').selectOption('maternal_health');
    await expect(page.locator('.hospital-card').first()).toBeVisible();
    expect(await page.locator('.hospital-card').count()).toBeLessThanOrEqual(all);
  });

  test('books a visit and it appears in Appointments', async ({ page }) => {
    await openSection(page, 'Booking', 'booking-view');
    await page.locator('[data-purpose="hospital-search"]').fill('Peter');
    const card = page.locator('[data-purpose="hospital-et-addis-stpeter"]');
    await card.getByRole('button', { name: 'Book Now' }).click();

    const modal = page.locator('[data-purpose="booking-modal"]');
    await expect(modal).toBeVisible();
    await expect(modal).toContainText(/Patient: DE\d{6}/);
    const slot = futureSlot(9, 9, 15);
    await page.locator('#booking-date').fill(slot.date);
    await page.locator('#booking-time').fill(slot.time);
    await page.locator('[data-purpose="time-window"]').selectOption('morning');
    await page.locator('#booking-note').fill('Booking flow test');
    await page.getByRole('button', { name: 'Submit Booking' }).click();

    const success = page.locator('[data-purpose="success-modal"]');
    await expect(success).toBeVisible();
    await expect(success).toContainText("St. Peter's Hospital");
    await expect(success).toContainText('does not receive bookings from Endod yet');
    await page.getByRole('button', { name: 'Done' }).click();
    await expect(success).toHaveCount(0);

    await page.locator('aside').getByRole('link', { name: 'Appointment' }).click();
    await expect(page.locator('[data-purpose="appointment-upcoming-list"]')).toContainText("St. Peter's Hospital");
  });

  test('shows the backend error for a time outside the arrival window', async ({ page }) => {
    await openSection(page, 'Booking', 'booking-view');
    await page.locator('[data-purpose="hospital-search"]').fill('Anbessa');
    await page.locator('[data-purpose="hospital-et-addis-black-lion"]').getByRole('button', { name: 'Book Now' }).click();
    const slot = futureSlot(10, 15, 0);
    await page.locator('#booking-date').fill(slot.date);
    await page.locator('#booking-time').fill(slot.time);
    await page.locator('[data-purpose="time-window"]').selectOption('morning');
    await page.getByRole('button', { name: 'Submit Booking' }).click();
    await expect(page.locator('[data-purpose="booking-error"]')).toContainText('morning appointment must start between');
    await expect(page.locator('[data-purpose="success-modal"]')).toHaveCount(0);
  });

  test('cancelling a booking, then leaving and returning, shows a fresh view', async ({ page }) => {
    await openSection(page, 'Booking', 'booking-view');
    await page.locator('.hospital-card').first().getByRole('button', { name: 'Book Now' }).click();
    const modal = page.locator('[data-purpose="booking-modal"]');
    await expect(modal).toBeVisible();
    await modal.getByRole('button', { name: 'Cancel' }).click();
    await expect(modal).toHaveCount(0);

    await page.locator('[data-purpose="hospital-search"]').fill('Peter');
    await page.locator('aside').getByRole('link', { name: 'Home' }).click();
    await expect(page.locator('[data-purpose="booking-view"]')).toHaveCount(0);
    await page.locator('aside').getByRole('link', { name: 'Booking' }).click();
    await expect(page.locator('[data-purpose="booking-view"]')).toBeVisible();
    await expect(modal).toHaveCount(0);
    await expect(page.locator('[data-purpose="hospital-search"]')).toHaveValue('');
  });
});
