import { test, expect } from '@playwright/test';
import { createAppointment, futureSlot } from './helpers';

test.describe('Interview — Home', () => {
  test('opens on Home with the next appointment and shortcuts', async ({ page }) => {
    const appointment = await createAppointment(page.request, {
      scheduled_at: futureSlot(1, 8, 0).iso, provider_name: `Dr. Home ${Date.now().toString(36)}`,
    });
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await expect(page.locator('[data-purpose="home-view"]')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Welcome, Test' })).toBeVisible();
    await expect(page.locator('[data-purpose="home-next-appointment"]')).not.toContainText('None scheduled');

    await page.locator('[data-purpose="home-next-appointment"]').click();
    await expect(page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`)).toBeVisible();
  });

  test('has no live voice screen', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await expect(page.locator('aside').getByRole('link', { name: 'Live Discussion' })).toHaveCount(0);
    await expect(page.locator('[data-purpose="video-consultation-stage"]')).toHaveCount(0);
  });
});
