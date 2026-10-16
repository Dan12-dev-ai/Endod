import fs from 'node:fs';
import path from 'node:path';
import { request, type FullConfig } from '@playwright/test';

// Registers a fresh test patient on the backend, signs in through the
// Next.js login route (which sets the httpOnly session cookie) and saves the
// session for the tests.

const BACKEND_URL = 'http://127.0.0.1:8011';
export const PASSWORD = 'E2eTestPassword1';

export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL ?? 'http://localhost:3100';
  const email = `e2e-${Date.now()}@example.com`;

  const backend = await request.newContext({ baseURL: BACKEND_URL });
  const registered = await backend.post('/auth/register', {
    data: { first_name: 'Test', last_name: 'Patient', email, password: PASSWORD, password_confirmation: PASSWORD },
  });
  if (!registered.ok()) throw new Error(`register failed: ${registered.status()} ${await registered.text()}`);
  await backend.dispose();

  const app = await request.newContext({ baseURL });
  const login = await app.post('/api/auth/login', { data: { identifier: email, password: PASSWORD } });
  if (!login.ok()) throw new Error(`login failed: ${login.status()} ${await login.text()}`);

  const statePath = path.join(__dirname, '.auth', 'patient.json');
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  await app.storageState({ path: statePath });
  // For the sign-in tests, which start signed out.
  fs.writeFileSync(path.join(path.dirname(statePath), 'credentials.json'), JSON.stringify({ email, password: PASSWORD }));
  await app.dispose();
}
