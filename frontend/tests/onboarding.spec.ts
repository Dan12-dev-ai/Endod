import { test, expect, request as playwrightRequest, type Page } from '@playwright/test';

// Onboarding for a brand-new account, against the real backend.
test.use({ storageState: { cookies: [], origins: [] } });

const BACKEND_URL = 'http://127.0.0.1:8011';
const PASSWORD = 'OnboardingPass1';

async function newPatientSignedIn(page: Page) {
  const email = `onboard-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.com`;
  const backend = await playwrightRequest.newContext({ baseURL: BACKEND_URL });
  const registered = await backend.post('/auth/register', {
    data: { first_name: 'New', last_name: 'Person', email, password: PASSWORD, password_confirmation: PASSWORD },
  });
  expect(registered.status()).toBe(201);
  // Registering by email takes a name; a phone sign-up does not. Clear it so
  // this account is where a new phone sign-up is: onboarding not finished.
  const token = (await registered.json()).access_token as string;
  const cleared = await backend.patch('/users/me', {
    headers: { Authorization: token }, data: { first_name: null, last_name: null },
  });
  expect(cleared.ok()).toBeTruthy();
  await backend.dispose();
  const login = await page.request.post('/api/auth/login', { data: { identifier: email, password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
}

async function answerUpToAge(page: Page, { open = true } = {}) {
  if (open) await page.goto('/onboarding');
  await page.locator('#first-name').fill('Almaz');
  await page.locator('#last-name').fill('Bekele');
  await page.locator('#last-name').press('Enter');
  // Each step advances on its own after a short animation.
  await expect(page.getByText('Step 2 of 4')).toBeVisible();
  await page.locator('[data-purpose="step-looking-for"] button').first().click();
  await expect(page.getByText('Step 3 of 4')).toBeVisible();
  await page.locator('[data-purpose="step-sex"]').getByText('Female', { exact: true }).click();
  await expect(page.getByText('Step 4 of 4')).toBeVisible();
}

test.describe('Onboarding', () => {
  test('with consent, sex and age are saved to the health profile', async ({ page }) => {
    await newPatientSignedIn(page);
    await answerUpToAge(page);

    await page.locator('[data-purpose="health-consent"] input').check();
    await page.getByLabel('21–40').check({ force: true });
    // Picking an age does not finish on its own.
    await page.waitForTimeout(800);
    await expect(page).toHaveURL(/\/onboarding$/);
    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page).toHaveURL(/\/interview$/);

    const health = await (await page.request.get('/api/backend/users/me/health-profile')).json();
    expect(health.sex).toBe('female');
    expect(health.age_range).toBe('21-40');
  });

  test('without consent, nothing health-related is stored', async ({ page }) => {
    await newPatientSignedIn(page);
    await answerUpToAge(page);

    await page.getByLabel('41–60').check({ force: true });
    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page).toHaveURL(/\/interview$/);

    const consent = await (await page.request.get('/api/backend/users/me/consent')).json();
    expect(consent.treatment_processing).toBe(false);
    const profile = await (await page.request.get('/api/backend/users/me')).json();
    expect(profile.first_name).toBe('Almaz');
  });
});

test.describe('Onboarding redirects', () => {
  test('an unfinished onboarding comes first, and a finished one is not shown again', async ({ page }) => {
    await newPatientSignedIn(page);
    await page.goto('/interview');
    await expect(page).toHaveURL(/\/onboarding$/);
    await page.goto('/health-card');
    await expect(page).toHaveURL(/\/onboarding\?next=%2Fhealth-card$/);

    await answerUpToAge(page);
    await page.getByLabel('41–60').check({ force: true });
    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page).toHaveURL(/\/interview$/);

    await page.goto('/onboarding');
    await expect(page).toHaveURL(/\/interview$/);
  });
});

test.describe('Onboarding keeps the destination', () => {
  test('a page asked for before onboarding opens after it', async ({ page }) => {
    await newPatientSignedIn(page);
    await page.goto('/health-card');
    await expect(page).toHaveURL(/\/onboarding\?next=%2Fhealth-card$/);
    await answerUpToAge(page, { open: false });
    await page.getByLabel('41–60').check({ force: true });
    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page).toHaveURL(/\/health-card$/);
  });
});
