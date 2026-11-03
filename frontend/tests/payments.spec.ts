import { test, expect, BLANK_PNG, type Locator, type Page } from './fixtures';
import { chooseOption, createAppointment, futureSlot, openSection, PARTNER_ID, payBooking, seed, VIDEO_VISITS } from './helpers';
import { safeCheckoutUrl } from '../app/interview/data';

// Paying for each partner-hospital booking through Chapa (tests/fake-chapa.mjs,
// which behaves like Chapa's checkout and refund API), with partner hospitals
// listed by tests/seed.py, video visits (Jitsi's script stubbed; only with
// E2E_VIDEO_VISITS=true, otherwise that they are hidden and refused) and the
// emergency panel (map tiles stubbed). The tests build on each other, so they
// run in order.

test.describe.configure({ mode: 'serial' });
// Patients and partner hospitals are in Ethiopia: times are entered in Addis Ababa time
// (CI machines run in UTC, where 09:30 would be 12:30 at the hospital).
test.use({ timezoneId: 'Africa/Addis_Ababa' });

const PARTNER = `[data-purpose="hospital-${PARTNER_ID}"]`;

async function openPartnerBooking(page: Page) {
  await openSection(page, 'Booking', 'booking-view');
  await page.locator('[data-purpose="hospital-search"]').fill('Endod Test General');
  const card = page.locator(PARTNER);
  await expect(card.locator('[data-purpose="partner-details"]')).toContainText('From ETB 200.00');
  await expect(card.locator('[data-purpose="partner-details"]')).toContainText('Private');
  if (VIDEO_VISITS) await expect(card.locator('[data-purpose="partner-details"]')).toContainText('Video visits');
  else await expect(card.locator('[data-purpose="partner-details"]')).not.toContainText('Video');
  await card.getByRole('button', { name: 'Book Now' }).click();
  await expect(page.locator('[data-purpose="booking-modal"]')).toBeVisible();
}

async function fillVisit(page: Page, days: number, note: string) {
  const slot = futureSlot(days, 9, 30);
  await page.locator('#booking-date').fill(slot.date);
  await page.locator('#booking-time').fill(slot.time);
  await chooseOption(page, 'time-window', 'Morning (08:00 - 12:00)');
  await page.locator('#booking-note').fill(note);
}

/** A partner booking's card in Appointments, on the tab given (by id, or the first). */
async function partnerCard(page: Page, tab: 'upcoming' | 'cancelled', id?: string): Promise<Locator> {
  await openSection(page, 'Appointment', 'appointment-view');
  if (tab === 'cancelled') await page.locator('[data-purpose="appointment-tab-cancelled"]').click();
  return id
    ? page.locator(`[data-purpose="appointment-card-${id}"]`)
    : page.locator(`[data-purpose="appointment-${tab}-list"] > *`, { hasText: 'Endod Test General' }).first();
}

async function cardId(card: Locator) {
  return ((await card.getAttribute('data-purpose')) ?? '').replace('appointment-card-', '');
}

