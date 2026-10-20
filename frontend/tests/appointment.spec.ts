import { test, expect } from './fixtures';
import { createAppointment, futureSlot, openSection } from './helpers';

// Appointments against the real backend. Each test creates its own
// appointments with a unique doctor name, since the test patient is shared.

function unique(label: string) {
  return `Dr. ${label} ${Date.now().toString(36)}`;
}

test.describe('Interview — Appointment page', () => {
  test('shows a booked appointment in Upcoming', async ({ page }) => {
    const doctor = unique('Upcoming');
    const appointment = await createAppointment(page.request, {
      scheduled_at: futureSlot(3).iso, provider_name: doctor, department: 'Cardiology',
    });
    await openSection(page, 'Appointment', 'appointment-view');

    const card = page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`);
    await expect(card).toBeVisible();
    await expect(card).toContainText(doctor);
    await expect(card).toContainText('Cardiology');
    await expect(card.getByRole('button', { name: 'Reschedule' })).toBeVisible();
    await expect(page.locator('[data-purpose="upcoming-count"]')).toContainText(/\d+ Scheduled/);
    await expect(page.locator('[data-purpose="next-appointment"]')).not.toContainText('None scheduled');
  });

  test('schedules a video visit from the modal', async ({ page }) => {
    const doctor = unique('Video');
    await openSection(page, 'Appointment', 'appointment-view');
    await page.getByRole('button', { name: 'Schedule Visit' }).click();
    await expect(page.locator('[data-purpose="appointment-modal"]')).toBeVisible();

    await page.locator('#appointment-provider').fill(doctor);
    await page.locator('[data-purpose="appointment-modal"]').getByText('Video Telehealth', { exact: true }).click();
    await page.locator('#appointment-meeting-url').fill('https://meet.example.com/visit');
    const slot = futureSlot(5, 14, 0);
    await page.locator('#appointment-date').fill(slot.date);
    await page.locator('#appointment-time').fill(slot.time);
    await page.getByRole('button', { name: 'Confirm Booking' }).click();

    await expect(page.locator('[data-purpose="appointment-modal-success"]')).toBeVisible();
    await page.getByRole('button', { name: 'Done' }).click();
    const card = page.locator('[data-purpose^="appointment-card-"]', { hasText: doctor });
    await expect(card).toContainText('Video visit');
    await expect(card.getByRole('link', { name: 'Join video visit' })).toHaveAttribute('href', 'https://meet.example.com/visit');
  });

  test('reschedules an appointment', async ({ page }) => {
    const doctor = unique('Move');
    const appointment = await createAppointment(page.request, { scheduled_at: futureSlot(4).iso, provider_name: doctor });
    await openSection(page, 'Appointment', 'appointment-view');
    const card = page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`);
    await card.getByRole('button', { name: 'Reschedule' }).click();

    const slot = futureSlot(6, 16, 45);
    await page.locator('#appointment-date').fill(slot.date);
    await page.locator('#appointment-time').fill(slot.time);
    await page.getByRole('button', { name: 'Confirm Reschedule' }).click();
    await expect(page.locator('[data-purpose="appointment-modal-success"]')).toContainText('Appointment moved');

    const moved = await page.request.get(`/api/backend/users/me/appointments/${appointment.appointment_id}`);
    expect(new Date((await moved.json()).scheduled_at).toISOString()).toBe(slot.iso);
  });

  test('rescheduling keeps the arrival window and shows its rule', async ({ page }) => {
    const appointment = await createAppointment(page.request, {
      scheduled_at: futureSlot(11, 9, 30).iso,
      provider_name: unique('Window'),
      time_window: 'morning',
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    await openSection(page, 'Appointment', 'appointment-view');
    await page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`).getByRole('button', { name: 'Reschedule' }).click();
    await expect(page.locator('#appointment-window')).toHaveValue('morning');

    const slot = futureSlot(12, 15, 0);
    await page.locator('#appointment-date').fill(slot.date);
    await page.locator('#appointment-time').fill(slot.time);
    await page.getByRole('button', { name: 'Confirm Reschedule' }).click();
    await expect(page.locator('[data-purpose="appointment-error"]')).toContainText('morning appointment must start between');

    await page.locator('#appointment-window').selectOption('afternoon');
    await page.getByRole('button', { name: 'Confirm Reschedule' }).click();
    await expect(page.locator('[data-purpose="appointment-modal-success"]')).toBeVisible();
  });

  test('cancels an appointment after confirmation', async ({ page }) => {
    const doctor = unique('Cancel');
    const appointment = await createAppointment(page.request, { scheduled_at: futureSlot(7).iso, provider_name: doctor });
    await openSection(page, 'Appointment', 'appointment-view');
    const card = page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`);
    await card.getByRole('button', { name: 'Cancel' }).click();
    await expect(card.locator('[data-purpose="cancel-confirm"]')).toBeVisible();
    await card.getByRole('button', { name: 'Yes, cancel' }).click();

    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Appointment Cancelled');
    await expect(card).toHaveCount(0);
    await page.locator('[data-purpose="appointment-tab-cancelled"]').click();
    const cancelled = page.locator(`[data-purpose="appointment-card-${appointment.appointment_id}"]`);
    await expect(cancelled).toContainText('Cancelled');
  });

  test('filters by visit type', async ({ page }) => {
    const doctor = unique('InPerson');
    await createAppointment(page.request, { scheduled_at: futureSlot(8).iso, provider_name: doctor, visit_mode: 'in_person' });
    await openSection(page, 'Appointment', 'appointment-view');
    await expect(page.locator('[data-purpose^="appointment-card-"]', { hasText: doctor })).toBeVisible();
    await page.locator('[data-purpose="appointment-type-filter"]').selectOption('telehealth');
    await expect(page.locator('[data-purpose^="appointment-card-"]', { hasText: doctor })).toHaveCount(0);
  });
});
