import { test, expect, type Page } from '@playwright/test';

async function openBooking(page: Page) {
  await page.locator('aside').getByRole('link', { name: 'Booking' }).click();
  await expect(page.locator('[data-purpose="booking-view"]')).toBeVisible();
}

test.describe('Interview — Booking page (manual only)', () => {
  test.beforeEach(async ({ page }) => {
    page.on('dialog', (dialog) => dialog.dismiss());
  });

  test('Manual Booking: hero -> hospital grid -> booking modal -> success confirmation', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openBooking(page);

    // Hero section renders
    await expect(page.getByRole('heading', { name: 'Hospital & Clinic Reservation' })).toBeVisible();

    // Action buttons should NOT exist
    await expect(page.locator('[data-purpose="booking-option-manual"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="booking-option-ai"]')).toHaveCount(0);

    // Hospital cards render directly
    await expect(page.locator('[data-purpose="manual-booking-section"]')).toBeVisible();
    const cards = page.locator('[data-purpose^="hospital-h"]');
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBe(4);

    // Click "Book Now" on the first hospital card -> opens booking modal
    await cards.first().locator('button', { hasText: 'Book Now' }).click();
    await expect(page.locator('[data-purpose="booking-modal"]')).toBeVisible();

    // Fill the form and submit
    await page.locator('#booking-date').fill('2026-01-15');
    await page.locator('#booking-time').fill('14:00');
    await page.locator('#booking-note').fill('Chest pain follow-up');
    await page.getByRole('button', { name: 'Submit Booking' }).click();

    // Success modal appears
    await expect(page.locator('[data-purpose="success-modal"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Hospital Appointment Confirmed!' })).toBeVisible();
    await expect(page.locator('[data-purpose="success-modal"]')).toContainText('St. Jude Metropolitan Hospital');

    // Dismiss success modal
    await page.getByRole('button', { name: 'Done & Return to Overview' }).click();
    await expect(page.locator('[data-purpose="success-modal"]')).toHaveCount(0);
  });

  test('Hospital cards show only name, distance, wait, and Book Now', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openBooking(page);

    const firstCard = page.locator('[data-purpose="hospital-h1"]');
    await expect(firstCard).toBeVisible();

    // Should contain hospital name, distance, and wait time
    await expect(firstCard).toContainText('St. Jude Metropolitan Hospital');
    await expect(firstCard).toContainText('1.8 miles');
    await expect(firstCard).toContainText('~15 mins');

    // Should have Book Now button
    await expect(firstCard.locator('button', { hasText: 'Book Now' })).toBeVisible();

    // Should NOT contain rating, tags, status, or website link
    await expect(firstCard).not.toContainText('★');
    await expect(firstCard).not.toContainText('Cardiology');
    await expect(firstCard).not.toContainText('Open 24/7');
    await expect(firstCard.locator('a')).toHaveCount(0);
  });

  test('Search filters hospital cards', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openBooking(page);

    const cards = page.locator('[data-purpose^="hospital-h"]');
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBe(4);

    // Search for "Apex" -> only 1 card should match
    await page.locator('[data-purpose="hospital-search"]').fill('Apex');
    await page.waitForTimeout(200);
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText('Apex Heart & Health Institute');

    // Search for "City" -> only 1 card
    await page.locator('[data-purpose="hospital-search"]').fill('City');
    await page.waitForTimeout(200);
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText('City Care Specialty Clinics');

    // Clear search -> all 4 cards back
    await page.locator('[data-purpose="hospital-search"]').fill('');
    await page.waitForTimeout(200);
    await expect(cards).toHaveCount(4);
  });

  test('Reset on exit: leaving Booking clears state; re-entering shows fresh view', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    await openBooking(page);

    // Open a booking modal (creates booking state)
    await page.locator('[data-purpose="hospital-h1"]').locator('button', { hasText: 'Book Now' }).click();
    await expect(page.locator('[data-purpose="booking-modal"]')).toBeVisible();

    // Close the modal via Cancel
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.locator('[data-purpose="booking-modal"]')).toHaveCount(0);
    await page.waitForTimeout(150);

    // Leave Booking -> booking view unmounts
    await page.locator('aside').getByRole('link', { name: 'Live Discussion' }).click();
    await expect(page.locator('[data-purpose="booking-view"]')).toHaveCount(0);
    await page.waitForTimeout(300);

    // Re-enter Booking -> fresh view (no modal)
    await page.locator('aside').getByRole('link', { name: 'Booking' }).click();
    await expect(page.locator('[data-purpose="booking-view"]')).toBeVisible();
    await expect(page.locator('[data-purpose="booking-modal"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="success-modal"]')).toHaveCount(0);
  });
});