test.describe('Paying for each booking through Chapa', () => {
  test('a partner booking shows the price breakdown and "Pay and book"; there is no balance', async ({ page }) => {
    await openPartnerBooking(page);
    const quote = page.locator('[data-purpose="booking-quote"]');
    await expect(quote).toContainText('200.00');
    await expect(quote).toContainText('5.00');
    await expect(quote.locator('[data-purpose="quote-total"]')).toHaveText('ETB 205.00');
    await expect(quote).not.toContainText('balance');
    await expect(page.locator('[data-purpose="pay-hint"]')).toContainText('telebirr, CBE Birr, M-Pesa, a bank or a card');
    await expect(page.getByRole('button', { name: 'Pay and book' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add money' })).toHaveCount(0);

    if (VIDEO_VISITS) {
      // The visit type changes the price: a video visit here is 120 birr.
      await page.locator('[data-purpose="visit-mode"]').getByText('Video').click();
      await expect(quote.locator('[data-purpose="quote-total"]')).toHaveText('ETB 125.00');
      await expect(page.locator('[data-purpose="visit-mode"]')).toContainText('A doctor at the hospital approves');
    } else {
      // Video visits are off: in person only, no choice offered.
      await expect(page.locator('[data-purpose="visit-mode"]')).toHaveCount(0);
      await expect(page.locator('[data-purpose="booking-modal"]')).not.toContainText('Video');
    }

    // No balance section any more.
    await expect(page.locator('aside').getByRole('link', { name: 'Balance' })).toHaveCount(0);
    await page.goto('/interview?section=wallet', { waitUntil: 'networkidle' });
    await expect(page.locator('[data-purpose="wallet-view"]')).toHaveCount(0);
  });

  test('booking goes out to Chapa and comes back paid, with the hospital waiting', async ({ page }) => {
    await openPartnerBooking(page);
    await fillVisit(page, 6, 'Paid booking test');
    await page.getByRole('button', { name: 'Pay and book' }).click();
    // Out to the (fake) Chapa checkout, which takes the payment and sends the patient back.
    await page.waitForURL(/\/interview\?section=appointment/);
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Payment received');
    await expect(page).not.toHaveURL(/payment=/);

    const row = page.locator('[data-purpose="appointment-upcoming-list"] > *', { hasText: 'Endod Test General' }).first();
    await expect(row.locator('[data-purpose="hospital-state"]')).toHaveText('Waiting for the hospital');
    await expect(row.locator('[data-purpose="payment-status"]')).toHaveText('Paid ETB 205.00');
    await expect(row.locator('[data-purpose="pay-now"]')).toHaveCount(0);
  });

  test('cancelling a paid visit refunds it to the payment method', async ({ page }) => {
    const row = await partnerCard(page, 'upcoming');
    const id = await cardId(row);
    await row.getByRole('button', { name: 'Cancel' }).click();
    await expect(row.locator('[data-purpose="cancel-confirm"]')).toContainText(
      'ETB 205.00 will be refunded to your payment method (it can take a few days).',
    );
    await row.getByRole('button', { name: 'Yes, cancel' }).click();
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Appointment Cancelled');

    let cancelled = await partnerCard(page, 'cancelled', id);
    await expect(cancelled.locator('[data-purpose="payment-status"]')).toHaveText(
      'Refund pending: ETB 205.00 to your payment method',
    );
    // The events worker sends it to Chapa, which returns it to the payer.
    seed('refunds');
    cancelled = await partnerCard(page, 'cancelled', id);
    await expect(cancelled.locator('[data-purpose="payment-status"]')).toHaveText('ETB 205.00 refunded to your payment method');
  });

  test('a booking the hospital declines is refunded and shown so', async ({ page }) => {
    const booking = await createAppointment(page.request, {
      scheduled_at: futureSlot(11, 9, 30).iso, timezone: 'Africa/Addis_Ababa', facility_id: PARTNER_ID,
      visit_mode: 'in_person', department: 'general_medicine',
    });
    await payBooking(page.request, booking.payment!);
    let card = await partnerCard(page, 'upcoming', booking.appointment_id);
    await expect(card.locator('[data-purpose="payment-status"]')).toHaveText('Paid ETB 205.00');

    seed('reject', booking.appointment_id);
    card = await partnerCard(page, 'cancelled', booking.appointment_id);
    await expect(card.locator('[data-purpose="hospital-state"]')).toHaveText('Declined by the hospital');
    await expect(card).toContainText('No doctor available');
    await expect(card.locator('[data-purpose="payment-status"]')).toHaveText('ETB 205.00 refunded to your payment method');

    await openSection(page, 'Notification', 'notification-view');
    await expect(page.getByText('205.00 birr is being refunded to your payment method (it can take a few days).').first())
      .toBeVisible();
  });

  test('an abandoned payment holds the time with "Pay now", then expires', async ({ page }) => {
    // The patient leaves Chapa's page without paying.
    await page.route('http://127.0.0.1:8012/checkout/**', (route) =>
      route.fulfill({ contentType: 'text/html', body: '<p data-purpose="fake-checkout">Chapa</p>' }),
    );
    await openPartnerBooking(page);
    await fillVisit(page, 13, 'Abandoned payment test');
    await page.getByRole('button', { name: 'Pay and book' }).click();
    await expect(page.locator('[data-purpose="fake-checkout"]')).toBeVisible();

    const card = await partnerCard(page, 'upcoming');
    await expect(card.locator('[data-purpose="hospital-state"]')).toHaveText('Awaiting payment');
    const id = await cardId(card);
    await expect(card.locator('[data-purpose="payment-status"]')).toContainText('ETB 205.00 to pay by');
    await expect(card.locator('[data-purpose="pay-now"]')).toHaveAttribute('href', /^http:\/\/127\.0\.0\.1:8012\/checkout\//);

    // Thirty minutes on, unpaid: the time is released.
    seed('expire', id);
    const expired = await partnerCard(page, 'cancelled', id);
    await expect(expired.locator('[data-purpose="hospital-state"]')).toHaveText('Payment not completed');
    await expect(expired.locator('[data-purpose="payment-status"]')).toHaveText('Not paid in time; nothing was charged');
    await expect(expired.locator('[data-purpose="pay-now"]')).toHaveCount(0);
  });

  test('a video visit waits for the doctor, then opens in Endod with a signed token', async ({ page }) => {
    test.skip(!VIDEO_VISITS, 'video visits are off (E2E_VIDEO_VISITS=true turns them on)');
    const at = new Date(Date.now() + 20 * 60_000);
    const appointment = await createAppointment(page.request, {
      scheduled_at: at.toISOString(), timezone: 'Africa/Addis_Ababa', facility_id: PARTNER_ID,
      visit_mode: 'telehealth', department: 'general_medicine',
    });
    await payBooking(page.request, appointment.payment!);
    await openSection(page, 'Appointment', 'appointment-view');
    const row = page.locator('[data-purpose="appointment-upcoming-list"] > *', { hasText: 'Endod Test General' }).first();
    await expect(row.locator('[data-purpose="hospital-state"]')).toHaveText('Waiting for a doctor');
    await expect(row.locator('[data-purpose="join-video"]')).toHaveCount(0);

    // The doctor approves in the hospital portal (the event the worker would apply).
    seed('confirm', appointment.appointment_id, 'endod-e2e-room');

    await page.route('https://meet.endod-health.com/external_api.js', (route) =>
      route.fulfill({
        contentType: 'application/javascript',
        body: `window.JitsiMeetExternalAPI = function (domain, options) {
          window.__jitsi = { domain, options };
          const listeners = {};
          const frame = document.createElement('div');
          frame.setAttribute('data-purpose', 'fake-jitsi');
          options.parentNode.appendChild(frame);
          this.addListener = (name, fn) => { listeners[name] = fn; };
          this.dispose = () => frame.remove();
          window.__jitsiEvent = (name) => listeners[name] && listeners[name]();
          setTimeout(() => window.__jitsiEvent('videoConferenceJoined'), 50);
        };`,
      }),
    );
    await openSection(page, 'Appointment', 'appointment-view');
    await expect(row.locator('[data-purpose="hospital-state"]')).toHaveText('Confirmed by the hospital');
    await row.locator('[data-purpose="join-video"]').click();
    await page.waitForURL(`**/visit/${appointment.appointment_id}`);
    await expect(page.locator('[data-purpose="fake-jitsi"]')).toBeAttached();

    const jitsi = await page.evaluate(() => (window as unknown as { __jitsi: { domain: string; options: { roomName: string; jwt: string } } }).__jitsi);
    expect(jitsi.domain).toBe('meet.endod-health.com');
    expect(jitsi.options.roomName).toBe('endod-e2e-room');
    const claims = JSON.parse(Buffer.from(jitsi.options.jwt.split('.')[1], 'base64url').toString());
    expect(claims.room).toBe('endod-e2e-room');
    expect(claims.context.user.moderator).toBe(false);
    expect(claims.context.user.name).toBe('Test Patient');

    await page.evaluate(() => (window as unknown as { __jitsiEvent: (n: string) => void }).__jitsiEvent('readyToClose'));
    await expect(page.locator('[data-purpose="visit-ended"]')).toContainText('The call has ended.');
  });

  test('someone else cannot open the video page for a visit that is not theirs', async ({ page }) => {
    test.skip(!VIDEO_VISITS, 'video visits are off (E2E_VIDEO_VISITS=true turns them on)');
    await page.goto('/visit/not-a-real-appointment');
    await expect(page.locator('[data-purpose="visit-error"]')).toBeVisible();
  });
});

test.describe('Video visits switched off (as in production)', () => {
  test.skip(VIDEO_VISITS, 'video visits are on (E2E_VIDEO_VISITS=true)');

  test('the backend tells the app video is off, and refuses video bookings and joins', async ({ page }) => {
    const status = await (await page.request.get('/api/backend/users/me/payments/status')).json();
    expect(status.video_visits).toBe(false);
    const booking = await page.request.post('/api/backend/users/me/appointments', { data: {
      scheduled_at: futureSlot(15, 9, 30).iso, timezone: 'Africa/Addis_Ababa', facility_id: PARTNER_ID,
      visit_mode: 'telehealth', department: 'general_medicine',
    } });
    expect(booking.status()).toBe(400);
    expect((await booking.json()).error).toContain('Video visits are not available right now');
    const quote = await page.request.get('/api/backend/users/me/hospital-bookings/quote',
      { params: { hospital_id: PARTNER_ID, visit_mode: 'telehealth' } });
    expect(quote.status()).toBe(400);
    const join = await page.request.post('/api/backend/users/me/appointments/not-a-real-appointment/video');
    expect(join.status()).toBe(404);
  });

  test('Appointments shows no video counter, filter, legend or join button', async ({ page }) => {
    // A video visit booked while they were on, approved and about to start.
    const id = 'a7a7a7a7-0000-4000-8000-00000000000a';
    // And a personal appointment with a meeting link the patient saved themselves.
    const ownId = 'a7a7a7a7-0000-4000-8000-00000000000c';
    await page.route('**/api/backend/users/me/appointments?**', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const real = await (await route.fetch()).json();
      return route.fulfill({ json: [{
        appointment_id: ownId, user_id: 'u', scheduled_at: new Date(Date.now() + 3 * 86_400_000).toISOString(),
        appointment_type: 'consultation', status: 'SCHEDULED', duration_minutes: 30, location: null,
        meeting_url: 'https://meet.example.com/own-link', visit_mode: 'telehealth', department: null,
        time_window: 'exact', facility: null, provider_name: 'Dr. Own Link', notes: null, timezone: 'Africa/Addis_Ababa',
        created_at: new Date().toISOString(), updated_at: new Date().toISOString(), hospital_booking: null,
      }, {
        appointment_id: id, user_id: 'u', scheduled_at: new Date(Date.now() + 20 * 60_000).toISOString(),
        appointment_type: 'consultation', status: 'CONFIRMED', duration_minutes: 30, location: null,
        meeting_url: 'https://meet.endod-health.com/endod-old', visit_mode: 'telehealth', department: 'general_medicine',
        time_window: 'exact', facility: { id: PARTNER_ID, name: 'Endod Test General Hospital' }, provider_name: null,
        notes: null, timezone: 'Africa/Addis_Ababa', created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        hospital_booking: {
          hospital_id: PARTNER_ID, state: 'confirmed', price: 12000, service_fee: 700, total: 12700, reason: null,
          video_ready: true, payment: { status: 'paid', due_at: null, checkout_url: null },
        },
      }, ...real] });
    });
    await openSection(page, 'Appointment', 'appointment-view');
    const card = page.locator(`[data-purpose="appointment-card-${id}"]`);
    // Still readable...
    await expect(card).toContainText('Endod Test General Hospital');
    // ...but nothing to join, count or filter by.
    await expect(card.locator('[data-purpose="join-video"]')).toHaveCount(0);
    await expect(card.getByText('Join video visit')).toHaveCount(0);
    await expect(page.locator('[data-purpose="next-appointment"]')).toBeVisible();
    await expect(page.locator('[data-purpose="next-video-visit"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="appointment-type-filter"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="legend-telehealth"]')).toHaveCount(0);
    // The patient's own saved link is theirs, not Endod video: it stays.
    await expect(page.locator(`[data-purpose="appointment-card-${ownId}"]`).getByRole('link'))
      .toHaveAttribute('href', 'https://meet.example.com/own-link');
  });

  test('if the status cannot be read, the video page still asks the backend, which refuses', async ({ page }) => {
    await page.route('**/api/backend/users/me/payments/status', (route) => route.fulfill({ status: 503, json: {} }));
    await page.goto('/visit/a7a7a7a7-0000-4000-8000-00000000000d');
    await expect(page.locator('[data-purpose="visit-error"]')).toContainText('Video visits are not available right now');
  });

  test('the video page says video visits are not available and leads to Appointments', async ({ page }) => {
    let joined = false;
    await page.route('**/api/backend/users/me/appointments/*/video', (route) => {
      joined = true;
      return route.fallback();
    });
    await page.goto('/visit/a7a7a7a7-0000-4000-8000-00000000000b');
    const unavailable = page.locator('[data-purpose="visit-unavailable"]');
    await expect(unavailable).toContainText('Video visits are not available right now.');
    await expect(page.locator('[data-purpose="visit-frame"]')).toHaveCount(0);
    expect(joined).toBe(false);
    await unavailable.getByRole('link', { name: 'Go to Appointments' }).click();
    await expect(page.locator('[data-purpose="appointment-view"]')).toBeVisible();
  });
});

test.describe('Online payment not set up yet: pay at the hospital', () => {
  // As in production before Chapa keys are set: the backend books a priced
  // partner visit at once, to be paid at the hospital with no Endod fee
  // (payment "at_hospital"; the backend side is covered by its own tests).
  // The test backend has a Chapa key, so its answers are the ones it gives
  // without one.
  async function paymentsOff(page: Page) {
    await page.route('**/api/backend/users/me/payments/status', (route) =>
      route.fulfill({ json: {
        online_payments: false, checkout_origins: ['https://checkout.chapa.co'], video_visits: VIDEO_VISITS,
      } }),
    );
    await page.route('**/api/backend/users/me/hospital-bookings/quote?**', (route) => {
      const mode = new URL(route.request().url()).searchParams.get('visit_mode') ?? 'in_person';
      const price = mode === 'telehealth' ? 12000 : 20000;
      return route.fulfill({ json: {
        hospital_id: PARTNER_ID, visit_mode: mode, price, service_fee: 0, total: price, currency: 'ETB',
        payment: 'at_hospital',
      } });
    });
  }

  function atHospitalBooking(id: string, scheduledAt: string, price = 20000) {
    return {
      appointment_id: id, user_id: 'u', scheduled_at: scheduledAt, appointment_type: 'consultation',
      status: 'SCHEDULED', duration_minutes: 30, location: 'Endod Test General Hospital', meeting_url: null,
      visit_mode: 'in_person', department: 'general_medicine', time_window: 'morning',
      facility: { id: PARTNER_ID, name: 'Endod Test General Hospital' }, provider_name: null, notes: null,
      timezone: 'Africa/Addis_Ababa', created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      hospital_booking: {
        hospital_id: PARTNER_ID, state: 'awaiting_hospital', price, service_fee: 0, total: price, reason: null,
        video_ready: false, payment: { status: 'at_hospital', due_at: null, checkout_url: null },
      },
    };
  }

  test('a priced partner hospital is bookable, showing what to pay at the hospital', async ({ page }) => {
    await paymentsOff(page);
    let posted: Record<string, unknown> | null = null;
    await page.route('**/api/backend/users/me/appointments', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      posted = route.request().postDataJSON();
      return route.fulfill({ status: 201, json: {
        appointment: atHospitalBooking('a7a7a7a7-0000-4000-8000-000000000001', posted!.scheduled_at as string),
        payment: { price: 20000, service_fee: 0, total: 20000, currency: 'ETB', status: 'at_hospital',
                   checkout_url: null, tx_ref: null, expires_at: null },
        reminders: { queued: 0, job_ids: [], skipped: [], offsets: [], channels: {} },
      } });
    });
    await openSection(page, 'Booking', 'booking-view');
    await page.locator('[data-purpose="hospital-search"]').fill('Endod Test General');
    const card = page.locator(PARTNER);
    await expect(card.locator('[data-purpose="pay-at-hospital-tag"]')).toHaveText('Pay at the hospital');
    await card.getByRole('button', { name: 'Book Now' }).click();

    const modal = page.locator('[data-purpose="booking-modal"]');
    await expect(modal.locator('[data-purpose="pay-at-hospital"]')).toHaveText('Pay ETB 200.00 at the hospital');
    await expect(modal.locator('[data-purpose="pay-hint"]')).toContainText('no Endod fee');
    await expect(modal).not.toContainText("Online payment isn't available yet. Please try again later.");
    await expect(modal.locator('[data-purpose="quote-total"]')).toHaveCount(0);
    if (VIDEO_VISITS) {
      // A video visit has its own price.
      await modal.locator('[data-purpose="visit-mode"]').getByText('Video').click();
      await expect(modal.locator('[data-purpose="pay-at-hospital"]')).toHaveText('Pay ETB 120.00 at the hospital');
      await modal.locator('[data-purpose="visit-mode"]').getByText('In person', { exact: true }).click();
      await expect(modal.locator('[data-purpose="pay-at-hospital"]')).toHaveText('Pay ETB 200.00 at the hospital');
    } else {
      await expect(modal.locator('[data-purpose="visit-mode"]')).toHaveCount(0);
    }

    await fillVisit(page, 8, 'Pay at the hospital test');
    const book = modal.getByRole('button', { name: 'Book, pay at the hospital' });
    await expect(book).toBeEnabled();
    await book.click();
    await expect(page.locator('[data-purpose="success-modal"]')).toBeVisible();
    await expect(page.locator('[data-purpose="booked-pay-at-hospital"]')).toHaveText('Pay ETB 200.00 at the hospital');
    expect(posted).toMatchObject({ facility_id: PARTNER_ID, visit_mode: 'in_person' });
    // Never sent to a checkout.
    await expect(page).toHaveURL(/section=booking/);
  });

  test('Appointments shows what to pay at the hospital, and cancelling promises no refund', async ({ page }) => {
    const id = 'a7a7a7a7-0000-4000-8000-000000000002';
    const declinedId = 'a7a7a7a7-0000-4000-8000-000000000003';
    const declined = atHospitalBooking(declinedId, futureSlot(10, 9, 30).iso);
    declined.status = 'CANCELLED';
    declined.hospital_booking.state = 'rejected';
    await page.route('**/api/backend/users/me/appointments?**', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const real = await (await route.fetch()).json();
      return route.fulfill({ json: [atHospitalBooking(id, futureSlot(9, 9, 30).iso), declined, ...real] });
    });
    await openSection(page, 'Appointment', 'appointment-view');
    const card = page.locator(`[data-purpose="appointment-card-${id}"]`);
    await expect(card.locator('[data-purpose="payment-status"]')).toHaveText('Pay at the hospital: ETB 200.00');
    await expect(card.locator('[data-purpose="pay-now"]')).toHaveCount(0);
    await card.getByRole('button', { name: 'Cancel' }).click();
    await expect(card.locator('[data-purpose="cancel-confirm"]')).not.toContainText('refund');
    await card.getByRole('button', { name: 'Keep' }).click();

    // A visit that will not happen asks for nothing.
    await page.locator('[data-purpose="appointment-tab-cancelled"]').click();
    await expect(page.locator(`[data-purpose="appointment-card-${declinedId}"] [data-purpose="payment-status"]`))
      .toHaveText('Nothing to pay: this visit will not happen');
  });

  test('in Amharic too', async ({ page }) => {
    await paymentsOff(page);
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'am' } });
    try {
      await page.goto('/interview?section=booking', { waitUntil: 'networkidle' });
      await page.locator('[data-purpose="hospital-search"]').fill('Endod Test General');
      await expect(page.locator(PARTNER).locator('[data-purpose="pay-at-hospital-tag"]')).toHaveText('ክፍያው በሆስፒታሉ ነው');
      await page.locator(PARTNER).locator('button').last().click();
      await expect(page.locator('[data-purpose="pay-at-hospital"]')).toHaveText('200.00 ብር በሆስፒታሉ ይከፍላሉ');
    } finally {
      await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'en' } });
    }
  });
});

