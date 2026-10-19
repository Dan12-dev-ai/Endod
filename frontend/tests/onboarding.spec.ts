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

/** Answer the first four steps (name, goals, sex, age), arriving at the card step. */
async function answerUpToCard(page: Page, { open = true, age = '41–60' } = {}) {
  if (open) await page.goto('/onboarding');
  await page.locator('#first-name').fill('Almaz');
  await page.locator('#last-name').fill('Bekele');
  await page.locator('#last-name').press('Enter');
  // Each step advances on its own after a short animation.
  await expect(page.getByText('Step 2 of 5')).toBeVisible();
  await page.locator('[data-purpose="step-looking-for"] button').first().click();
  await expect(page.getByText('Step 3 of 5')).toBeVisible();
  await page.locator('[data-purpose="step-sex"]').getByText('Female', { exact: true }).click();
  await expect(page.getByText('Step 4 of 5')).toBeVisible();
  await page.getByLabel(age).check({ force: true });
  await expect(page.getByText('Step 5 of 5')).toBeVisible();
}

test.describe('Onboarding', () => {
  test('with consent, the health card details are saved and shown on the card', async ({ page }) => {
    await newPatientSignedIn(page);
    await answerUpToCard(page, { age: '21–40' });

    const card = page.locator('[data-purpose="step-card"]');
    // The card questions wait for consent.
    await expect(card.locator('#blood-type')).toBeDisabled();
    await card.locator('[data-purpose="health-consent"] input').check();
    await card.locator('#blood-type').selectOption('O+');
    await card.locator('#allergies').fill('Penicillin, Latex');
    await card.locator('#emergency-name').fill('Tesfaye Bekele');
    await card.locator('#emergency-phone').fill('0911 223 344');
    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page).toHaveURL(/\/interview$/);

    const health = await (await page.request.get('/api/backend/users/me/health-profile')).json();
    expect(health.sex).toBe('female');
    expect(health.age_range).toBe('21-40');
    expect(health.blood_type).toBe('O+');
    expect(health.allergies).toEqual(['Penicillin', 'Latex']);
    expect(health.emergency_contact_name).toBe('Tesfaye Bekele');
    expect(health.emergency_contact_phone).toBe('+251911223344');

    // The Overview opens with the card, showing what was just entered.
    const home = page.locator('[data-purpose="home-card"]');
    await expect(home.locator('[data-purpose="full-name"]')).toHaveText('Almaz Bekele');
    await expect(home.locator('[data-purpose="blood-value"]')).toHaveText('O+');
    await expect(home.locator('[data-purpose="allergies-value"]')).toHaveText('Penicillin, Latex');
    await expect(home.locator('[data-purpose="emergency-value"]')).toContainText('Tesfaye Bekele');
    await expect(home.locator('[data-purpose="qr-code"]')).toBeVisible();
  });

  test('an invalid emergency phone is caught before anything is saved', async ({ page }) => {
    await newPatientSignedIn(page);
    await answerUpToCard(page);
    const card = page.locator('[data-purpose="step-card"]');
    await card.locator('[data-purpose="health-consent"] input').check();
    await card.locator('#emergency-phone').fill('12345');
    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page.locator('main').getByRole('alert')).toContainText('Ethiopian mobile number');
    await expect(page).toHaveURL(/\/onboarding/);
  });

  test('without consent, nothing health-related is stored and the card shows no details', async ({ page }) => {
    await newPatientSignedIn(page);
    await answerUpToCard(page);

    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page).toHaveURL(/\/interview$/);

    const consent = await (await page.request.get('/api/backend/users/me/consent')).json();
    expect(consent.treatment_processing).toBe(false);
    const profile = await (await page.request.get('/api/backend/users/me')).json();
    expect(profile.first_name).toBe('Almaz');
    const home = page.locator('[data-purpose="home-card"]');
    // Not recorded reads "—", never "none".
    await expect(home.locator('[data-purpose="allergies-value"]')).toHaveText('—');
    await expect(home.locator('[data-purpose="home-add-health-details"]')).toBeVisible();
  });
});

test.describe('Onboarding redirects', () => {
  test('an unfinished onboarding comes first, and a finished one is not shown again', async ({ page }) => {
    await newPatientSignedIn(page);
    await page.goto('/interview');
    await expect(page).toHaveURL(/\/onboarding$/);
    await page.goto('/health-card');
    await expect(page).toHaveURL(/\/onboarding\?next=%2Fhealth-card$/);

    await answerUpToCard(page);
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
    await answerUpToCard(page, { open: false });
    await page.locator('[data-purpose="finish-onboarding"]').click();
    await expect(page).toHaveURL(/\/health-card$/);
  });
});
