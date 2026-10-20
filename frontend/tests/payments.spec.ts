import { test, expect, type Page } from '@playwright/test';
import { createAppointment, futureSlot, openSection, PARTNER_ID, seed } from './helpers';

// The Endod balance (through tests/fake-chapa.mjs, which behaves like Chapa's
// checkout), paid bookings at a partner hospital (listed by tests/seed.py),
// video visits (Jitsi's script stubbed) and the emergency panel (Google Maps
// stubbed). The tests build on each other, so they run in order.

test.describe.configure({ mode: 'serial' });
// Patients and partner hospitals are in Ethiopia: times are entered in Addis Ababa time
// (CI machines run in UTC, where 09:30 would be 12:30 at the hospital).
test.use({ timezoneId: 'Africa/Addis_Ababa' });

const PARTNER = `[data-purpose="hospital-${PARTNER_ID}"]`;

async function balanceText(page: Page) {
  await openSection(page, 'Balance', 'wallet-view');
  return page.locator('[data-purpose="wallet-amount"]');
}

async function openPartnerBooking(page: Page) {
  await openSection(page, 'Booking', 'booking-view');
  await page.locator('[data-purpose="hospital-search"]').fill('Endod Test General');
  const card = page.locator(PARTNER);
  await expect(card.locator('[data-purpose="partner-details"]')).toContainText('From ETB 200.00');
  await expect(card.locator('[data-purpose="partner-details"]')).toContainText('Private');
  await expect(card.locator('[data-purpose="partner-details"]')).toContainText('Video visits');
  await card.getByRole('button', { name: 'Book Now' }).click();
  await expect(page.locator('[data-purpose="booking-modal"]')).toBeVisible();
}

