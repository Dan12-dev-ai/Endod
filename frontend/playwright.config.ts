import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { defineConfig } from '@playwright/test';

// Browser tests run the real stack: the backend (offline AI mode, a throwaway
// SQLite database) and `next dev` pointed at it. tests/global-setup.ts signs
// a test patient in and saves the session for every test.

const BACKEND_PORT = 8011;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
// The backend's Python: E2E_PYTHON, else the repo's virtualenv.
const python =
  process.env.E2E_PYTHON ??
  path.join('..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
// A fresh database per run. Set once in the main process (which also clears
// earlier runs' files); test workers inherit it, so they never pick another.
if (!process.env.E2E_DB) {
  for (const name of fs.readdirSync(os.tmpdir())) {
    if (name.startsWith('dedan-e2e-')) fs.rmSync(path.join(os.tmpdir(), name), { force: true, recursive: true });
  }
  process.env.E2E_DB = path.join(os.tmpdir(), `dedan-e2e-${Date.now()}.db`).replace(/\\/g, '/');
  // Hospital record files the backend downloads (cleared with the database above).
  process.env.E2E_RECORDS = path.join(os.tmpdir(), `dedan-e2e-records-${Date.now()}`);
}
const e2eDatabase = process.env.E2E_DB;
// Record files come from tests/fake-hospital.mjs, as the hospital API would serve them.
export const E2E_PLATFORM_KEY = 'e2e-platform-key';
export const FAKE_HOSPITAL_URL = 'http://127.0.0.1:8013';

export default defineConfig({
  testDir: 'tests',
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  // All specs share one test patient: one worker keeps them from seeing
  // each other's appointments and inbox items mid-test.
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  globalSetup: './tests/global-setup.ts',
  use: {
    baseURL: 'http://localhost:3100',
    storageState: 'tests/.auth/patient.json',
    headless: true,
    viewport: { width: 1280, height: 720 }, // desktop -> interview sidebar is visible
    // Drive the system Google Chrome via its `chrome` channel — no browser
    // download needed (cdn.playwright.dev download timed out in this env).
    channel: 'chrome',
    launchOptions: {
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
      ],
    },
    trace: 'on-first-retry',
    actionTimeout: 10_000,
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn main_clinical:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: path.join(__dirname, '..', 'backend-v2'),
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ENVIRONMENT: 'development',
        AI_PROVIDER_MODE: 'offline',
        REALTIME_TOKEN_SECRET: 'e2e-only-secret',
        DEDAN_DATABASE_URL: `sqlite:///${e2eDatabase}`,
        TRUST_PROXY_HEADERS: 'true',
        RATE_LIMIT_REQUESTS: '1000',
        // Payments go to tests/fake-chapa.mjs; video tokens are signed with a test secret.
        CHAPA_SECRET_KEY: 'CHASECK_TEST-e2e',
        CHAPA_BASE_URL: 'http://127.0.0.1:8012/v1',
        PUBLIC_APP_URL: 'http://localhost:3100',
        JITSI_APP_SECRET: 'e2e-jitsi-secret',
        SERVICE_FEE_FLAT_SANTIM: '500',
        SERVICE_FEE_PERCENT_BP: '0',
        HOSPITAL_API_URL: FAKE_HOSPITAL_URL,
        PLATFORM_ADMIN_KEY: E2E_PLATFORM_KEY,
        RECORD_FILES_DIR: process.env.E2E_RECORDS ?? '',
        // Signs the prescription QR codes History shows.
        RX_SIGNING_KEY: 'e2e-rx-signing-key',
      },
    },
    {
      command: 'node tests/fake-hospital.mjs',
      url: `${FAKE_HOSPITAL_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: { PLATFORM_ADMIN_KEY: E2E_PLATFORM_KEY },
    },
    {
      command: 'node tests/fake-chapa.mjs',
      url: 'http://127.0.0.1:8012/health',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: 'npm run dev -- -p 3100',
      url: 'http://localhost:3100/login',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { DEDAN_API_URL: BACKEND_URL },
    },
  ],
});

