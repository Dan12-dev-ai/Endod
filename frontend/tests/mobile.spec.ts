import { test, expect, type Page } from './fixtures';
import { PARTNER_ID, seed, VIDEO_VISITS } from './helpers';

// The phone layout (app/interview/mobile-shell.tsx): /interview is a tile
// dashboard, each section its own screen under /interview/mobile-*, rendering
// the same views as the desktop app, so everything those views do (video off,
// pay at the hospital with the service fee, Bills) holds on a phone too.

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

const SECTIONS = [
  { tile: 'card', title: 'Health card', view: 'health-card-wrapper', path: '/interview/mobile-card' },
  { tile: 'booking', title: 'Book a visit', view: 'booking-view', path: '/interview/mobile-booking' },
  { tile: 'appointment', title: 'My appointments', view: 'appointment-view', path: '/interview/mobile-appointment' },
  { tile: 'bills', title: 'Bills', view: 'bills-view', path: '/interview/mobile-bills' },
  { tile: 'records', title: 'Medical Record', view: 'medical-record-view', path: '/interview/mobile-records' },
  { tile: 'notification', title: 'Notifications', view: 'notification-view', path: '/interview/mobile-notification' },
  { tile: 'setting', title: 'Settings', view: 'settings-view', path: '/interview/mobile-setting' },
];

async function openDashboard(page: Page) {
  await page.goto('/interview', { waitUntil: 'networkidle' });
  await expect(page.locator('[data-purpose="mobile-home"]')).toBeVisible();
}

