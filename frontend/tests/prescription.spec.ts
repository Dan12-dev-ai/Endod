import jsQR from 'jsqr';
import { PNG } from 'pngjs';
import { test, expect, type Page } from './fixtures';
import { openSection, seed } from './helpers';

// A hospital prescription in History, as a pharmacy uses it
// (docs/pharmacy.md section 3): the QR to scan, the 6-digit code, until when
// it works, what has been given and where. The prescription and a dispense
// are seeded through the platform's own handlers (tests/seed.py).

test.use({ timezoneId: 'Africa/Addis_Ababa' });

async function dedanId(page: Page): Promise<string> {
  const me = await (await page.request.get('/api/backend/users/me')).json();
  return me.dedan_user_id as string;
}

// A record opens on its own page: the pharmacy block (QR, code, dispenses) is there.
function recordDetail(page: Page) {
  return page.locator('[data-purpose="medical-record-detail"]');
}

function prescription(page: Page, tag: string) {
  return page.locator('[data-purpose="history-item"]', { hasText: `Chest infection ${tag}` });
}

test.describe('Prescriptions at the pharmacy', () => {
  test('History shows the QR, the code, expiry, item statuses and dispenses', async ({ page }) => {
    const tag = Date.now().toString(36);
    seed('prescription', await dedanId(page), tag);
    seed('dispense', tag, 'Kenema Pharmacy', '14');
    await openSection(page, 'Medical Record', 'medical-record-view');

    const rx = prescription(page, tag);
    await rx.getByRole('button', { expanded: false }).click();
    const panel = recordDetail(page).locator('[data-purpose="rx-pharmacy"]');
    await expect(panel).toHaveAttribute('data-status', 'open');
    await expect(panel.locator('[data-purpose="rx-code"]')).toHaveText(/^\d{6}$/);
    await expect(panel.locator('[data-purpose="rx-expiry"]')).toContainText('Valid until');

    // The QR scans to the pharmacy site's link with a signed token.
    const qr = panel.locator('[data-purpose="rx-qr"]');
    await expect(qr).toBeVisible();
    const src = (await qr.getAttribute('src')) ?? '';
    expect(src.startsWith('data:image/png;base64,')).toBe(true);
    const png = PNG.sync.read(Buffer.from(src.split(',')[1], 'base64'));
    const decoded = jsQR(new Uint8ClampedArray(png.data), png.width, png.height);
    expect(decoded?.data).toMatch(/^https:\/\/pharmacy\.endod-health\.com\/rx\/[0-9a-f]{32}\.[A-Za-z0-9_-]{22}$/);
    const box = await qr.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(200); // large enough to scan from a phone screen

    const items = panel.locator('[data-purpose="rx-item"]');
    await expect(items).toHaveCount(2);
    await expect(items.nth(0)).toContainText('Amoxicillin 500 mg');
    await expect(items.nth(0).locator('[data-purpose="rx-item-status"]')).toHaveText('14 of 21 given');
    await expect(items.nth(1).locator('[data-purpose="rx-item-status"]')).toHaveText('Not given yet');
    await expect(panel.locator('[data-purpose="rx-dispense"]')).toHaveCount(1);
    await expect(panel.locator('[data-purpose="rx-dispense"]')).toContainText('Pharmacy (as entered): Kenema Pharmacy');
    // The typed name is plain text, never a link.
    await expect(panel.locator('[data-purpose="rx-dispenses"] a')).toHaveCount(0);

    // The dispense reached the inbox, without the medicine's name: a generic
    // title, the pharmacy only in the body, labelled as entered.
    const inbox = await (await page.request.get('/api/backend/users/me/inbox')).json();
    const notice = inbox.items.find((i: { kind: string }) => i.kind === 'prescription_dispensed');
    expect(notice.title).toBe('Medicine given at a pharmacy');
    expect(notice.body).toContain('Pharmacy (as entered): Kenema Pharmacy.');
    expect(JSON.stringify(notice)).not.toContain('Amoxicillin');

    // The rest of the first medicine, at another pharmacy.
    seed('dispense', tag, 'Bole Pharmacy', '7');
    await page.reload({ waitUntil: 'networkidle' });
    await page.locator('aside').getByRole('link', { name: 'Medical Record' }).click();
    const after = prescription(page, tag);
    await after.getByRole('button', { expanded: false }).click();
    await expect(recordDetail(page).locator('[data-purpose="rx-item"]').nth(0).locator('[data-purpose="rx-item-status"]')).toHaveText('Given');
    await expect(recordDetail(page).locator('[data-purpose="rx-dispense"]')).toHaveCount(2);
    await expect(recordDetail(page).locator('[data-purpose="rx-qr"]')).toHaveCount(1); // the second medicine is still to give
  });

  test('works at phone width, in Amharic', async ({ page }) => {
    const tag = Date.now().toString(36);
    seed('prescription', await dedanId(page), tag);
    seed('dispense', tag, 'Kenema Pharmacy', '14');
    await page.setViewportSize({ width: 375, height: 760 });
    await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'am' } });
    try {
      await page.context().clearCookies({ name: 'endod_language' });
      await page.goto('/interview', { waitUntil: 'networkidle' });
      await page.locator('[data-purpose="mobile-nav-followup"]').click();
      const rx = prescription(page, tag);
      await rx.getByRole('button', { expanded: false }).click();
      const panel = recordDetail(page).locator('[data-purpose="rx-pharmacy"]');
      await expect(panel.locator('[data-purpose="rx-status"]')).toHaveText('መጠቀም ይቻላል');
      await expect(panel.locator('[data-purpose="rx-item-status"]').nth(0)).toHaveText('ከ21 14 ተሰጥቷል');
      await expect(panel.locator('[data-purpose="rx-item-status"]').nth(1)).toHaveText('ገና አልተሰጠም');
      await expect(panel.locator('[data-purpose="rx-qr"]')).toBeVisible();
      await expect(panel.locator('[data-purpose="rx-code"]')).toHaveText(/^\d{6}$/);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    } finally {
      await page.request.patch('/api/backend/users/me/preferences', { data: { language: 'en' } });
    }
  });
});