test.describe('Endod balance and paid bookings', () => {
  test('without money, a partner booking shows the price and asks to add money', async ({ page }) => {
    await openPartnerBooking(page);
    const quote = page.locator('[data-purpose="booking-quote"]');
    await expect(quote).toContainText('200.00');
    await expect(quote).toContainText('5.00');
    await expect(quote.locator('[data-purpose="quote-total"]')).toHaveText('ETB 205.00');
    await expect(page.locator('[data-purpose="needs-money"]')).toBeVisible();

    // The visit type changes the price: a video visit here is 120 birr.
    await page.locator('[data-purpose="visit-mode"]').getByText('Video').click();
    await expect(quote.locator('[data-purpose="quote-total"]')).toHaveText('ETB 125.00');
    await expect(page.locator('[data-purpose="visit-mode"]')).toContainText('A doctor at the hospital approves');

    await page.getByRole('button', { name: 'Add money' }).click();
    await expect(page.locator('[data-purpose="wallet-view"]')).toBeVisible();
    await expect(page.locator('[data-purpose="wallet-empty"]')).toBeVisible();
  });

  test('adding money goes through Chapa and comes back credited', async ({ page }) => {
    await openSection(page, 'Balance', 'wallet-view');
    await expect(page.locator('[data-purpose="wallet-amount"]')).toHaveText('ETB 0.00');

    await page.locator('#deposit-amount').fill('5');
    await page.locator('[data-purpose="deposit-submit"]').click();
    // Below the 10 birr minimum: the form does not submit.
    expect(await page.locator('#deposit-amount').evaluate((el: HTMLInputElement) => el.validity.rangeUnderflow)).toBe(true);
    await expect(page).toHaveURL(/\/interview$/);

    await page.locator('#deposit-amount').fill('500');
    await page.locator('[data-purpose="deposit-submit"]').click();
    // Out to the (fake) Chapa checkout, which pays and returns to the app.
    await page.waitForURL(/\/interview\?section=wallet&deposit=/);
    await expect(page.locator('[data-purpose="wallet-amount"]')).toHaveText('ETB 500.00');
    await expect(page.locator('[data-purpose="wallet-entry-deposit"]')).toContainText('500.00');
    await expect(page.getByText('ETB 500.00 was added to your balance.')).toBeVisible();
  });

  test('an in-person booking pays, shows in Appointments, and cancelling refunds it', async ({ page }) => {
    await openPartnerBooking(page);
    await expect(page.locator('[data-purpose="needs-money"]')).toHaveCount(0);
    const slot = futureSlot(6, 9, 30);
    await page.locator('#booking-date').fill(slot.date);
    await page.locator('#booking-time').fill(slot.time);
    await page.locator('[data-purpose="time-window"]').selectOption('morning');
    await page.locator('#booking-note').fill('Paid booking test');
    await page.getByRole('button', { name: 'Submit Booking' }).click();

    const success = page.locator('[data-purpose="success-modal"]');
    await expect(success).toBeVisible();
    await expect(success.locator('[data-purpose="booked-paid"]')).toContainText('205.00');
    await page.getByRole('button', { name: 'Done' }).click();

    await expect(await balanceText(page)).toHaveText('ETB 295.00');
    await expect(page.locator('[data-purpose="wallet-entry-payment"]')).toContainText('200.00');
    await expect(page.locator('[data-purpose="wallet-entry-service_fee"]')).toContainText('5.00');

    await page.locator('aside').getByRole('link', { name: 'Appointment' }).click();
    const row = page.locator('[data-purpose="appointment-upcoming-list"] > *', { hasText: 'Endod Test General' }).first();
    await expect(row.locator('[data-purpose="hospital-state"]')).toHaveText('Waiting for the hospital');
    await expect(row.locator('[data-purpose="hospital-booking"]')).toContainText('Paid ETB 205.00');
    await row.getByRole('button', { name: 'Cancel' }).click();
    await expect(row.locator('[data-purpose="cancel-confirm"]')).toContainText('ETB 205.00 will go back to your Endod balance.');
    await row.getByRole('button', { name: 'Yes, cancel' }).click();

    await expect(await balanceText(page)).toHaveText('ETB 500.00');
    await expect(page.locator('[data-purpose="wallet-entry-refund"]')).toContainText('205.00');
  });

  test('a video visit waits for the doctor, then opens in Endod with a signed token', async ({ page }) => {
    const at = new Date(Date.now() + 20 * 60_000);
    const appointment = await createAppointment(page.request, {
      scheduled_at: at.toISOString(), timezone: 'Africa/Addis_Ababa', facility_id: PARTNER_ID,
      visit_mode: 'telehealth', department: 'general_medicine',
    });
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
    await page.goto('/visit/not-a-real-appointment');
    await expect(page.locator('[data-purpose="visit-error"]')).toBeVisible();
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
    // No Maps key in this deployment: no map, and nothing breaks.
    await expect(panel.locator('[data-purpose="hospital-map"]')).toHaveCount(0);

    await panel.locator('[data-purpose="emergency-locate"]').click();
    await expect(hospital).toContainText(' km');

    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
  });

  test('shows the hospitals on a map when a Maps key is configured', async ({ page }) => {
    await page.route('**/api/config', (route) => route.fulfill({ json: { googleMapsKey: 'e2e-browser-key' } }));
    await page.route('https://maps.googleapis.com/**', (route) =>
      route.fulfill({
        contentType: 'application/javascript',
        body: `(() => {
          window.__markers = [];
          class LatLngBounds { constructor() { this.n = 0; } extend() { this.n++; } isEmpty() { return this.n === 0; } getCenter() { return {}; } }
          window.google = { maps: {
            Map: class { constructor(el) { el.setAttribute('data-map-ready', 'yes'); } setCenter() {} setZoom() {} fitBounds() {} },
            Marker: class { constructor(o) { window.__markers.push(o.title); } setMap() {} addListener() {} },
            LatLngBounds, SymbolPath: { CIRCLE: 0 },
          } };
          window.__endodMapsReady();
        })();`,
      }),
    );
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await page.locator('[data-purpose="emergency-button"]').click();
    const map = page.locator('[data-purpose="hospital-map"]');
    await expect(map).toBeVisible();
    await expect(map).toHaveAttribute('data-map-ready', 'yes');
    await expect.poll(() => page.evaluate(() => (window as unknown as { __markers: string[] }).__markers)).toContain(
      'Endod Test General Hospital',
    );
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
