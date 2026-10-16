# API Reference (backend-v2)

Reference for the FastAPI app in `backend-v2/main_clinical.py` and the routers
it mounts from `backend-v2/dedan_platform/api_*.py`. Everything here is derived
from the code on this branch; if the code and this page disagree, the code
wins and this page is the bug.

Contents: [Basics](#1-basics) · [Auth](#2-auth) ·
[Profile, preferences, consent](#3-profile-onboarding-preferences-consent) ·
[Health profile](#4-health-profile) · [Timeline](#5-timeline) ·
[Appointments](#6-appointments) · [Inbox](#7-inbox) ·
[Reminder log](#8-reminder-delivery-log) · [Medical records](#9-medical-records) ·
[Consultations and analysis](#10-consultations-and-anonymous-analysis) ·
[Images](#11-image-upload) · [Care navigation](#12-care-navigation) ·
[Handoff](#13-doctor-handoff) · [Live voice](#14-live-voice) ·
[Service endpoints](#15-service-endpoints) ·
[Screen to endpoint map](#16-frontend-screen--endpoint-map) ·
[Known gaps](#17-known-gaps)

---

## 1. Basics

### Base URL

| Environment | URL |
| --- | --- |
| Local (`make run-backend`, `.env.example` `PORT=8001`) | `http://localhost:8001` |
| Docker image (`Dockerfile` CMD) | port `8000` |

Suggested frontend config: `NEXT_PUBLIC_API_URL=http://localhost:8001` and
prefix every path below with it. The Next.js app does not read any such
variable yet.

OpenAPI UI at `/docs`, `/redoc`, `/openapi.json` exists only when `DEBUG=true`.

### Authentication

- Get a token from `POST /auth/register`, `POST /auth/login`,
  `POST /auth/phone/complete` or `POST /auth/password` (all return
  `access_token`).
- Send it in the **`Authorization`** header. Any of these forms work
  (`app.core.security.normalize_token`):
  `Authorization: <token>`, `Authorization: Bearer <token>`,
  `Authorization: DEDAN <token>`.
- Token format: `v1.<base64url JSON payload>.<HMAC-SHA256 signature>`;
  the payload has `sub` (DEDAN ID), `iat`, `exp`, `scope`. Treat it as opaque.
- Lifetime: `expires_in` seconds in the response (default 43200 = 12 h,
  `PORTAL_TOKEN_TTL`). No refresh endpoint; sign in again on 401.
- Scopes: `portal` (issued by the auth routes) and `realtime` are accepted by
  every authenticated route. `phone_verification` tokens (from
  `/auth/phone/verify`) are **not** session tokens; they are only accepted in
  the `verification_token` body field.
- A password change or a phone password reset invalidates every token issued
  before it.
- Every `/users/me/*` route resolves the user from the token. There are no
  routes that take a user id.

Auth failures from `current_user_id`:

| Status | `error` | Cause |
| --- | --- | --- |
| 401 | `Authentication required.` | Missing, malformed, forged, expired, wrong-scope or pre-password-change token |
| 404 | `Account not found.` | Token valid but account gone |
| 403 | `Account is deactivated.` | Account disabled |

### Error shape

`main_clinical.py` installs custom handlers, so errors **do not** use
FastAPI's default `{"detail": ...}`. Every JSON error looks like:

```json
{
  "error": "Appointment not found.",
  "error_code": "HTTP_400",
  "details": null,
  "timestamp": 1760600000.12
}
```

| Source | `error` | `error_code` | `details` |
| --- | --- | --- | --- |
| `HTTPException` with string detail | the detail string | `HTTP_<status>` | `null` |
| `HTTPException` with dict detail (image validation) | `"HTTP error"` | `HTTP_<status>` | the dict, e.g. `{message, errors, warnings}` |
| Pydantic validation (bad body/query) | `"Validation error"` | `VALIDATION_ERROR` (422) | FastAPI `errors()` list (`loc`, `msg`, `type`) |
| Unhandled exception | `"Internal server error"` | `INTERNAL_ERROR` (500) | `{"type": ...}` only if `DEBUG=true` |
| Rate limit | `"Rate limit exceeded"` | `RATE_LIMIT_EXCEEDED` (429) | `{limit, window_seconds, retry_after}` |
| Body too large | `"Request body too large"` | `PAYLOAD_TOO_LARGE` (413) | `{max_bytes}` |
| Unknown API path (`/api/`, `/auth/`, `/users/`, ...) | `"Not found"` | `HTTP_404` | `null` |

Show `error` to the user; branch on the HTTP status.

### Limits

| Limit | Value | Config |
| --- | --- | --- |
| Requests per client IP | 30 per 60 s by default (`.env.example` sets 240/60) | `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW` |
| Rate-limit exempt paths | `/api/health`, `/health`, `/docs`, `/redoc`, `/openapi.json` | |
| Client identity | socket IP; `X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true` | |
| Request body | 16 MB (or `MAX_IMAGE_SIZE_MB` if larger), returns 413 | |
| Password login lockout | 8 failures then 15 min lock (429) | `PASSWORD_LOCKOUT_ATTEMPTS`, `PASSWORD_LOCKOUT_MINUTES` |
| OTP | 5 codes/phone/hour, 60 s resend gap, 30 requests/client/hour, 5 wrong attempts per code, code valid 5 min | `OTP_*` |

The request limiter is in-process memory (resets on restart, not shared
between replicas). 429 responses from the limiter carry `Retry-After`.

### CORS

- Allowed origins: `CORS_ORIGINS` (comma-separated or JSON array). Default
  `http://localhost:3000, http://localhost:3001, http://127.0.0.1:3000`.
  `*` is refused in production.
- `allow_credentials=true`; allowed methods `GET, POST, PUT, PATCH, DELETE,
  OPTIONS`; allowed request headers `Authorization, X-API-Key, Content-Type,
  X-Correlation-ID`; exposed headers `X-Process-Time, Retry-After`.

### Optional headers

`X-Correlation-ID` is read by profile, appointment and care-navigation writes
and stored on audit and timeline rows.

---

## 2. Auth

All `/auth/*` routes except `/auth/session` and `/auth/password` are
unauthenticated.

### Session response (shared shape)

`register`, `login` and `phone/complete` return:

```json
{
  "access_token": "v1.eyJzdWIiOiJERTQ4MjczMSIs...",
  "token_type": "DEDAN",
  "expires_in": 43200,
  "dedan_user_id": "DE482731",
  "profile": { "...": "see GET /users/me" }
}
```

`phone/complete` also returns `"created": true|false`.

### Password policy (server side)

10 to 200 characters, must contain both upper and lower case letters, and
`password_confirmation` must match when sent. Violations: 400 with a message
such as `Password must be at least 10 characters.`

### `POST /auth/register` (201)

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `first_name` | string | yes | 1-60 |
| `last_name` | string | yes | 1-60 |
| `email` | string | yes | valid email, lowercased |
| `password` | string | yes | password policy |
| `password_confirmation` | string | yes | must equal `password` |
| `phone` | string | no | 6-32 chars of digits/`+ ().-`; Ethiopian mobiles stored as E.164. Not verified, so it cannot be used to sign in until linked via `POST /users/me/phone` |
| `locale` | string | no | default `en`, max 8 |
| `timezone` | string | no | default `UTC`, max 64 |
| `country_code` | string | no | default `ET`, 2 chars |

The DEDAN ID (`DE` + 6 digits) is assigned by the server and returned.
Errors: 400 (invalid email/phone, password policy), 409 (email already used).

### `POST /auth/login`

```json
{ "identifier": "DE482731", "password": "CorrectHorse9" }
```

`identifier` (1-254) is a DEDAN ID, a **verified** Ethiopian mobile number, or
an email. Errors: 401 `Incorrect DEDAN ID or password.` (same message for
unknown account and wrong password), 401 `This account has been deactivated.`,
429 when locked out.

### `GET /auth/session` (auth)

Returns `{"profile": {...}}`. Use it on app load to check that the stored token
is still valid.

### `POST /auth/password` (auth): change password

```json
{ "current_password": "...", "new_password": "...", "new_password_confirmation": "..." }
```

Response:

```json
{ "changed": true, "access_token": "v1....", "token_type": "DEDAN", "expires_in": 43200 }
```

**Replace the stored token with the new one**: the old token stops working.
Adds a `security` inbox item. Errors: 401 `Current password is incorrect.` or
`No password is set for this account.`, 400 password policy, 429 lockout.

### Phone OTP flow (sign-up, sign-in without password, password reset)

Only Ethiopian mobiles are accepted (`09xxxxxxxx`, `07xxxxxxxx`, `+2519...`,
`2519...`). In development without `SMSETHIOPIA_API_KEY` the code is printed
to the backend console instead of being sent.

1. **`POST /auth/phone/request-code`** (202)

   ```json
   { "phone": "0911 234 567" }
   ```

   Response: `{"expires_in": 300, "resend_after": 60}`. The answer is the same
   whether or not an account exists. Errors: 400 invalid phone, 429 too many
   codes (message says how long to wait), 503 SMS provider down.

2. **`POST /auth/phone/verify`**

   ```json
   { "phone": "0911 234 567", "code": "123456" }
   ```

   Response:

   ```json
   { "verification_token": "v1....", "expires_in": 900, "account_exists": true }
   ```

   `account_exists` tells the UI whether step 3 is a sign-up or a reset.
   Errors: 400 with `Incorrect code. Please try again.`, `The code has
   expired...`, `Too many incorrect attempts...`, `This code was already
   used...`, `No code was requested for this number...`.

3. **`POST /auth/phone/complete`**

   | Field | Type | Required | Notes |
   | --- | --- | --- | --- |
   | `verification_token` | string | yes | from step 2, single use, 15 min |
   | `password` | string | yes | password policy |
   | `password_confirmation` | string | no | checked if sent |
   | `first_name`, `last_name` | string | no | max 60; used only when creating |

   - No account for the phone: creates one (verified phone, timezone
     `Africa/Addis_Ababa`, country `ET`), `created: true`. Send the user to
     onboarding.
   - Account exists: this is a **password reset**. It sets the new password,
     signs out other sessions, adds a `security` inbox item, `created: false`.

   Returns the session response. Errors: 400 password policy (the
   verification is not used up), 401 expired/used verification, 403
   deactivated account, 409 race with another sign-up.

There is no email-based password reset. A user who registered by email resets
by phone only after linking a phone (`POST /users/me/phone`).

---

## 3. Profile, onboarding, preferences, consent

All require auth. `PATCH` bodies are partial JSON objects: send only the
fields you change. Unknown fields return 400
(`Unsupported profile fields: [...]`).

### `GET /users/me`

```json
{
  "internal_user_id": "6f1c...",
  "dedan_user_id": "DE482731",
  "created_at": "2026-10-01T08:00:00+00:00",
  "is_active": true,
  "display_name": "Abebe Kebede",
  "first_name": "Abebe", "middle_name": null, "last_name": "Kebede",
  "address_line": null, "city": "Addis Ababa", "region": null, "postal_code": null,
  "email": "abebe@example.com",
  "phone": "+251911234567", "phone_verified": true,
  "locale": "en", "timezone": "Africa/Addis_Ababa", "country_code": "ET",
  "preferences": {
    "language": "en", "voice_preference": null, "voice_gender": null,
    "theme": "system", "email_notifications": true, "sms_notifications": true,
    "push_notifications": true, "reminder_offsets": "604800,86400,3600",
    "preferred_contact_window": null,
    "onboarding_goals": ["symptoms", "appointments"],
    "care_search_radius_km": 15
  },
  "consent": {
    "treatment_processing": true, "analytics": false, "research": false,
    "marketing": false, "data_sharing_with_clinicians": false,
    "granted_at": "2026-10-01T08:01:00+00:00", "revoked_at": null,
    "policy_version": "1.0"
  }
}
```

No health data is included here.

### `PATCH /users/me`

Fields: `display_name` (1-120), `first_name`/`middle_name`/`last_name` (max
60), `email` (valid, unique; it cannot be removed while the account has no
verified phone, since it is then the only way to sign in), `phone` (6-32 chars;
a **verified** phone cannot be changed here, only through a code and
`POST /users/me/phone`; changing an unverified one keeps it unverified), `locale` (`en` or `am-ET` form), `timezone` (IANA name),
`country_code` (2 letters), `address_line` (200), `city` (100), `region`
(100), `postal_code` (20). Empty string or `null` clears an optional field.
Changing name parts recomputes `display_name` unless the user set a custom
one. Returns the full profile. Errors: 400 validation, 409 email in use.

### `GET /users/me/preferences` / `PATCH /users/me/preferences`

Returns (and PATCH returns) the `preferences` object only.

| Field | Accepted values |
| --- | --- |
| `language` | `en`, `am`, `om`, `ti`, `so`, `sw` |
| `voice_preference` | `warm`, `calm`, `clear` |
| `onboarding_goals` | array (or comma string) of `symptoms`, `hospitals`, `appointments`, `treatment`, `history` |
| `care_search_radius_km` | integer 1-200 or `null` |
| `reminder_offsets` | 1-5 seconds-before values (array or comma string), each up to 30 days; stored as e.g. `"86400,3600"`. Empty resets to the default `604800,86400,3600` |
| `email_notifications`, `sms_notifications`, `push_notifications` | boolean (JSON true/false only) |
| `theme` | `system`, `light`, `dark` |
| `voice_gender` | `female`, `male`, `neutral` or `null` |
| `preferred_contact_window` | text, max 64, or `null` |

### `GET /users/me/consent` / `PATCH /users/me/consent`

Fields (booleans): `treatment_processing`, `analytics`, `research`,
`marketing`, `data_sharing_with_clinicians`. Returns the `consent` object.
Values must be JSON booleans; anything else (including the string
`"false"`) is a 400.

`treatment_processing` gates the health profile, records writes, handoff
summaries and `POST /users/me/consultations` (403 without it).
`data_sharing_with_clinicians` gates `POST /users/me/handoff/share`.

### `POST /users/me/phone`: link a verified phone

```json
{ "verification_token": "<from /auth/phone/verify>" }
```

Marks the phone verified on the current account, so it can be used for
sign-in and phone password reset. Returns the full profile. Errors: 401
expired/used verification, 409 number already signs in to another account.

### Onboarding

There is no dedicated onboarding endpoint. After sign-up the onboarding
screens write:

1. `PATCH /users/me` with names.
2. `PATCH /users/me/preferences` with `onboarding_goals`.
3. `PATCH /users/me/consent` with `{"treatment_processing": true}` (needed
   before step 4).
4. `PATCH /users/me/health-profile` with `sex` and `age_range` (or
   `date_of_birth`).

---

## 4. Health profile

Requires auth **and** `consent.treatment_processing`; otherwise 403
`Consent to store health information is required.`

### `GET /users/me/health-profile`

```json
{
  "sex": "female",
  "date_of_birth": null,
  "age_range": "21-40",
  "age_years": 30,
  "allergies": ["Penicillin"],
  "medications": [],
  "conditions": ["Asthma"],
  "blood_type": "O+",
  "emergency_contact_name": "Kebede A.",
  "emergency_contact_phone": "+251911000000"
}
```

`age_years` is computed: from `date_of_birth` if set, otherwise the middle of
`age_range` (`81+` gives 86).

### `PATCH /users/me/health-profile`

| Field | Accepted values |
| --- | --- |
| `sex` | `female`, `male`, `other`, `undisclosed` (`prefer_not_to_say` is accepted as `undisclosed`) |
| `age_range` | `0-20`, `21-40`, `41-60`, `61-80`, `81+` (`1-20` and `81-100` are accepted and stored as `0-20` / `81+`) |
| `date_of_birth` | `YYYY-MM-DD`, not in the future, under 130 years ago |
| `blood_type` | `A+ A- B+ B- AB+ AB- O+ O-` |
| `allergies`, `medications`, `conditions` | array of strings (stored comma-joined, so do not put commas inside an item) |
| `emergency_contact_name` | max 120 |
| `emergency_contact_phone` | max 32 |

Returns the health profile.

---

## 5. Timeline

All require auth. Event types: `AI_CONVERSATION, APPOINTMENT, LAB_RESULT,
IMAGING, MEDICATION, PRESCRIPTION, CONSULTATION, FOLLOW_UP, DOCUMENT, OTHER,
ASSESSMENT, LIVE_DISCUSSION, SYMPTOM_REPORT, SAFETY_ALERT, CARE_NAVIGATION,
TREATMENT, NOTIFICATION`.

### `GET /users/me/timeline`

| Query | Type | Notes |
| --- | --- | --- |
| `limit` | int | 1-100, default 25 |
| `cursor` | string | `next_cursor` from the previous page |
| `event_type` | string | one of the types above, else 400 |
| `status` | string | e.g. `SCHEDULED`, `COMPLETED` |
| `date_from`, `date_to` | ISO datetime | filter on `occurred_at` |

```json
{
  "events": [
    {
      "event_id": "a1b2...",
      "event_type": "AI_CONVERSATION",
      "title": "AI consultation",
      "description": "Urgency: routine",
      "status": "COMPLETED",
      "source": "dedan",
      "occurred_at": "2026-10-15T09:00:00+00:00",
      "created_at": "2026-10-15T09:00:00+00:00",
      "conversation_id": "session-123",
      "metadata": { "response_id": "...", "urgency": "routine", "possible_explanations": [] }
    }
  ],
  "next_cursor": "MjAyNi0x...",
  "has_more": true,
  "limit": 25
}
```

Newest `occurred_at` first. Appointment events use the appointment time, so
future appointments sort above past events.

### `GET /users/me/timeline/summary`

`{"total": 12, "by_type": {"APPOINTMENT": 3, ...}, "upcoming": 2}`

### `GET /users/me/timeline/{event_id}`

One event, or 404 `Event not found.`

### `DELETE /users/me/timeline/{event_id}`

`{"deleted": true, "event_id": "..."}`. 404 if not found; 409
`Safety records cannot be deleted.` for system `SAFETY_ALERT` events.

---

## 6. Appointments

All require auth.

### Statuses and transitions

Statuses are upper case: `SCHEDULED`, `CONFIRMED`, `RESCHEDULED`,
`CANCELLED`, `COMPLETED`, `MISSED`.

| From | Allowed targets |
| --- | --- |
| `SCHEDULED` | `CONFIRMED`, `RESCHEDULED`, `CANCELLED`, `MISSED` |
| `CONFIRMED` | `RESCHEDULED`, `CANCELLED`, `COMPLETED`, `MISSED` |
| `RESCHEDULED` | `RESCHEDULED`, `CONFIRMED`, `CANCELLED`, `COMPLETED`, `MISSED` |
| `COMPLETED`, `CANCELLED`, `MISSED` | none (terminal) |

New bookings start as `SCHEDULED`. Moving to a terminal status cancels pending
reminders. `COMPLETED` also writes a `CONSULTATION` record (unverified) that
appears in medical records. `CONFIRMED` and `CANCELLED` add inbox items.

### Appointment object

```json
{
  "appointment_id": "0c9e...",
  "user_id": "6f1c...",
  "provider_id": null,
  "organization_id": null,
  "appointment_type": "consultation",
  "scheduled_at": "2026-10-20T07:30:00+00:00",
  "duration_minutes": 30,
  "status": "SCHEDULED",
  "location": "Tikur Anbessa Specialized Hospital, Shendera Road, Addis Ababa",
  "meeting_url": null,
  "visit_mode": "in_person",
  "department": "Cardiology",
  "time_window": "morning",
  "facility": {
    "id": "et-addis-black-lion", "name": "Tikur Anbessa Specialized Hospital",
    "address": "Shendera Road", "city": "Addis Ababa", "country": "ET",
    "phone": "+251 11 268 9600"
  },
  "provider_name": "Dr. Hana Tesfaye",
  "notes": "Chest tightness when climbing stairs",
  "timezone": "Africa/Addis_Ababa",
  "created_at": "2026-10-16T10:00:00+00:00",
  "updated_at": "2026-10-16T10:00:00+00:00"
}
```

`facility` is `null` without `facility_id`. `scheduled_at` is always returned
in UTC; render it in `timezone`.

### `GET /users/me/appointments`

Query: `upcoming_only` (bool, default false: future and not
`CANCELLED`/`COMPLETED`/`MISSED`), `limit` (1-200, default 50). Returns a
**JSON array** of appointment objects, latest first; with `upcoming_only`,
soonest first. The frontend's upcoming / past / cancelled
tabs filter this list client side.

### `POST /users/me/appointments` (201)

| Field | Type | Default | Rules |
| --- | --- | --- | --- |
| `scheduled_at` | ISO datetime | required | must include an offset (`2026-10-20T10:30:00+03:00`); not more than 5 min in the past |
| `timezone` | string | `UTC` | IANA name; used for `time_window` checks and reminder text. Send the user's zone, e.g. `Africa/Addis_Ababa` |
| `visit_mode` | string | `telehealth` if `meeting_url` set, else `in_person` | `in_person` or `telehealth` |
| `time_window` | string | `exact` | `exact`, `morning` (08-12), `afternoon` (12-17), `evening` (17-21); start time must fall in the window in `timezone` |
| `facility_id` | string | null | an `id` from the facility directory; not allowed for telehealth; unknown id gives 400 |
| `location` | string | from facility | max 200; filled as `name, address, city` when a facility is given |
| `meeting_url` | string | null | `https://` only, max 500, telehealth only |
| `department` | string | null | free text, max 120 |
| `provider_name` | string | null | free text, max 120 (no provider registry) |
| `appointment_type` | string | `consultation` | free text |
| `duration_minutes` | int | 30 | 5-480 |
| `notes` | string | null | |
| `provider_id`, `organization_id` | string | null | opaque ids; `provider_id` is used for double-booking checks |
| `reminder_offsets` | string | user preference, then `604800,86400,3600` | comma-separated seconds |

Response:

```json
{
  "appointment": { "...": "appointment object" },
  "reminder_policy_count": 2,
  "reminder_offsets": [3600, 86400],
  "reminders": {
    "queued": 4, "job_ids": ["..."], "skipped": [], "offsets": [3600, 86400],
    "channels": { "email": 2, "sms": 2 }
  }
}
```

Reminders are only queued; they are sent by the notification worker
(`NOTIFICATION_WORKER_ENABLED`). Errors (all 400): naive `scheduled_at`, past
time, unknown timezone, bad `time_window` / `visit_mode` / `meeting_url`,
unknown `facility_id`, telehealth with a facility, field too long,
`You already have an appointment at that time.`,
`That time is no longer available. Please choose another.`

### `GET /users/me/appointments/{appointment_id}`

Appointment object, or 404 `Appointment not found.`

### `PATCH /users/me/appointments/{appointment_id}/status`

```json
{ "status": "CANCELLED" }
```

Returns the appointment object plus `reminders_cancelled` (int). Errors: 400
for unknown status, illegal transition (`Cannot move an appointment from
CANCELLED to CONFIRMED.`) or `RESCHEDULED` (use the reschedule endpoint,
which takes the new time); 404 for a missing appointment.

### `POST /users/me/appointments/{appointment_id}/reschedule`

Body uses the same schema as create, but only `scheduled_at` (required) and
`time_window` are read; everything else is ignored. Minimal body:

```json
{ "scheduled_at": "2026-10-22T14:00:00+03:00", "time_window": "afternoon" }
```

Status becomes `RESCHEDULED`; old reminders are cancelled and new ones queued.
If `time_window` is omitted the old window is kept when the new time fits,
otherwise it becomes `exact`. Returns the appointment object plus
`reminders_cancelled` and `reminders` (same shape as on create). Errors: 400
(same validation as create, illegal transition from a terminal status), 404
not found.

---

## 7. Inbox

In-app notifications (the Notification screen). All require auth. Categories:
`appointments`, `records`, `messages`, `security`.

Written by the server for: appointment booked / moved / confirmed / cancelled
(`appointments`), password changed, password reset by phone, phone verified
(`security`). Nothing currently writes `records` or `messages` items.

### `GET /users/me/inbox`

| Query | Type | Notes |
| --- | --- | --- |
| `category` | string | one of the categories, else 400 |
| `unread_only` | bool | default false |
| `limit` | int | 1-100, default 50 |
| `cursor` | string | `next_cursor` from the previous page (max 200 chars); invalid gives 400 |

```json
{
  "items": [
    {
      "id": "c3d4...",
      "category": "appointments",
      "kind": "appointment_booked",
      "title": "Appointment booked",
      "body": "Monday 20 October 2026, 10:30 (Africa/Addis_Ababa) at Tikur Anbessa Specialized Hospital, Shendera Road, Addis Ababa.",
      "link": { "screen": "appointment", "id": "0c9e..." },
      "created_at": "2026-10-16T10:00:00+00:00",
      "read": false
    }
  ],
  "next_cursor": null,
  "unread_count": 3,
  "unread_by_category": { "appointments": 2, "records": 0, "messages": 0, "security": 1 }
}
```

Paging: newest first. Pass `next_cursor` back as `cursor` until it is
`null`. Dismissed items are never returned. Unread counts cover all items, not
just the page. `link` is `null` for items with no target.

`kind` values: `appointment_booked`, `appointment_rescheduled`,
`appointment_confirmed`, `appointment_cancelled`, `password_changed`,
`password_reset`, `phone_verified`.

### `POST /users/me/inbox/read-all`

Query `category` optional. Returns `{"marked_read": 3}`.

### `POST /users/me/inbox/{item_id}/read`

`{"id": "...", "read": true}`; 404 `Item not found.`

### `DELETE /users/me/inbox/{item_id}`

Dismisses (soft delete, also marks read). `{"id": "...", "dismissed": true}`;
404 if not found or already dismissed.

---

## 8. Reminder delivery log

Status of queued email/SMS reminders (not the inbox). Auth required.

### `GET /users/me/notifications`

Query: `limit` (1-100, default 25), `status` (`PENDING`, `PROCESSING`,
`SENT`, `FAILED`, `RETRYING`, `CANCELLED`, `SKIPPED`; anything else is 400).

```json
{
  "notifications": [
    {
      "notification_id": "...", "appointment_id": "...", "channel": "email",
      "template": "appointment_reminder", "status": "PENDING",
      "scheduled_for": "2026-10-19T07:30:00+00:00", "sent_at": null, "attempts": 0,
      "created_at": "...", "updated_at": "..."
    }
  ],
  "count": 1,
  "summary": { "PENDING": 1, "PROCESSING": 0, "SENT": 0, "FAILED": 0, "RETRYING": 0, "CANCELLED": 0, "SKIPPED": 0 }
}
```

### `GET /users/me/notifications/{notification_id}`

One item, or 404.

---

## 9. Medical records

Past visits, stored as `CONSULTATION` timeline events. Auth required.

### `GET /users/me/records`

Query `limit` (1-200, default 100).

```json
{
  "records": [
    {
      "record_id": "e5f6...",
      "occurred_at": "2026-09-02T09:00:00+00:00",
      "facility_name": "St. Peter's Hospital",
      "department": "General Medicine",
      "diagnosis": "Seasonal allergy",
      "medications": [{ "name": "Cetirizine", "dose": "10 mg daily" }],
      "follow_up_days": 14,
      "follow_up_due": "2026-09-16T09:00:00+00:00",
      "follow_up_note": "Return if wheezing",
      "verified": false,
      "source": "patient"
    }
  ],
  "summary": {
    "total_visits": 1, "verified_records": 0, "facilities_visited": 1,
    "medications_used": 1, "active_follow_ups": 0
  }
}
```

`verified` is true only for `source` `clinician` or `facility`; nothing in the
API writes those yet. Patient entries (`source: "patient"`) and appointments
marked `COMPLETED` (`source: "appointment"`) are unverified. Records can be
deleted through `DELETE /users/me/timeline/{record_id}`.

### `POST /users/me/records` (201)

Requires `treatment_processing` consent (403).

| Field | Type | Rules |
| --- | --- | --- |
| `occurred_at` | ISO datetime | required, with offset; after 1900, not in the future |
| `facility_name` | string | required, max 160 |
| `department` | string | max 120 |
| `diagnosis` | string | max 300 |
| `medications` | array of `"name"` or `{name, dose}` | max 20; name max 120, dose max 80 |
| `follow_up_days` | int | 1-730 |
| `follow_up_note` | string | max 500 |

Returns one record object. 400 on validation errors.

---

## 10. Consultations and anonymous analysis

Both run the same pipeline (AI provider or deterministic offline rules, then
the safety validator) and return the same clinical document.

### `POST /users/me/consultations` (auth)

For signed-in patients. Age, sex, location, allergies, medications,
conditions and language come from the stored profile. Unknown fields are
rejected (422), so do not send `patient_age` etc.

| Field | Type | Rules |
| --- | --- | --- |
| `symptom_description` | string | required, 10-3000 |
| `symptom_duration` | string | max 200 |
| `symptom_severity` | string | `mild`, `moderate`, `severe` |
| `image_ids` | string[] | max 10, ids from `/api/images/upload` |
| `voice_transcript` | string | max 5000 |
| `session_id` | string | max 64; reuse it to keep one conversation |
| `conversation_history` | `{role, content}`[] | max 50 turns; `role` `user`/`patient`/`assistant` |
| `pregnant` | bool | default false |

Preconditions: 403 without `treatment_processing` consent; 400
`Add your age (date of birth or age range) to your health profile first.`
when the health profile has no age. Profile languages other than `en`, `sw`,
`am` are analysed in English.

Side effects: adds an `AI_CONVERSATION` timeline event, plus a
`SAFETY_ALERT` event when urgency is `emergency`.

### `POST /api/analyze` (no auth)

Anonymous version; the caller supplies the patient details.

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `patient_age` | int | yes | 0-150 |
| `patient_sex` | string | yes | `male`, `female`, `other` |
| `symptom_description` | string | yes | 10-3000 |
| `consent` | bool | no (default true) | `false` gives 400 |
| `patient_location` | string | no | |
| `patient_pregnant` | bool | no | |
| `patient_chronic_conditions`, `patient_medications`, `patient_allergies` | string[] | no | |
| `patient_language` | string | no | default `en` |
| `symptom_duration` | string | no | |
| `symptom_severity` | string | no | `mild`, `moderate`, `severe` |
| `image_ids` | string[] | no | |
| `image_data_list` | string[] | no | raw base64 or `data:` URLs |
| `voice_transcript`, `session_id` | string | no | |
| `conversation_history` | `{role, content}`[] | no | |

Nothing is stored for `/api/analyze`.

### Response (both endpoints)

Top-level keys: `response_id`, `session_id`, `timestamp`, `health_summary`,
`safety`, `possible_explanations`, `uncertainty`, `treatment_education`,
`medication_information`, `visual_education`, `follow_up`, `sources`,
`professional_review`, `provider`, `model`, `confidence_score`, `disclaimer`.

```json
{
  "response_id": "ddafadca-46ec-444e-8052-5c359b398184",
  "session_id": "333d5277-896f-47de-a6f4-799b7813b5e8",
  "timestamp": "2026-10-16T09:33:31.139447",
  "health_summary": {
    "symptoms": ["mild headache for two days"], "duration": "2 days", "severity": 3,
    "relevant_history": [], "images_provided": false,
    "other_information": { "ai_confidence": 0.55, "processing_time_ms": 2 }
  },
  "safety": {
    "urgency": "routine",
    "red_flags": [],
    "requires_immediate_care": false,
    "emergency_message": null,
    "recommended_action": "Schedule a routine appointment with a clinician, or use self-care and re-check if symptoms worsen.",
    "professional_review_required": true
  },
  "possible_explanations": [
    {
      "label": "Undetermined - requires professional evaluation",
      "why_it_fits": "...", "what_does_not_fit": "...",
      "evidence_level": "theoretical", "requires_more_info": ["Physical examination"]
    }
  ],
  "uncertainty": { "message": "...", "level": "moderate", "missing_information": ["Temperature"] },
  "treatment_education": [],
  "medication_information": [],
  "visual_education": [],
  "follow_up": {},
  "sources": [],
  "professional_review": true,
  "provider": "offline",
  "model": "offline-rules-v1",
  "confidence_score": 0.55,
  "disclaimer": "This is AI-generated health information, not a diagnosis. Always consult a qualified healthcare professional."
}
```

- `safety.urgency`: `routine`, `soon`, `urgent`, `emergency`. When
  `requires_immediate_care` is true, show `emergency_message` prominently.
- `medication_information[]` items have `medication_name`,
  `medication_class`, `general_purpose`, `common_warnings`,
  `contraindication_categories`, `potential_interactions`,
  `questions_to_ask`, `package_check_items`, `is_educational_only` (always
  true). Never present them as a prescription.
- If the AI provider fails, the offline rules answer instead (the request
  does not fail).

Errors: 400 consent, 403/400 preconditions (consultations), 422 validation,
500 `Analysis failed. Reference: <request id>`, 503 providers not initialised.

---

## 11. Image upload

No auth. Images live on local disk with an in-memory index, expire after
`IMAGE_TTL_HOURS` (default 24) and are lost on restart.

### `POST /api/images/upload`

`multipart/form-data` with `file` (required) and `session_id` (optional).

```json
{
  "image_id": "0f8c...",
  "filename": "photo.png",
  "size_bytes": 184320,
  "mime_type": "image/png",
  "quality_score": 0.92,
  "is_usable": true,
  "upload_timestamp": "2026-10-16T09:33:31.139447",
  "preview_url": "/api/images/0f8c.../preview"
}
```

Checks: type from magic bytes (`ALLOWED_IMAGE_TYPES`, default jpeg, png,
webp, heic), max `MAX_IMAGE_SIZE_MB` (10), max 10000 px per side and 40 MP,
minimum 224x224 and a basic quality score. Failure: 400 with
`details: {message, errors, warnings}`.

### `POST /api/images/upload-base64`

```json
{ "image_data": "<base64 or data: URL>", "filename": "image.jpg", "session_id": "..." }
```

Same response. `image_data` may be plain base64 or a `data:...;base64,` URL;
invalid base64 is a 400.

### `GET /api/images/{image_id}`

Stored metadata (`image_id`, `original_filename`, `mime_type`, `size`,
`dimensions`, `quality`, `upload_timestamp`, `expires_at`). Storage
internals and the session id are not returned.
404 if unknown.

### `GET /api/images/{image_id}/preview`

`{"image_id": "...", "content": "<base64>", "mime_type": "image/png"}`.

### `DELETE /api/images/{image_id}`

`{"message": "Image deleted", "image_id": "..."}`; 404 if unknown.

---

## 12. Care navigation

All under `/users/me`. Facility data comes from a hard-coded curated
directory (`care_navigation.DIRECTORY`, version `2024-06-01`).

Department values: `general_medicine`, `emergency`, `maternal_health`,
`pediatrics`, `cardiology`, `respiratory`.

### Facility object

```json
{
  "id": "et-addis-black-lion",
  "name": "Tikur Anbessa Specialized Hospital",
  "kind": "hospital",
  "address": "Shendera Road",
  "city": "Addis Ababa",
  "country": "ET",
  "latitude": 9.0289,
  "longitude": 38.7603,
  "departments": ["emergency", "general_medicine", "cardiology", "respiratory"],
  "phone": "+251 11 268 9600",
  "emergency": true,
  "open_hours": "24 hours",
  "website": null,
  "verified": true,
  "source": "dedan-curated-directory",
  "notes": "Largest medical referral centre in Ethiopia.",
  "availability_source": "not_integrated"
}
```

`open_hours: null` means unknown, not closed. `website` is always `null`
today.

### `GET /users/me/care/facilities` (auth): browse

The Booking screen's hospital list.

| Query | Type | Notes |
| --- | --- | --- |
| `country` | string | 2 letters, e.g. `ET` |
| `city` | string | exact match, case-insensitive, max 100 |
| `department` | string | one of the department values, else 400 |
| `emergency_only` | bool | default false |
| `q` | string | substring of name, city or address, max 120 |
| `latitude`, `longitude` | float | send both or neither (400) |
| `sort` | string | `name` (default) or `distance` (needs coordinates, else 400) |
| `limit` | int | 1-100, default 50 |

```json
{
  "facilities": [ { "...": "facility object", "distance_km": 2.4 } ],
  "total": 2,
  "location_used": true,
  "directory_version": "2024-06-01",
  "departments": ["general_medicine", "emergency", "maternal_health", "pediatrics", "cardiology", "respiratory"]
}
```

`distance_km` is `null` without coordinates.

### `POST /users/me/care/facilities` (auth): ranked search

Ranks facilities for a consultation (clinical fit 72 %, distance 28 %).

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `symptoms` | string[] | `[]` | max 40; keywords select departments |
| `urgency` | string | `routine` | `urgent`/`emergency` require an emergency department |
| `is_emergency` | bool | false | |
| `language` | string | `en` | |
| `latitude`, `longitude` | float | null | **ignored unless `location_granted` is true** |
| `location_granted` | bool | false | |
| `query` | string | null | max 120; filters by name/city/address before `limit` is applied. If nothing matches, the unfiltered list is returned and `query_matched` is `false` |
| `country` | string | null | ISO code, e.g. `ET`; all countries when omitted |
| `limit` | int | 5 | 1-20 |

With coordinates, facilities more than 150 km away are dropped.

```json
{
  "required_departments": ["emergency", "cardiology"],
  "location_used": false,
  "facilities": [
    {
      "...": "facility object",
      "distance_km": null,
      "matched_departments": ["emergency", "cardiology"],
      "relevance_score": 0.97,
      "reasons": ["Has a 24-hour emergency service", "Offers emergency/cardiology"]
    }
  ],
  "directory_version": "2024-06-01",
  "directory_source": "dedan-curated-directory",
  "directory_source_note": "Curated directory of named institutions maintained by DEDAN. ...",
  "note": "No location was shared, so facilities are ranked by clinical fit only.",
  "urgency": "urgent",
  "is_emergency": false
}
```

### `GET /users/me/care/facilities/{facility_id}` (auth)

Facility object, or 404 `Facility not found.`

### `GET /users/me/care/facilities/{facility_id}/availability` (auth)

Query `on_date` (string, echoed back, not validated). No availability feed is
integrated, so `slots` is always empty:

```json
{
  "facility_id": "et-addis-stpeter",
  "on_date": "2026-10-20",
  "available": false,
  "slots": [],
  "source": "no_availability_provider_configured",
  "confidence": "unknown",
  "note": "St. Peter's Hospital does not yet publish live appointment availability to DEDAN. Call the facility ..."
}
```

24-hour emergency facilities instead return `source: "opening_hours"`,
`confidence: "opening_hours_only"`, `walk_in_available: true`. Let the
user pick any time; the booking API does not check slots.

### `POST /users/me/care/navigation` (auth, 201)

Records that the patient was routed to care (timeline event).

| Field | Type | Notes |
| --- | --- | --- |
| `facility_id`, `facility_name`, `appointment_id` | string | optional |
| `symptoms` | string[] | max 40 (only the count is stored) |
| `urgency` | string | default `routine` |
| `is_emergency` | bool | true writes `SAFETY_ALERT` (status `SCHEDULED`), false writes `CARE_NAVIGATION` (`COMPLETED`) |
| `reason` | string | max 200 |

Returns the created timeline event.

---

## 13. Doctor handoff

Lets the patient review a clinician-facing summary, then share it.

### `POST /users/me/handoff/summary` (auth, 201)

Requires `treatment_processing` consent.

| Field | Type | Limits |
| --- | --- | --- |
| `main_concern` | string | max 400 |
| `patient_statements` | string[] | max 40 |
| `allergies`, `medications` | string[] | max 40 each |
| `relevant_context`, `safety_findings`, `possible_causes`, `clinician_questions` | string[] | max 20 each |
| `onset` | string | max 120 |
| `severity` | string | max 40 |
| `language` | string | `en` (default) or `am` for `patient_explanation` |

```json
{
  "handoff_id": "9b1f...",
  "summary": {
    "main_concern": "...", "reported_symptoms": [], "onset": "...", "duration": "...",
    "severity": "...", "associated_symptoms": [], "allergies": ["not stated"],
    "medications": ["not stated"], "relevant_context": [], "safety_findings": [],
    "possible_causes": [], "questions_for_clinician": [],
    "is_ai_generated": true, "is_diagnosis": false, "disclaimer": "..."
  },
  "fingerprint": "3e7a...",
  "approved_at": "2026-10-16T10:00:00+00:00",
  "is_shared": false,
  "shared_at": null,
  "disclaimer": "...",
  "patient_explanation": {
    "language": "en",
    "sections": [{ "heading": "How severe it is", "body": "..." }],
    "questions": ["..."], "default_questions": ["..."], "disclaimer": "..."
  }
}
```

Nothing is sent to a clinician at this point.

### `POST /users/me/handoff/share` (auth)

```json
{ "handoff_id": "9b1f...", "fingerprint": "3e7a..." }
```

Requires `data_sharing_with_clinicians` consent (403). Echo back the
`fingerprint` the patient saw. Returns
`{"handoff_id", "is_shared": true, "shared_at", "disclaimer"}`. Errors: 400
empty or mismatched fingerprint, 404 handoff not found. "Sharing" only writes
a timeline event; no clinician system receives anything yet.

---

## 14. Live voice

The realtime routers (`realtime.discussion`, `live_voice`, `realtime_api`)
are imported inside a `try` and **are not present on this branch**, so
nothing is mounted at `/ws/live-voice`. Only the capability probe exists.

### `GET /dedan/v2/live-voice/capabilities` (no auth)

```json
{
  "available": false,
  "endpoint": "/ws/live-voice",
  "transport": "websocket",
  "native_duplex": false,
  "streaming": false,
  "barge_in": false,
  "text_fallback": true,
  "languages": ["en", "am", "om", "ti", "so", "sw"],
  "input_sample_rate": 16000,
  "output_sample_rate": 24000,
  "provider": null,
  "providers_registered": [],
  "detail": "Live voice is not installed on this deployment."
}
```

Use it to hide the voice UI when `available` is false. The AI interview
screen should use `POST /users/me/consultations` (text, optional
`voice_transcript`).

---

## 15. Service endpoints

| Method + path | Auth | Response |
| --- | --- | --- |
| `GET /health` | no | `{"status": "healthy", "service": "DEDAN Health Clinical API"}` |
| `GET /api/health` | no | `{status, timestamp, version, components: {api, image_service, safety_validator}, ai_providers: {live_mode, text_ready, vision_ready, multimodal_ready}}` |
| `GET /api/providers` | no | `{providers: [{slot, provider, model, credential_configured}], primary, fallback_order, offline_mode, health, registry}` |

`GET /` serves the static `web-portal/` (if present), not JSON.

---

## 16. Frontend screen → endpoint map

Screens are the `activeNav` views in `frontend/app/interview/page.tsx`, plus
the auth and onboarding pages.

| Screen | Endpoints |
| --- | --- |
| Sign up (`app/signup`, `app/verify-otp`, `app/set-password`) | `POST /auth/phone/request-code` → `POST /auth/phone/verify` → `POST /auth/phone/complete` (with `first_name`/`last_name`). Email sign-up: `POST /auth/register` |
| Login (`app/login`) | `POST /auth/login` (phone, DEDAN ID or email as `identifier`); on load `GET /auth/session` |
| Forgot password | phone OTP flow; `complete` returns `created: false` |
| Onboarding (`app/onboarding`) | `PATCH /users/me`, `PATCH /users/me/preferences` (`onboarding_goals`), `PATCH /users/me/consent`, `PATCH /users/me/health-profile` (`sex`, `age_range`) |
| Live Discussion / AI interview (`live`) | `GET /dedan/v2/live-voice/capabilities`; `POST /api/images/upload`; `POST /users/me/consultations`; then `POST /users/me/care/facilities` (ranked), `POST /users/me/care/navigation`, `POST /users/me/handoff/summary` / `share` |
| Booking / hospital directory (`booking`) | `GET /users/me/care/facilities` (filters: `department`, `q`, `sort=distance` with coordinates); `GET /users/me/care/facilities/{id}`; `GET .../availability`; book with `POST /users/me/appointments` (`facility_id`, `department`, `time_window`, `visit_mode`, `notes`) |
| Appointments (`appointment`) | `GET /users/me/appointments` (split into upcoming/past/cancelled client side); book `POST /users/me/appointments` (`provider_name`, `visit_mode`); reschedule `POST .../{id}/reschedule`; cancel/confirm `PATCH .../{id}/status` |
| Medical Record (`followup`) | `GET /users/me/records`; `POST /users/me/records`; `GET /users/me/timeline` for history |
| Notification (`message`) | `GET /users/me/inbox?category=...&cursor=...`; `POST /users/me/inbox/read-all`; `POST /users/me/inbox/{id}/read`; `DELETE /users/me/inbox/{id}`; follow `link.screen`/`link.id` (`appointment`) |
| Setting (`setting`) | `GET`/`PATCH /users/me`; `GET`/`PATCH /users/me/preferences` (`care_search_radius_km`, notification toggles); `POST /auth/password`; `POST /users/me/phone`; health card fields via `GET`/`PATCH /users/me/health-profile` (`blood_type`, `allergies`, `emergency_contact_*`); `GET`/`PATCH /users/me/consent` |

Value mapping the UI needs:

| UI value | API value |
| --- | --- |
| "Exact Arrival Time" / "Morning (08:00 - 12:00)" / "Afternoon" / "Evening" | `time_window`: `exact` / `morning` / `afternoon` / `evening` |
| "in-person" / "telehealth" | `visit_mode`: `in_person` / `telehealth` |
| Specialty filter (Cardiology, General Medicine, Emergency & Trauma, Pediatrics) | `department`: `cardiology`, `general_medicine`, `emergency`, `pediatrics` |
| Onboarding age "1–20" ... "81–100" | `age_range`: send the label as is (hyphen or en dash; normalised to `0-20` ... `81+`) |
| Onboarding goals (symptoms, hospitals, ...) | `onboarding_goals` ids are identical |

`frontend/app/api/auth/*` (`send-otp`, `resend-otp`, `verify-otp`,
`set-password`, `login`) do **not** proxy to the backend. They keep OTPs and
passwords in the Next.js process (`app/lib/otp-store`, `app/lib/user-store`)
and send SMS directly. Replace them with the backend calls above
(`resend-otp` is just `request-code` again after `resend_after` seconds).

---

## 17. Known gaps

- **Facility directory**: 6 hard-coded entries, only 2 in Ethiopia
  (`et-addis-black-lion`, `et-addis-stpeter`); the other 4 are in Kenya. It
  needs a real, maintained Ethiopian data source.
- **No ratings, wait times or websites.** The booking UI's rating, wait and
  website fields have no backend data (`website` is always `null`).
- **No provider registry.** `provider_name` is free text; `provider_id` is an
  unchecked opaque string. There is no doctor list endpoint.
- **Availability not integrated.** `/availability` never returns slots and
  booking does not check any; "Slots Today" style badges cannot be backed.
- No email password reset; no token refresh; no account deletion endpoint.
- Live voice is not mounted on this branch.
- Inbox categories `records` and `messages` have no producers.
- Image endpoints have no auth or ownership (an image id acts as the access
  key, as `/api/analyze` is anonymous), and images are lost on restart.
- Frontend password rule (8+ chars, upper, number, symbol) differs from the
  backend (10+ chars, upper and lower).
