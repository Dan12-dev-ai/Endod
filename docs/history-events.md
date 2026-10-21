# Patient history, follow-ups and queues: the contract between the hospital service and Endod

Both systems already exchange events over Redis Streams with an outbox/inbox
(`endod:hospital` = hospital -> platform, `endod:patient` = platform -> hospital,
consumer groups `patient-platform` / `hospital-service`, envelope fields
`id, type, source, occurred_at, payload`, payload a JSON object). Everything
below adds to that; nothing existing changes. Handlers are idempotent
(events can arrive twice and out of order); an event that refers to
something not received yet raises `RetryLater`; a malformed one is
dead-lettered (`PermanentEventError`). Times are ISO-8601 with an offset
(UTC preferred); dates are `YYYY-MM-DD`.

`dedan_id` is the patient's Endod ID (`DE` + 6 digits). Record, visit, file,
queue-entry, request and share ids are 32-char lowercase hex (uuid4().hex).

## 1. Linking a hospital patient to an Endod account

Reception identifies the patient in the hospital portal by scanning the
Endod health card QR (`https://endod-health.com/card/<DEDAN_ID>?s=<SIGNATURE>`)
or by typing the Endod ID AND the phone number on the account. Nothing about
a patient is sent to Endod before the link is confirmed.

hospital -> platform `patient.link_requested`
`{"request_id", "hospital_id", "patient_id" (hospital's), "dedan_id", "card_signature": str|null, "phone": "+2519..."|null}`

Platform: the account exists and is active, and EITHER `card_signature`
verifies (`cards.verify_card`) OR `phone` equals the account's phone (both
normalised to E.164) and that phone is verified (the patient confirmed it
with an SMS code); an unverified phone never links. Replies:

platform -> hospital `patient.linked`
`{"request_id", "hospital_id", "patient_id", "dedan_id", "name", "phone": str|null}`
(`phone`: the account's verified phone, else null)

platform -> hospital `patient.link_refused`
`{"request_id", "hospital_id", "patient_id", "dedan_id", "reason": "not_found"|"not_verified"}`
(no data on refusal).

The hospital stores `dedan_id` on its patient only on `patient.linked`; the
patient gets an inbox item "<Hospital> linked your records to Endod". A
patient arriving through an Endod booking (`appointment.requested` carries
`patient.dedan_id`) is already identified: checking that booking in links
the hospital patient without a request (the platform links the account to
that hospital when the booking is made).

The platform accepts records and follow-ups about a patient only from a
hospital linked to them (a confirmed link, or an Endod booking there);
anything else is dead-lettered and never stored. A `queue.updated` for an
account not linked to that hospital is handled as a walk-in (its `dedan_id`
is ignored: nothing shows in the account, the text goes to `phone`).

## 2. Clinical records (hospital -> patient)

Categories (closed set): `diagnosis`, `prescription`, `lab_result`,
`imaging`, `visit_note`, `document`.

`details` by category (unknown keys ignored):
- diagnosis: `{condition, code (ICD-10, optional), status: active|resolved|chronic, notes}`
- prescription: `{items: [{drug, dose, route, frequency, duration, quantity, notes}], notes}`
- lab_result: `{items: [{test, value, unit, reference_range, flag: low|normal|high|critical|null}], specimen, notes}`
- imaging: `{modality, body_part, findings, impression}`
- visit_note: `{complaint, findings, plan, vitals: {bp, pulse, temp, weight, height, spo2}}`
- document: `{description}`

Files: PDF, JPEG, PNG or WebP, at most 20 MB each, at most 10 per record,
stored by the hospital service; the platform downloads its own copy.

hospital -> platform `record.published` (corrections reuse `record_id` with a
higher `version`; the platform keeps the highest version)
`{"record_id", "version", "hospital_id", "hospital_name", "dedan_id", "visit_id": hex|null,
  "category", "title", "details", "occurred_at", "recorded_by", "source": "portal"|"import",
  "files": [{"file_id", "filename", "content_type", "size", "sha256"}]}`

hospital -> platform `record.retracted` (entered in error)
`{"record_id", "hospital_id", "dedan_id", "reason"}`

File download (platform -> hospital API over the private `endod-bus`
network, never public): `GET {HOSPITAL_API_URL}/platform/records/{record_id}/files/{file_id}`
with header `X-Platform-Key`. The platform checks size and sha256 and stores
its copy; a failed download is retried by its worker (the record shows
meanwhile, its file marked as still arriving).

## 3. Visits and follow-ups

A visit groups records (`visit_id`) and may carry a follow-up set by the doctor.

hospital -> platform `visit.follow_up`
`{"visit_id", "hospital_id", "hospital_name", "dedan_id", "follow_up_on": "YYYY-MM-DD",
  "note": str|null, "doctor_name": str|null, "cancelled": bool}`

Platform: inbox item + SMS now, a FOLLOW_UP timeline event, an SMS reminder
the day before, and the follow-up appears in the app with "Book now" (the
patient may book an earlier date). `cancelled: true` removes it and its
reminder.

## 4. Queues ("people ahead of you")

One queue per doctor per day. Reception checks patients in (an Endod
booking, a linked patient, or a walk-in with a phone number); the doctor or
reception calls the next one. Each hospital sets how many people ahead
triggers the "get ready" SMS (`queue_notify_ahead`, default 3; 0 = off).

hospital -> platform `queue.updated`
`{"entry_id", "hospital_id", "hospital_name", "doctor_name", "day", "ticket": int,
  "status": "waiting"|"called"|"done"|"skipped"|"cancelled", "ahead": int,
  "dedan_id": str|null, "phone": str|null, "patient_name", "notify": "near"|"turn"|null, "seq": int}`

- Sent for every change affecting an entry linked to Endod (so the app shows
  the live position), and for anyone with a phone whenever `notify` is set.
- `"near"` is sent once per entry when `ahead` first reaches
  `queue_notify_ahead`; `"turn"` once when the entry is called. The platform
  sends exactly one SMS per notify (dedupe on entry_id + notify), to the
  account's phone if `dedan_id` is set and linked to the hospital (section
  1), else to `phone`. Walk-ins without an account get the SMS too (no
  account is created).
