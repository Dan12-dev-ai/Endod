import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests',
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:3000',
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
  // Reuse the already-running `next dev` on :3000 if it is up; otherwise start one.
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000/interview',
    reuseExistingServer: true,
    timeout: 90_000,
  },
});