test.describe('Phone layout', () => {
  test('the dashboard reaches every section, and Back returns to it', async ({ page }) => {
    await openDashboard(page);
    // The desktop sidebar app is not what a phone gets.
    await expect(page.locator('[data-purpose="mobile-nav"]')).toHaveCount(0);
    for (const s of SECTIONS) {
      await page.locator(`[data-purpose="mobile-tile-${s.tile}"]`).click();
      await expect(page).toHaveURL(s.path);
      await expect(page.locator(`[data-purpose="${s.view}"]`)).toBeVisible();
      await expect(page.locator('[data-purpose="mobile-title"]')).toHaveText(s.title);
      await page.locator('[data-purpose="mobile-back"]').click();
      await expect(page.locator('[data-purpose="mobile-home"]')).toBeVisible();
    }
  });

  test('the bottom bar moves between sections and marks the current one', async ({ page }) => {
    await page.goto('/interview/mobile-card', { waitUntil: 'networkidle' });
    // Next keeps the dashboard just left mounted but hidden: only the visible bar counts.
    const bar = page.locator('[data-purpose="mobile-bottom-nav"]:visible');
    for (const [name, view, path] of [
      ['Booking', 'booking-view', '/interview/mobile-booking'],
      ['Appointment', 'appointment-view', '/interview/mobile-appointment'],
      ['Notification', 'notification-view', '/interview/mobile-notification'],
      ['Setting', 'settings-view', '/interview/mobile-setting'],
      ['Card', 'health-card-wrapper', '/interview/mobile-card'],
    ] as const) {
      // The dev-only Next.js badge covers this corner in tests; real phones have no badge.
      await bar.getByRole('link', { name, exact: true }).dispatchEvent('click');
      await expect(page).toHaveURL(path);
      await expect(page.locator(`[data-purpose="${view}"]`)).toBeVisible();
      await expect(bar.getByRole('link', { name, exact: true })).toHaveAttribute('aria-current', 'page');
    }
  });

  test('a tile opens from the keyboard', async ({ page }) => {
    await openDashboard(page);
    const bills = page.getByRole('navigation', { name: 'Services' }).getByRole('link', { name: 'Bills' });
    await bills.focus();
    await expect(bills).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL('/interview/mobile-bills');
    await expect(page.locator('[data-purpose="bills-view"]')).toBeVisible();
  });

  test('a desktop deep link opens the matching phone screen', async ({ page }) => {
    await page.goto('/interview?section=bills', { waitUntil: 'networkidle' });
    await expect(page).toHaveURL('/interview/mobile-bills');
    await expect(page.locator('[data-purpose="bills-view"]')).toBeVisible();
    await page.goto('/interview?section=appointment', { waitUntil: 'networkidle' });
    await expect(page).toHaveURL('/interview/mobile-appointment');
    await expect(page.locator('[data-purpose="appointment-view"]')).toBeVisible();
  });

  test('Bills shows the hospital charge with the Endod service fee', async ({ page }) => {
    const tag = Date.now().toString(36);
    const me = await (await page.request.get('/api/backend/users/me')).json();
    seed('charge', me.dedan_user_id as string, tag);
    await openDashboard(page);
    await page.locator('[data-purpose="mobile-tile-bills"]').click();
    const bill = page.locator('[data-purpose^="bill-"]', { hasText: `Complete blood count ${tag}` });
    await expect(bill.locator('[data-purpose="bill-fee"]')).toHaveText('ETB 25.00');
    await expect(bill.locator('[data-purpose="bill-total"]')).toHaveText('ETB 375.00');
    await expect(bill).toContainText('Pay ETB 375.00 at the hospital (including the Endod service fee).');
  });

  test('booking: in person only while video is off, paid at the hospital with the service fee', async ({ page }) => {
    // As in production before online payment is set up (see payments.spec.ts).
    await page.route('**/api/backend/users/me/payments/status', (route) =>
      route.fulfill({ json: { online_payments: false, checkout_origins: ['https://checkout.chapa.co'], video_visits: VIDEO_VISITS } }),
    );
    await page.route('**/api/backend/users/me/hospital-bookings/quote?**', (route) => {
      const mode = new URL(route.request().url()).searchParams.get('visit_mode') ?? 'in_person';
      const price = mode === 'telehealth' ? 12000 : 20000;
      return route.fulfill({ json: {
        hospital_id: PARTNER_ID, visit_mode: mode, price, service_fee: 2500, total: price + 2500, currency: 'ETB', payment: 'at_hospital',
      } });
    });
    await openDashboard(page);
    await page.locator('[data-purpose="mobile-tile-booking"]').click();
    await page.locator('[data-purpose="hospital-search"]').fill('Endod Test General');
    const card = page.locator(`[data-purpose="hospital-${PARTNER_ID}"]`);
    await expect(card.locator('[data-purpose="pay-at-hospital-tag"]')).toHaveText('Pay at the hospital');
    if (!VIDEO_VISITS) await expect(card.locator('[data-purpose="partner-details"]')).not.toContainText('Video');
    await card.getByRole('button', { name: 'Book Now' }).click();

    const modal = page.locator('[data-purpose="booking-modal"]');
    await expect(modal.locator('[data-purpose="pay-at-hospital"]')).toHaveText('Pay ETB 225.00 at the hospital');
    await expect(modal.locator('[data-purpose="pay-hint"]')).toContainText('plus the Endod service fee (ETB 25.00)');
    if (!VIDEO_VISITS) {
      await expect(modal.locator('[data-purpose="visit-mode"]')).toHaveCount(0);
      await expect(modal).not.toContainText('Video');
    }
  });

  test('Appointments on a phone has no video counter while video is off', async ({ page }) => {
    test.skip(VIDEO_VISITS, 'video visits are on (E2E_VIDEO_VISITS=true)');
    await openDashboard(page);
    await page.locator('[data-purpose="mobile-tile-appointment"]').click();
    await expect(page.locator('[data-purpose="appointment-view"]')).toBeVisible();
    await expect(page.locator('[data-purpose="next-appointment"]')).toBeVisible();
    await expect(page.locator('[data-purpose="next-video-visit"]')).toHaveCount(0);
    await expect(page.locator('[data-purpose="legend-telehealth"]')).toHaveCount(0);
  });

  test('the language switch translates the dashboard', async ({ page }) => {
    await openDashboard(page);
    await page.locator('[data-purpose="mobile-home"] [data-purpose="language-select"]').click();
    await page.locator('[data-purpose="language-option-am"]').click();
    await expect(page.locator('[data-purpose="mobile-tile-bills"]')).toHaveText('ሂሳቦች');
    await expect(page.locator('[data-purpose="mobile-tile-setting"]')).toHaveText('ቅንብር');
    // Back to English for the other tests (the choice is saved with the account).
    await page.locator('[data-purpose="mobile-home"] [data-purpose="language-select"]').click();
    await page.locator('[data-purpose="language-option-en"]').click();
    await expect(page.locator('[data-purpose="mobile-tile-bills"]')).toHaveText('Bills');
  });
});
