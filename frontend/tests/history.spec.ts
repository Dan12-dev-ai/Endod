import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import { test, expect, type Page } from './fixtures';
import { openSection, PARTNER_ID, seed } from './helpers';

// The History page, record files, sharing, follow-ups and the queue card,
// against the real backend. Hospital records are published through the event
// handlers (tests/seed.py) and their files served by tests/fake-hospital.mjs.

const HOSPITAL = 'Endod Test General Hospital';

// Days are Addis Ababa days, in the browser too.
test.use({ timezoneId: 'Africa/Addis_Ababa' });

async function dedanId(page: Page): Promise<string> {
  const me = await (await page.request.get('/api/backend/users/me')).json();
  return me.dedan_user_id as string;
}

/** A calendar day `days` from today in Addis Ababa (YYYY-MM-DD). */
function addisDay(days: number): string {
  const at = new Date(Date.now() + days * 86_400_000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Addis_Ababa' }).format(at);
}

function item(page: Page, title: string) {
  return page.locator('[data-purpose="history-item"]', { hasText: title });
}

test.describe('History', () => {
  test('hospital records show by category with details, search and dates', async ({ page }) => {
    const tag = Date.now().toString(36);
    seed('records', await dedanId(page), tag);
    await openSection(page, 'Medical Record', 'medical-record-view');

    const lab = item(page, `Complete blood count ${tag}`);
    await expect(lab).toContainText(HOSPITAL);
    await expect(lab).toContainText('Dr. Hiwot Bekele');
    await expect(lab.locator('[data-purpose="record-source"]')).toHaveText('Verified');
    await lab.getByRole('button', { expanded: false }).click();
    const detail = page.locator('[data-purpose="medical-record-detail"]');
    const table = detail.locator('[data-purpose="lab-table"]');
    await expect(table.locator('tr[data-flag="low"]')).toContainText('Hemoglobin');
    await expect(table.locator('tr[data-flag="low"]')).toContainText('Low');
    await expect(detail).toContainText('Specimen: Blood');

    await page.locator('[data-purpose="back-link"]').click();
    await expect(page.locator('[data-purpose="medical-record-view"]')).toBeVisible();

    const rx = item(page, `Malaria treatment ${tag}`);
    await rx.getByRole('button', { expanded: false }).click();
    const rxDetail = page.locator('[data-purpose="medical-record-detail"]');
    await expect(rxDetail.locator('[data-purpose="medicine-list"]')).toContainText('Artemether-lumefantrine 4 tablets');
    await expect(rxDetail.locator('[data-purpose="medicine-list"]')).toContainText('twice a day');

    await page.locator('[data-purpose="back-link"]').click();
    await expect(page.locator('[data-purpose="medical-record-view"]')).toBeVisible();

    // Tabs
    await page.locator('[data-purpose="history-tab-labs"]').click();
    await expect(lab).toBeVisible();
    await expect(rx).toHaveCount(0);
    await page.locator('[data-purpose="history-tab-imaging"]').click();
    await expect(item(page, `Chest X-ray ${tag}`)).toBeVisible();
    await expect(lab).toHaveCount(0);
    await page.locator('[data-purpose="history-tab-all"]').click();
  });

  test('a record file previews and downloads through the app only', async ({ page, browser }) => {
    const tag = Date.now().toString(36);
    seed('records', await dedanId(page), tag);
    await openSection(page, 'Medical Record', 'medical-record-view');
    const lab = item(page, `Complete blood count ${tag}`);
    await lab.getByRole('button', { expanded: false }).click();
    const detail = page.locator('[data-purpose="medical-record-detail"]');
    const file = detail.locator('[data-purpose="record-file"]');
    await expect(file).toContainText('cbc-scan.png');

    await file.locator('[data-purpose="file-preview-button"]').click();
    const preview = page.locator('[data-purpose="file-preview"] img');
    await expect(preview).toBeVisible();
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(8);
    await page.keyboard.press('Escape');

    const [download] = await Promise.all([page.waitForEvent('download'), file.locator('[data-purpose="file-download"]').click()]);
    expect(download.suggestedFilename()).toBe('cbc-scan.png');
    const bytes = fs.readFileSync((await download.path())!);
    expect(bytes.subarray(0, 8).toString('latin1')).toBe('\x89PNG\r\n\x1a\n');

    const href = (await file.locator('[data-purpose="file-download"]').getAttribute('href'))!;
    const served = await page.request.get(href);
    expect(served.headers()['content-type']).toBe('image/png');
    expect(served.headers()['x-content-type-options']).toBe('nosniff');
    // Malformed ids, another path, and no session are all refused.
    expect((await page.request.get('/api/records/files/..%2F..%2Fetc/passwd')).status()).toBe(404);
    expect((await page.request.get(`/api/records/files/${'f'.repeat(32)}/${'f'.repeat(32)}`)).status()).toBe(404);
    const anonymous = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    expect((await anonymous.request.get(`http://localhost:3100${href}`)).status()).toBe(401);
    await anonymous.close();
    // The JSON proxy never reaches /internal.
    expect((await page.request.get(`/api/backend/internal/shares/${'a'.repeat(32)}/files/${'a'.repeat(32)}`)).status()).toBe(404);

    // A PDF opens in a new tab.
    await page.locator('[data-purpose="back-link"]').click();
    await expect(page.locator('[data-purpose="medical-record-view"]')).toBeVisible();

    const xray = item(page, `Chest X-ray ${tag}`);
    await xray.getByRole('button', { expanded: false }).click();
    const xrayDetail = page.locator('[data-purpose="medical-record-detail"]');
    await expect(xrayDetail.locator('[data-purpose="file-open"]')).toHaveAttribute('target', '_blank');
    const pdf = await page.request.get((await xrayDetail.locator('[data-purpose="file-open"]').getAttribute('href'))!);
    expect(pdf.headers()['content-type']).toBe('application/pdf');
    expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
  });

  test('a file still arriving shows up by itself', async ({ page }) => {
    test.setTimeout(60_000);
    const tag = Date.now().toString(36);
    seed('records-arriving', await dedanId(page), tag);
    await openSection(page, 'Medical Record', 'medical-record-view');
    const lab = item(page, `Complete blood count ${tag}`);
    await lab.getByRole('button', { expanded: false }).click();
    const detail = page.locator('[data-purpose="medical-record-detail"]');
    const file = detail.locator('[data-purpose="record-file"]');
    await expect(file.locator('[data-purpose="file-state"]')).toHaveText('Still arriving');
    await expect(file.locator('[data-purpose="file-download"]')).toHaveCount(0);

    // The platform downloads it; the page asks again every 10 seconds.
    seed('download');
    await expect(file.locator('[data-purpose="file-download"]')).toBeVisible({ timeout: 25_000 });
    await expect(file.locator('[data-purpose="file-state"]')).toHaveCount(0);
  });

  test('records are shared with a partner hospital until a date, and sharing stops', async ({ page }) => {
    const tag = Date.now().toString(36);
    seed('records', await dedanId(page), tag);
    await openSection(page, 'Medical Record', 'medical-record-view');
    await expect(item(page, `Malaria ${tag}`)).toBeVisible();
    await page.locator('[data-purpose="share-records"]').click();
    const modal = page.locator('[data-purpose="share-modal"]');
    await modal.getByRole('searchbox').fill(tag);
    await modal.locator('[data-purpose="share-record"]', { hasText: `Complete blood count ${tag}` }).locator('input').check();
    await modal.locator('[data-purpose="share-record"]', { hasText: `Chest X-ray ${tag}` }).locator('input').check();
    await expect(modal.locator('[data-purpose="share-selected"]')).toHaveText('2 selected');
    await modal.getByRole('button', { name: 'Share', exact: true }).click();
    await expect(modal.locator('[data-purpose="share-error"]')).toHaveText('Choose a hospital.');
    await modal.locator('#share-hospital').selectOption(PARTNER_ID);
    await modal.locator('#share-until').fill(addisDay(30));
    await modal.getByRole('button', { name: 'Share', exact: true }).click();
    await expect(modal).toHaveCount(0);
    await expect(page.locator('[data-purpose="toast-notification"]')).toContainText('Records shared');

    const share = page.locator('[data-purpose="share"][data-status="active"]', { hasText: `Chest X-ray ${tag}` });
    await expect(share).toContainText(HOSPITAL);
    await expect(share).toContainText('2 records');
    await share.locator('[data-purpose="share-revoke"]').click();
    const stopped = page.locator('[data-purpose="share"][data-status="revoked"]', { hasText: `Chest X-ray ${tag}` });
    await expect(stopped.locator('[data-purpose="share-status"]')).toHaveText('Stopped');
    await expect(stopped.locator('[data-purpose="share-revoke"]')).toHaveCount(0);
  });

  test('download my records opens a printable page', async ({ page }) => {
    const tag = Date.now().toString(36);
    seed('records', await dedanId(page), tag);
    await page.goto('/history/print', { waitUntil: 'networkidle' });
    await expect(page.locator('[data-purpose="print-item"]', { hasText: `Complete blood count ${tag}` })).toContainText('Hemoglobin');
    await expect(page.locator('[data-purpose="print-patient"]')).toContainText('Test Patient');
    await expect(page.locator('[data-purpose="print-button"]')).toBeEnabled();
    await page.emulateMedia({ media: 'print' });
    await expect(page.locator('[data-purpose="print-button"]')).toBeHidden();
  });

  test('works at phone width, in Amharic', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 760 });
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'am' } });
    try {
      await page.context().clearCookies({ name: 'endod_language' });
      await page.goto('/interview', { waitUntil: 'networkidle' });
      await page.locator('[data-purpose="mobile-nav-followup"]').click();
      await expect(page.getByRole('heading', { name: 'የጤና ታሪክዎ' })).toBeVisible();
      await expect(page.locator('[data-purpose="history-tab-labs"]')).toHaveText('የላብራቶሪ ውጤቶች');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    } finally {
      await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'en' } });
    }
  });
});

