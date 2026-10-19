import { test, expect } from '@playwright/test';

// The signed-in state on public pages, the sign-in redirects, and the
// Digital Health Card's verifiable QR code. Runs as the shared test patient
// ("Test Patient", onboarding finished).

test.describe('Signed in', () => {
  test('the landing page shows the account, and Get Started opens the dashboard', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-purpose="nav-account-name"]')).toHaveText('Test');
    await expect(page.locator('[data-purpose="nav-sign-up"]')).toHaveCount(0);

    await page.locator('[data-purpose="hero-cta"]').click();
    await expect(page).toHaveURL(/\/interview$/);
  });

  test('the account menu leads to the dashboard and the health card', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Account menu' }).click();
    await expect(page.getByRole('menuitem', { name: 'My health card' })).toBeVisible();
    await page.getByRole('menuitem', { name: 'Dashboard' }).click();
    await expect(page).toHaveURL(/\/interview$/);
  });

  test('/login?next= takes a signed-in patient straight to that page', async ({ page }) => {
    await page.goto('/login?next=%2Fhealth-card');
    await expect(page).toHaveURL(/\/health-card$/);
  });

  test('forgot password stays reachable while signed in', async ({ page }) => {
    await page.goto('/signup?reset=1');
    await expect(page).toHaveURL(/\/signup\?reset=1$/);
  });

  test('the dashboard still shows the name when the card signature cannot be fetched', async ({ page }) => {
    await page.route('**/api/backend/users/me/card', (route) => route.fulfill({ status: 503, body: '{}' }));
    await page.goto('/interview', { waitUntil: 'networkidle' });
    await expect(page.getByText('Test Patient').first()).toBeVisible();
  });

  for (const path of ['/login', '/signup']) {
    test(`${path} sends a signed-in patient to the dashboard`, async ({ page }) => {
      await page.goto(path);
      await expect(page).toHaveURL(/\/interview$/);
    });
  }
});

test.describe('Signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('the landing page offers sign in and sign up', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('[data-purpose="nav-sign-up"]')).toBeVisible();
    await expect(page.locator('[data-purpose="nav-account"]')).toHaveCount(0);
    await page.locator('[data-purpose="hero-cta"]').click();
    await expect(page).toHaveURL(/\/signup$/);
  });

  test('a session the backend no longer accepts is cleared, not looped', async ({ page, context }) => {
    await context.addCookies([{ name: 'dedan_session', value: 'expired-or-forged', url: 'http://localhost:3100' }]);
    await page.goto('/login');
    await expect(page).toHaveURL(/\/login$/);
    const cookies = await context.cookies();
    expect(cookies.find((c) => c.name === 'dedan_session')?.value ?? '').toBe('');
    await page.goto('/interview');
    await expect(page).toHaveURL(/\/login\?next=%2Finterview$/);
  });
});

test.describe('Digital Health Card', () => {
  test('the QR code links to a check that confirms the card', async ({ page, browser }) => {
    const card = await (await page.request.get('/api/backend/users/me/card')).json();
    expect(card.dedan_user_id).toMatch(/^DE\d{6}$/);

    await page.goto('/health-card');
    await expect(page.getByText(card.dedan_user_id).first()).toBeVisible();

    // Anyone can scan it, signed in or not.
    const scanner = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const scan = await scanner.newPage();
    await scan.goto(`/card/${card.dedan_user_id}?s=${card.signature}`);
    await expect(scan.locator('[data-purpose="card-valid"]')).toBeVisible();
    await expect(scan.getByText('Test Patient')).toBeVisible();

    const forged = card.dedan_user_id === 'DE000001' ? 'DE000002' : 'DE000001';
    await scan.goto(`/card/${forged}?s=${card.signature}`);
    await expect(scan.locator('[data-purpose="card-invalid"]')).toBeVisible();
    await scanner.close();
  });
});
