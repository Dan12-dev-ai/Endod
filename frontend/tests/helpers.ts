import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { expect, type APIRequestContext, type Locator, type Page } from './fixtures';

/** The test partner hospital listed by tests/seed.py. */
export const PARTNER_ID = 'e2e0'.repeat(8);

/** Run tests/seed.py against the test backend's database (see that file). */
export function seed(...args: string[]) {
  const python =
    process.env.E2E_PYTHON ??
    path.resolve(__dirname, '..', '..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  execFileSync(python, [path.join(__dirname, 'seed.py'), ...args], {
    cwd: path.join(__dirname, '..', '..', 'backend-v2'),
    env: {
      ...process.env,
      DEDAN_DATABASE_URL: `sqlite:///${process.env.E2E_DB}`,
      ENVIRONMENT: 'development',
      // Where the backend keeps record files, and the fake hospital API they come from.
      RECORD_FILES_DIR: process.env.E2E_RECORDS ?? '',
      HOSPITAL_API_URL: 'http://127.0.0.1:8013',
      PLATFORM_ADMIN_KEY: 'e2e-platform-key',
      // Refunds and expired holds talk to tests/fake-chapa.mjs, as the backend does.
      CHAPA_SECRET_KEY: 'CHASECK_TEST-e2e',
      CHAPA_BASE_URL: 'http://127.0.0.1:8012/v1',
    },
    stdio: 'inherit',
  });
}

/** Open a sidebar section of /interview. */
export async function openSection(page: Page, link: string, view: string) {
  await page.goto('/interview', { waitUntil: 'networkidle' });
  await page.locator('aside').getByRole('link', { name: link }).click();
  await expect(page.locator(`[data-purpose="${view}"]`)).toBeVisible();
}

/** A local date (YYYY-MM-DD) `days` from today, and an ISO instant at hh:mm on it. */
export function futureSlot(days: number, hour = 10, minute = 30) {
  const at = new Date();
  at.setDate(at.getDate() + days);
  at.setHours(hour, minute, 0, 0);
  const pad = (n: number) => String(n).padStart(2, '0');
  return {
    date: `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`,
    time: `${pad(hour)}:${pad(minute)}`,
    iso: at.toISOString(),
  };
}

/** Book an appointment for the signed-in test patient through the app's API proxy. */
export async function createAppointment(request: APIRequestContext, body: Record<string, unknown>) {
  const response = await request.post('/api/backend/users/me/appointments', { data: body });
  expect(response.status(), await response.text()).toBe(201);
  const json = await response.json();
  return {
    ...(json.appointment as { appointment_id: string; scheduled_at: string }),
    payment: (json.payment ?? null) as { checkout_url: string; tx_ref: string } | null,
  };
}

/**
 * Pay a partner booking on tests/fake-chapa.mjs (its checkout page marks it
 * paid), then come back as the app does: the backend checks with Chapa.
 */
export async function payBooking(request: APIRequestContext, payment: { checkout_url: string; tx_ref: string }) {
  const paid = await request.get(payment.checkout_url, { maxRedirects: 0 });
  expect(paid.status()).toBe(302);
  const back = await request.get(`/api/backend/users/me/booking-payments/${payment.tx_ref}`);
  expect(back.status(), await back.text()).toBe(200);
  expect((await back.json()).status).toBe('paid');
}

/**
 * Pick an option in a Radix select (components/ui/select.tsx): open the
 * combobox trigger, choose the option by its visible name, and check the
 * trigger now shows it. `trigger` is a data-purpose value or a locator.
 */
export async function chooseOption(page: Page, trigger: string | Locator, label: string) {
  const box = typeof trigger === 'string' ? page.locator(`[data-purpose="${trigger}"]`) : trigger;
  await expect(box).toHaveAttribute('role', 'combobox');
  await box.click();
  // While open, Radix hides the rest of the page (the trigger too) from the
  // accessibility tree, so wait for the listbox rather than the trigger.
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.getByRole('option', { name: label, exact: true }).click();
  await expect(box).toHaveAttribute('aria-expanded', 'false');
  await expect(box).toHaveText(label);
}
