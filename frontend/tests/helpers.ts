import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { expect, type APIRequestContext, type Page } from '@playwright/test';

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
  return (await response.json()).appointment as { appointment_id: string; scheduled_at: string };
}