- `seq` increases per entry; the platform ignores an older `seq`.
- SMS language: the account's language; walk-ins get Amharic then English.

## 5. Sharing records with a hospital (platform -> hospital)

The patient picks records (from hospitals or self-reported) and a partner
hospital, optionally until a date.

platform -> hospital `records.shared`
`{"share_id", "hospital_id", "dedan_id", "patient_name", "expires_at": ISO|null,
  "records": [{"record_id", "origin" (hospital name or "Self-reported"), "category", "title",
               "details", "occurred_at", "recorded_by": str|null,
               "files": [{"file_id", "filename", "content_type", "size", "sha256"}]}]}`

platform -> hospital `records.unshared` `{"share_id", "hospital_id"}` (also
sent automatically at `expires_at`). The hospital deletes its copy. Shared
files are fetched by the hospital service on demand from
`GET {PLATFORM_API_URL}/internal/shares/{share_id}/files/{file_id}` with
`X-Platform-Key` over `endod-bus`; refused once unshared or expired. Records
are shared only with listed partner hospitals.

## 6. Imports from hospitals with their own system

The hospital portal accepts a FHIR R4 Bundle (JSON) or a CSV file (a
documented template). Each item becomes a record (`source: "import"`) for an
Endod-linked patient, matched by the hospital MRN or by identifier
`{"system": "https://endod-health.com/id", "value": "DE123456"}`. Mapping:
Condition -> diagnosis; MedicationRequest/MedicationStatement ->
prescription; Observation (laboratory) -> lab_result; DiagnosticReport
(imaging) -> imaging; DocumentReference (inline base64 attachment) ->
document. A preview lists what will be imported and what is skipped (and
why) before anything is saved. Imported records are published like any other.

## 7. Networking and configuration

- The hospital API joins `endod-bus` with alias `endod-hospital-api`; the
  platform's internal API (`internal-api`, serving only `/internal/...` and
  `/health`) joins it with alias `endod-platform-api`. Both keep their own
  networks; the platform's patient API is not on `endod-bus`.
- Platform env: `HOSPITAL_API_URL=http://endod-hospital-api:8000`,
  `PLATFORM_ADMIN_KEY` (same value as the hospital's), `RECORD_FILES_DIR`
  (a volume, default `/data/records`).
- Hospital env: `HOSPITAL_PLATFORM_API_URL=http://endod-platform-api:8000`,
  `HOSPITAL_FILES_DIR` (a volume, default `/data/files`).
- Internal endpoints (`/platform/...` on the hospital API, `/internal/...`
  on the platform API) require `X-Platform-Key` (constant-time compare), are
  never reachable through either public portal, and refuse when no key is set.