test.describe('Where the app sends a patient to pay', () => {
  test("only Chapa's checkout, or the origin the backend names for its Chapa server", () => {
    expect(safeCheckoutUrl('https://checkout.chapa.co/checkout/payment/abc')).toBe('https://checkout.chapa.co/checkout/payment/abc');
    for (const bad of [
      'https://evil.example/checkout/abc', 'http://checkout.chapa.co/x', 'https://checkout.chapa.co.evil.example/x',
      'https://user:pw@checkout.chapa.co/x', 'javascript:alert(1)', 'http://127.0.0.1:8012/checkout/x', '', null,
    ]) {
      expect(safeCheckoutUrl(bad)).toBeNull();
    }
    expect(safeCheckoutUrl('http://127.0.0.1:8012/checkout/x', ['http://127.0.0.1:8012'])).toBe('http://127.0.0.1:8012/checkout/x');
  });
});

test.describe('Emergency', () => {
  test.use({ geolocation: { latitude: 9.0, longitude: 38.78 }, permissions: ['geolocation'] });

  test('calls 907 and nearby hospitals, with distance once located', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.locator('[data-purpose="emergency-button"]').click();
    const panel = page.locator('[data-purpose="emergency-panel"]');
    await expect(panel).toBeVisible();
    await expect(panel.locator('[data-purpose="call-ambulance"]')).toHaveAttribute('href', 'tel:907');
    await expect(panel.locator('[data-purpose="call-police"]')).toHaveAttribute('href', 'tel:991');
    const hospital = panel.locator(`[data-purpose="emergency-hospital-${PARTNER_ID}"]`);
    await expect(hospital.getByRole('link', { name: /Call their ambulance/ })).toHaveAttribute('href', 'tel:+251911000111');
    await expect(hospital).not.toContainText(' km');

    await panel.locator('[data-purpose="emergency-locate"]').click();
    await expect(hospital).toContainText(' km');

    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
  });

  test('shows the hospitals and the patient on an OpenStreetMap map', async ({ page }) => {
    // Tiles come from OpenStreetMap; the test serves a blank tile instead.
    let tiles = 0;
    await page.route('https://tile.openstreetmap.org/**', (route) => {
      tiles += 1;
      return route.fulfill({ contentType: 'image/png', body: BLANK_PNG });
    });
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.locator('[data-purpose="emergency-button"]').click();
    const panel = page.locator('[data-purpose="emergency-panel"]');
    const map = panel.locator('[data-purpose="hospital-map"]');
    await expect(map).toBeVisible();
    await expect(map.locator('.leaflet-marker-icon[title="Endod Test General Hospital"]')).toBeVisible();
    await expect(map).toContainText('OpenStreetMap');
    await expect.poll(() => tiles).toBeGreaterThan(0);

    // Located: the patient's own dot joins the hospitals.
    await panel.locator('[data-purpose="emergency-locate"]').click();
    await expect(map.locator('.leaflet-marker-icon[title="You are here"]')).toBeVisible();
  });
});

