# Endod Health web app (Next.js)

The patient web app. It talks to the DEDAN backend (`../backend-v2`); see
[`../docs/api.md`](../docs/api.md) for the API.

## Run it

1. Start the backend (from the repo root): `make run-backend` (port 8001).
   Without `SMSETHIOPIA_API_KEY` the backend prints SMS codes to its console.
2. `cp .env.example .env.local` and adjust `DEDAN_API_URL` if needed.
3. `npm ci && npm run dev`, then open http://localhost:3000.

## How it talks to the backend

- The browser never holds a backend token. Sign-in routes in `app/api/auth/*`
  call the backend and keep the session in an httpOnly cookie
  (`dedan_session`); the phone verification step uses a short-lived httpOnly
  cookie too.
- `app/api/backend/[...path]` forwards the signed-in patient's own calls
  (`/users/me/...` only) with that cookie. Client code uses `app/lib/api.ts`:
  `api("users/me/appointments")`.
- `proxy.ts` sends signed-out visitors from private pages to `/login`.
- State-changing requests from another site are refused (Origin check, and
  the cookie is `SameSite=Lax`).

## Tests

`npx playwright test` starts the backend (offline AI mode, a throwaway
SQLite database) and `next dev` on port 3100, signs a test patient in
(`tests/global-setup.ts`) and runs the browser tests. It uses the repo's
`.venv`; set `E2E_PYTHON` to use another Python.