test.describe('Follow-ups and queues', () => {
  test('a follow-up shows on Home and Book now opens booking at that hospital on that day', async ({ page }) => {
    const day = addisDay(12);
    seed('follow-up', await dedanId(page), day);
    await page.goto('/interview', { waitUntil: 'networkidle' });
    const followUp = page.locator('[data-purpose="home-view"] [data-purpose="follow-up"]', { hasText: HOSPITAL }).first();
    await expect(followUp).toContainText('Dr. Hiwot Bekele');
    await expect(followUp).toContainText('Bring your lab results');
    await followUp.locator('[data-purpose="follow-up-book"]').click();
    const modal = page.locator('[data-purpose="booking-modal"]');
    await expect(modal).toContainText(HOSPITAL);
    await expect(modal.locator('#booking-date')).toHaveValue(day);
    // An earlier day is allowed.
    await modal.locator('#booking-date').fill(addisDay(5));
    await expect(modal.locator('#booking-date')).toHaveValue(addisDay(5));
  });

  test('the queue card shows the live place on Home and Appointments', async ({ page }) => {
    test.setTimeout(60_000);
    const dedan = await dedanId(page);
    const entry = randomUUID().replace(/-/g, '');
    seed('queue', dedan, entry, '1', '3', 'waiting');
    try {
      await page.goto('/interview', { waitUntil: 'networkidle' });
      const card = page.locator('[data-purpose="home-view"] [data-purpose="queue-card"]');
      await expect(card.locator('[data-purpose="queue-position"]')).toHaveText('You are number 4');
      await expect(card.locator('[data-purpose="queue-ahead"]')).toHaveText('3 people ahead of you');
      await expect(card).toContainText('Dr. Hiwot Bekele');
      await expect(card).toContainText('17');

      // The card follows the queue by itself (it asks every 15 seconds).
      seed('queue', dedan, entry, '2', '1', 'waiting');
      await expect(card.locator('[data-purpose="queue-ahead"]')).toHaveText('1 person ahead of you', { timeout: 20_000 });
      seed('queue', dedan, entry, '3', '0', 'called');
      await openSection(page, 'Appointment', 'appointment-view');
      await expect(page.locator('[data-purpose="appointment-view"] [data-purpose="queue-called"]')).toHaveText("It's your turn. Please go in.");
    } finally {
      // Seen: the card goes away for the other tests.
      seed('queue', dedan, entry, '9', '0', 'done');
    }
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await expect(page.locator('[data-purpose="queue-card"]')).toHaveCount(0);
  });
});