test.describe('Emergency dialog keyboard use', () => {
  test('Tab stays inside, and closing returns focus to the Emergency button', async ({ page }) => {
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const button = page.locator('[data-purpose="emergency-button"]');
    await button.focus();
    await page.keyboard.press('Enter');
    const panel = page.locator('[data-purpose="emergency-panel"]');
    await expect(panel.locator(`[data-purpose="emergency-hospital-${PARTNER_ID}"]`)).toBeVisible();
    for (let i = 0; i < 15; i++) {
      await page.keyboard.press('Tab');
      expect(await panel.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Shift+Tab');
    expect(await panel.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    await expect(button).toBeFocused();
  });
});

test.describe('Chapa notifications (public routes)', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('the webhook refuses oversized bodies and tells callers nothing more', async ({ request }) => {
    const big = await request.post('/api/payments/chapa/webhook', {
      data: 'x'.repeat(70_000), headers: { 'Content-Type': 'text/plain' },
    });
    expect(big.status()).toBe(413);
    const unknown = await request.post('/api/payments/chapa/webhook', { data: { tx_ref: 'endod-unknown' } });
    expect(unknown.status()).toBe(400);
    expect(await unknown.json()).toEqual({ ok: false });
  });

  test('the callback takes the reference from a POST body too', async ({ request }) => {
    const json = await request.post('/api/payments/chapa/callback', { data: { trx_ref: 'endod-unknown' } });
    const form = await request.post('/api/payments/chapa/callback', { form: { tx_ref: 'endod-unknown' } });
    const none = await request.post('/api/payments/chapa/callback', { data: {} });
    // Unknown here: found and checked, but not ours (the backend says 404), never "missing".
    expect(json.status()).toBe(404);
    expect(form.status()).toBe(404);
    expect(none.status()).toBe(400);
  });
});
