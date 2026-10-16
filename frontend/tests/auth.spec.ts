import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from '@playwright/test';

// Sign-in against the real backend. These start signed out.
test.use({ storageState: { cookies: [], origins: [] } });

function credentials(): { email: string; password: string } {
  return JSON.parse(fs.readFileSync(path.join(__dirname, '.auth', 'credentials.json'), 'utf8'));
}

test.describe('Auth', () => {
  test('private pages send a signed-out visitor to login', async ({ page }) => {
    await page.goto('/interview');
    await expect(page).toHaveURL(/\/login\?next=%2Finterview$/);
  });

  test('a wrong password shows the backend message', async ({ page }) => {
    const { email } = credentials();
    await page.goto('/login');
    await page.locator('#phone').fill(email);
    await page.locator('#password').fill('WrongPassword1');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.locator('[data-purpose="form-error"]')).toContainText('Incorrect');
  });

  test('signing in returns to the page that asked for it', async ({ page, context }) => {
    const { email, password } = credentials();
    await page.goto('/login?next=%2Fhealth-card');
    await page.locator('#phone').fill(email);
    await page.locator('#password').fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/health-card$/);
    await expect(page.getByText(/DE\d{6}/).first()).toBeVisible();

    // The session is an httpOnly cookie: not readable by page scripts.
    const session = (await context.cookies()).find((c) => c.name === 'dedan_session');
    expect(session?.httpOnly).toBe(true);
    expect(await page.evaluate(() => document.cookie)).not.toContain('dedan_session');
  });

  // Protocol-relative, tab-split and backslash forms all resolve off-site.
  for (const next of ['%2F%2Fevil.example', '%2F%09%2Fevil.example%2Fphish', '%2F%5C%5Cevil.example']) {
    test(`an unsafe next= is ignored (${next})`, async ({ page }) => {
      const { email, password } = credentials();
      await page.goto(`/login?next=${next}`);
      await page.locator('#phone').fill(email);
      await page.locator('#password').fill(password);
      await page.getByRole('button', { name: 'Sign in' }).click();
      await expect(page).toHaveURL(/localhost:3100\/interview$/);
    });
  }

  test('a spoofed X-Forwarded-For does not escape the per-client SMS limit', async ({ request }) => {
    // As behind one trusted proxy: the client-chosen part is on the left,
    // the address the proxy saw on the right.
    const statuses: number[] = [];
    for (let i = 0; i < 32; i++) {
      const phone = `09${String(10_000_000 + i * 997 + Math.floor(Math.random() * 1000)).slice(0, 8)}`;
      const response = await request.post('/api/auth/send-otp', {
        data: { phone },
        headers: { 'X-Forwarded-For': `10.9.${i}.1, 203.0.113.7` },
      });
      statuses.push(response.status());
    }
    expect(statuses).toContain(429);
  });

  test('the backend proxy only serves the patient\'s own data', async ({ request }) => {
    const signedOut = await request.get('/api/backend/users/me');
    expect(signedOut.status()).toBe(401);
    const otherPath = await request.get('/api/backend/auth/session');
    expect(otherPath.status()).toBe(404);
  });
});

test.describe('Sign out', () => {
  test('signs the patient out and protects the app again', async ({ browser }) => {
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const page = await context.newPage();
    const { email, password } = JSON.parse(
      fs.readFileSync(path.join(__dirname, '.auth', 'credentials.json'), 'utf8'),
    ) as { email: string; password: string };
    const login = await page.request.post('/api/auth/login', { data: { identifier: email, password } });
    expect(login.ok()).toBeTruthy();

    await page.goto('/interview');
    await page.locator('[data-purpose="sign-out"]').click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto('/interview');
    await expect(page).toHaveURL(/\/login\?next=/);
    await context.close();
  });
});
