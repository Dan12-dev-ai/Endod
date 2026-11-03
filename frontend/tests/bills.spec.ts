import { test, expect, type Page } from './fixtures';
import { openSection, seed } from './helpers';

// Bills from partner hospitals (charges, docs/service-fee.md): paid at the
// hospital, each with Endod's service fee. The charge arrives through the
// event handler (tests/seed.py), as the hospital service sends it.

async function dedanId(page: Page): Promise<string> {
  const me = await (await page.request.get('/api/backend/users/me')).json();
  return me.dedan_user_id as string;
}

test.describe('Bills', () => {
  test('a hospital charge shows with the Endod service fee and the total to pay', async ({ page }) => {
    const tag = Date.now().toString(36);
    seed('charge', await dedanId(page), tag);
    await openSection(page, 'Bills', 'bills-view');

    const bill = page.locator('[data-purpose^="bill-"]', { hasText: `Complete blood count ${tag}` });
    await expect(bill).toContainText('Endod Test General Hospital');
    await expect(bill).toContainText('To pay');
    await expect(bill.locator('[data-purpose="bill-fee"]')).toHaveText('ETB 25.00');
    await expect(bill.locator('[data-purpose="bill-total"]')).toHaveText('ETB 375.00');
    await expect(bill).toContainText('Pay ETB 375.00 at the hospital (including the Endod service fee).');
    await expect(page.locator('[data-purpose="bills-open-total"]')).toContainText('To pay at the hospital: ETB');
  });
});
