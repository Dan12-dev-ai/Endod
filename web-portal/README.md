# DEDAN Health — web portal

Static HTML, no build step. Served by the FastAPI app itself
(`main_clinical.py` mounts `web-portal/` at `/`), so the browser talks to the API
on the same origin and there is no second dev server, no CORS, and no proxy.

## Running it

```bash
cd backend-v2
python3 -c "import secrets; print('REALTIME_TOKEN_SECRET=' + secrets.token_urlsafe(48))" >> .env
AI_PROVIDER_MODE=offline ../.venv/bin/python -m uvicorn main_clinical:app --host 0.0.0.0 --port 8001
```

Then open <http://localhost:8001/>. From the repository root, `make start-api`
does the same thing detached and `make check-portal` lints the markup.

`REALTIME_TOKEN_SECRET` is required. The token signer refuses to mint without one
rather than fall back to a hard-coded key, so signup and login fail loudly
without it.

## Pages

| File | What it does | Endpoints |
| --- | --- | --- |
| `index.html` | Public landing; becomes a live dashboard when signed in | `/auth/session`, `/users/me/timeline`, `/users/me/timeline/summary`, `/users/me/appointments` |
| `login.html` | Sign in with a DEDAN ID **or** email | `POST /auth/login` |
| `register.html` | Create an account and grant clinical consent | `POST /auth/register`, `PATCH /users/me/consent` |
| `live-discussion.html` | Consultation; text always answers, voice when available | `POST /api/analyze`, `POST /users/me/care/navigation` |
| `health-history.html` | Timeline, summary and health profile | `/users/me/timeline/**`, `/users/me/health-profile` |
| `appointments.html` | Book, reschedule, cancel | `/users/me/appointments/**` |
| `find-hospitals.html` | Care navigation and facility availability | `POST /users/me/care/facilities`, `/care/facilities/{id}/availability` |
| `settings.html` | Profile, preferences, consent, password, health profile | `PATCH /users/me`, `/preferences`, `/consent`, `/health-profile`, `POST /auth/password` |

## Shared modules (`assets/`)

Loaded by every page; each owns one concern so it cannot drift between pages.

- **`api.js`** — the session token, the API error shape (the backend answers
  `{"error", "error_code"}`, not FastAPI's `{"detail"}`), auth guards, toasts,
  form helpers and DOM builders. `DEDAN` is the global.
- **`shell.js`** — chrome for the signed-in pages: sidebar wiring, dead-link
  rewrites, `boot()`. `DEDAN_SHELL` is the global.
- **`theme.js`** — one Tailwind config. It replaced eight inlined copies of the
  same palette that had already drifted apart.
- **`icons.css`** — the Material Symbols class. The Google Fonts stylesheet
  definition lost a cascade race to the Tailwind base font for icons inserted at
  runtime, so they rendered as the literal word ("delete", "event").

Per-page scripts: `appointments.js`, `care.js`, `consult.js`, `history.js`,
`settings.js`.

## Rules this code follows

- **No `innerHTML`.** Every value rendered is patient-supplied or clinical text.
  `scripts/check-portal.py` fails the build on it; use `DEDAN.el` and
  `textContent`.
- **One auth path.** `DEDAN.requireSession()` revalidates against
  `/auth/session` rather than trusting `localStorage`, and redirects to sign-in
  on a 401. No page writes its own guard.
- **No invented clinical data.** Empty lists say so. Facility availability shows
  `availability_source` verbatim, so "not integrated" reads as a real gap rather
  than an empty state.
- **Consent is load-bearing.** Withdrawing it must stop health data being read,
  so the health sections re-render rather than showing something the server
  would now refuse.

## Verifying

```bash
make check-portal    # markup balance, links, unsafe patterns, inline JS syntax
make journey-test    # 50 checks in a real browser, whole patient journey
make screenshots      # every page to /tmp/opencode/shots
cd backend-v2 && ../.venv/bin/python -m pytest tests/ -q
```

`journey-test` fails on any console error or unexpected HTTP status, so a page
cannot look correct while being broken.
