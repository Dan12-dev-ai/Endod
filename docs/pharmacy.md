# Prescriptions at pharmacies: the contract

Business rules (decided by the owner):
- Only prescriptions from partner hospitals (hospital records, category
  `prescription`, received over `record.published`). No paper prescriptions.
- One QR per prescription. It keeps working at any pharmacy until everything
  on it has been given, it expires, or the hospital retracts it.
- Partial dispensing allowed, at several pharmacies.
- No payment through Endod. No pharmacy accounts or onboarding yet.
- Expiry: 30 days after the prescription's `occurred_at` (Africa/Addis_Ababa
  end of day).
- The pharmacist types the pharmacy's name; it is shown to the patient as
  given, without a verified badge.

## 1. Platform: what each prescription gets

When the platform stores a hospital prescription (`record.published`,
category `prescription`, highest version), it gets a dispensing entry:
- `rx_id`: 32 hex.
- QR token: `<rx_id>.<signature>`; signature = base64url HMAC-SHA256 over
  `rx:` + rx_id with a server secret (`RX_SIGNING_KEY`, separate from the
  card key), truncated to 22 chars. The QR encodes
  `https://pharmacy.endod-health.com/rx/<token>`.
- Code: 6 random digits, unique among active prescriptions. It is texted to
  the patient's verified phone once when the prescription arrives (Amharic
  then English, no drug names: "Endod: prescription code 482913 from
  <hospital>. Show it with your phone number at the pharmacy."). Never texted
  to an unverified phone.
- Items: one per prescription item, index-based (`item_index`), with
  `quantity_text` (as written), `quantity_total` (the leading number if the
  text starts with one, else null), `given_total` (number, when counted) and
  `status`: `not_given` | `partly_given` | `given`.

A correction (higher version) keeps the same rx_id, QR and code; items are
re-matched by index, given amounts kept. A retraction or expiry closes it.

A patient whose account an Endod admin suspended keeps their prescriptions:
lookups and dispenses work as before (continuity of care); only signing in
to the app and new hospital links are refused.

## 2. Platform API for the pharmacy site (server to server)

Served by the platform's `internal-api` (bus network, alias
`endod-platform-api`), header `X-Pharmacy-Key` (env `PHARMACY_API_KEY`,
constant-time compare, refused when unset). The pharmacy site's server
passes the pharmacist's IP in `X-Client-IP` for rate limiting. Browsers
never call it directly.

`POST /pharmacy/lookup`
- body `{"token": "<rx_id>.<sig>"}` OR `{"code": "482913", "phone": "09..."}`
- code lookups require the patient's phone (normalised, must match the
  account's verified phone). Limits: 10 failed code lookups per client IP per
  hour, and 5 failed per code per hour; then 429. Token lookups: 60 per IP per
  hour. A wrong signature, unknown code or phone mismatch all give the same
  404 "Not found".
- 200: `{"rx_id", "status": "open"|"completed"|"expired"|"retracted",
  "hospital_name", "doctor_name", "written_at", "expires_at",
  "patient": {"name", "dedan_id", "age": int|null, "sex": str|null},
  "notes", "items": [{"item_index", "drug", "dose", "route", "frequency",
  "duration", "quantity_text", "quantity_total", "given_total", "status",
  "notes"}], "dispenses": [{"at", "pharmacy_name", "items": [...]}]}`.
  Nothing else about the patient (no diagnoses, no other records).

`POST /pharmacy/dispense`
- body `{"token" | "code"+"phone", "pharmacy_name": str (2-120),
  "pharmacist_name": str|null, "items": [{"item_index", "amount": number|null,
  "complete": bool}]}`
- `amount` counts down `quantity_total` when it is known (never below 0; more
  than what is left is 409). `complete: true` marks the item given whatever
  the count. Only `open` prescriptions; otherwise 409 with the status.
- Idempotency: header `Idempotency-Key` (uuid); the same key returns the same
  result without dispensing twice.
- 200: the updated prescription (as lookup). When every item is `given`, the
  status becomes `completed` and the QR and code stop working for dispensing
  (lookup still shows it as completed).

## 3. What the patient sees (platform frontend)

On each hospital prescription in History: the QR (large, for scanning), the
6-digit code, expiry, per-item status ("14 of 21 given" / "Given" / "Not
given yet") and the list of dispenses ("Pharmacy (as entered): Kenema
Pharmacy, 23 Oct 14:10").
On each dispense, an SMS (Amharic then English: "Endod: medicine from your
prescription was given at a pharmacy. Details in the Endod app.") and an
inbox item ("Medicine given at a pharmacy"). Neither names a drug. The SMS
never names the pharmacy. In the inbox body and History, the pharmacy's
name is shown only as plain text (never a link), labelled as entered by the
pharmacy.

Items are identified by `item_index`, the item's position in the
hospital's list as sent. Empty items the platform drops do not shift the
others.

## 4. Platform -> hospital

platform -> hospital `prescription.dispensed`
`{"record_id" (the hospital's), "hospital_id", "dedan_id", "dispense_id",
"at", "pharmacy_name", "status": "open"|"completed",
"items": [{"item_index", "amount", "complete", "given_total", "status"}]}`

The hospital service stores it and shows it on the prescription record in
the portal ("Dispensed: Kenema Pharmacy, 23 Oct, 14 of 21"). Idempotent on
dispense_id.

## 5. Pharmacy site

`pharmacy.endod-health.com` (the pharmacy_scanner Next.js app):
- `/` scanner (existing design) + code and phone entry. A scanned QR that is a
  `https://pharmacy.endod-health.com/rx/<token>` URL is looked up; anything
  else is "Not an Endod prescription".
- `/rx/<token>` opens the prescription directly (phone camera apps open the
  URL).
- Prescription page (replaces the sample `/patient`): real data from lookup,
  per-item "given now" inputs, pharmacy name (remembered on that device),
  Dispense button with confirmation, then the updated state.
- Its Next.js server routes call the platform with `PHARMACY_API_KEY`
  (`PLATFORM_API_URL=http://endod-platform-api:8000`); the key never reaches
  the browser. Same-origin checks on its POST routes.
