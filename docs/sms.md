# SMS-first: patients without smartphones

Patients without a smartphone get their health information by SMS: their
card number (Endod ID), appointment and follow-up notices, prescription
codes for pharmacies, and, on request, their lab results and reports. The
CEO's choice ("Option B"): sensitive information is never pushed; the
patient **pulls** it by texting a command and their PIN to a short code.

Three parts:

1. **SMS-only patients**: a hospital enrols a patient who has no Endod
   account; Endod creates one on the strength of an SMS code (`sms_enrol.py`).
2. **Push** (as today's rules: never clinical): card number and PIN,
   "a lab result / report is ready", follow-ups, appointment texts,
   prescription codes (`patient_sms.py`).
3. **Pull** (`sms_inbound.py`, `api_sms.py`, `main_sms.py`): commands texted
   to the short code, **off** until the short code exists
   (`SMS_INBOUND_ENABLED=false`).

## 1. SMS-only patients

The hospital service's integration API (`POST /patients/{mrn}/sms-enrol`,
then `POST /patients/{mrn}/sms-enrol/verify`, see its guide) sends two
events over the bus (contract: [history-events.md](history-events.md),
section 8):

1. `patient.sms_enrol_requested` `{request_id, hospital_id, patient_id, phone}`:
   Endod texts a 6-digit code to the phone (Amharic, then English) and
   answers `patient.sms_enrol_code_sent`. Nothing else about the patient
   reaches Endod before the code proves the phone is theirs.
2. `patient.sms_enrol_verify` `{request_id, hospital_id, patient_id, code, name, language}`:
   reception typed the code the patient read out. Endod answers
   `patient.sms_enrolled` `{..., dedan_id, name, phone, created}` and:
   * the phone has no account: creates one (verified phone, no password,
     `users.sms_only`, the language given, SMS allowed) with a new Endod ID;
   * the phone already signs in to an account: that account (no duplicate);
   * links the hospital patient to it (like `patient.linked`);
   * texts the card number and a new 4-digit PIN, with how to use and change
     it (only mentioning the short code while it is live). An app account
     that already has a PIN keeps it (the text gives the card number only).

Refusals: `patient.sms_enrol_refused` `{..., reason, attempts_left}`, reason
`invalid_phone`, `rate_limited`, `sms_unavailable` (step 1) or `wrong_code`
(with `attempts_left`; the code still works), `too_many_attempts`, `expired`,
`superseded` (a newer request for this patient), `no_code`, `not_allowed`
(the phone's account is closed or suspended) (step 2).

Limits: the code expires after `SMS_ENROL_CODE_TTL_MINUTES` (10), allows
`SMS_ENROL_MAX_ATTEMPTS` (5) guesses (counted atomically), and only the
newest request of a hospital patient counts. Sending: one a minute per phone
(`SMS_ENROL_RESEND_SECONDS`), `SMS_ENROL_MAX_PER_PHONE_PER_HOUR` (5),
`SMS_ENROL_MAX_PER_HOSPITAL_PER_HOUR` (200). Codes and PINs are stored as
HMACs only; the PIN text is sent straight to the provider after the commit
(never through the notification queue, so it is stored nowhere in clear).
Audit: `user_events` `sms_enrolled` (hospital, created, new PIN).

**Forgotten PIN, lost text:** reception enrols the patient again; the
account is found by its phone and a new PIN is texted.

**Taking the account over:** a patient who later signs up in the app with the
same phone (SMS code, then a password: `phone_auth.complete`) gets the same
account (the phone already signs in to it): records, card number and PIN
stay; `sms_only` is cleared and the inbox says "Welcome to the Endod app".

## 2. Push

All through the notification queue (retries, once per key), in the
account's language, to a verified phone of a patient who allows SMS (an
SMS-only patient does, by default). Never a test, record, diagnosis or
hospital name.

| When | Text |
|---|---|
| Enrolled | card number, PIN, how to use and change it |
| A lab result is published (not an import, not a prescription) | "a new lab result from your hospital is ready" |
| Any other record (imaging, visit note, diagnosis, document) | "a new medical report from your hospital is ready" |
| Prescription | its pickup code (as before) |
| Follow-up set / the day before | as before |
| Booking decisions, queue | as before |

"Ready" texts: at most one of each kind per hospital per day (a visit's
records arrive together), and not when the record was retracted before
sending. Decided: they go to **every** patient who allows SMS, not only
SMS-only ones. The ending depends on whether the short code is live
(`SMS_INBOUND_ENABLED` and `SMS_SHORT_CODE`, checked when the text is sent)
and on the patient:

| | short code live, patient has a PIN | otherwise |
|---|---|---|
| app account | "Text RESULT and your PIN to 8xxx or open the app." | "Open the app to see it." |
| SMS-only | "Text RESULT and your PIN to 8xxx to read it." | "Please ask at the hospital to see it." |

So no text ever names a command that would not work. Texts that point to the
app say something else to an SMS-only patient (follow-ups: "contact the
hospital to book it").

## 3. Pull: commands to the short code

Off by default. While `SMS_INBOUND_ENABLED` is false (or no
`SMS_INBOUND_SECRET`), every inbound route answers 404.

### Commands

Case-insensitive; the first word may also be the Amharic alias.

| Command | Aliases | Reply |
|---|---|---|
| `CARD <PIN>` | ID, ካርድ, መታወቂያ | the Endod ID (card number) |
| `APPT <PIN>` | APPOINTMENT, VISIT, ቀጠሮ | the next two visits booked through Endod and the next two follow-ups (date, hospital) |
| `RESULT <PIN>`, `RESULT 2 <PIN>` | RESULTS, LAB, ውጤት | three lab results per reply, newest first: date, test, value, unit, low/normal/high/critical; "Older: RESULT 2" when there are more |
| `REPORT <PIN>`, `REPORT 2 <PIN>` | ሪፖርት | the latest report's date, title and conclusion (imaging impression, visit plan, diagnosis, document description); never a file |
| `RX <PIN>` | PRESCRIPTION, MED, MEDS, መድሃኒት, መድኃኒት | up to three open prescriptions' pickup codes, until when, hospital |
| `PIN <old> <new>` | ፒን | changes the PIN (not all the same digit, not like 1234) |
| `HELP` (or anything else) | ?, እርዳታ | the list |

### Rules

* **Who:** the sender's number must be the *verified* phone of an active,
  unsuspended account. Any other number gets one generic "not registered,
  ask at your hospital" reply a day at most (naming no account).
* **PIN:** every command but HELP; an HMAC under the server's secret.
  `SMS_PIN_MAX_ATTEMPTS` (5) wrong PINs lock it for `SMS_PIN_LOCK_MINUTES`
  (60), and that reply tells the patient (and to tell the hospital if it
  was not them). An app account without a PIN is told to set one (app:
  `PUT /users/me/sms-pin`) or ask at the hospital.
* **Sensitive results are never sent, even on request:** a lab test whose
  LOINC `code` is in `SMS_SENSITIVE_LOINC`, or a test, record title or
  report text containing a word of `SMS_SENSITIVE_KEYWORDS` (a keyword must
  start a word), or a diagnosis whose ICD-10 code starts with one of
  `SMS_SENSITIVE_ICD10`: HIV, pregnancy/hCG, sexually transmitted
  infections, mental health by default. The reply says "this result is only
  available at the hospital or in the app" (no test name).
* **Rate limits** (in the database, shared by every replica):
  `SMS_INBOUND_MAX_PER_PHONE_PER_HOUR` (20) per sender,
  `SMS_INBOUND_MAX_PER_HOUR` (5000) in all; over them, no reply.
* **Length:** in the account's language (Amharic or English), at most
  `SMS_REPLY_MAX_SEGMENTS` (3) segments: GSM-7 153 characters a segment,
  UCS-2 (any Amharic) 67. Long result lines are shortened, then cut.
* **Audit:** every text received is a row of `sms_inbound_messages`:
  provider, its message id (a retried callback is answered once), the
  sender's phone masked, the account, the command and the outcome (`ok`,
  `ok_withheld`, `wrong_pin`, `pin_locked_now`, `pin_locked`, `no_pin`,
  `bad_format`, `help`, `pin_changed`, `pin_weak`, `unknown_sender`,
  `rate_limited`, `invalid_sender`). Never the text, the PIN or the reply;
  logs carry the command and outcome only.

Decided: APPT names the hospital (the patient asked, with their PIN, and a
visit without a place is not useful); RESULT and REPORT do not.

### The webhook (provider-agnostic)

Served by the `sms-inbound` service (`main_sms.py`: nothing but
`/sms/v1/inbound/...` and `/health`), published by the shared nginx at
`https://api.endod-health.com/sms/v1/inbound/` (deploy/shared-nginx).
Requests must come through nginx (`X-Endod-Edge-Key` = `EDGE_SHARED_SECRET`;
403 otherwise; in production without one configured, 503).

**Africa's Talking:** register the incoming-messages callback
`https://api.endod-health.com/sms/v1/inbound/africastalking/<SMS_INBOUND_SECRET>`.
They POST form fields `from`, `to`, `text`, `id`, `date`, `linkId`; their
callbacks are not signed, so the secret in the path authenticates them (a
wrong one is 404). The answer is `200 OK` at once; the reply goes out after,
from the short code (`from`), through their SMS API
(`AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY`).

**Any other gateway:** `POST /sms/v1/inbound/generic` with JSON
`{"from": "+2519...", "to": "<short code>", "text": "RESULT 1234", "id": "<message id>"}`
and the header `X-Endod-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of
"<t>.<body>" under SMS_INBOUND_SECRET>` (5 minutes' tolerance; wrong: 404).
The answer carries the reply for the gateway to send:
`{"reply": "...", "to": "+2519..."}` (`reply` null: send nothing).

## The PIN in the patient app

Settings > SMS PIN (`frontend/app/interview/sms-pin-section.tsx`, the same
section on desktop and on the phone screen `/interview/mobile-setting`), in
English and Amharic. It reads `GET /users/me/sms-pin`, the one source for
both the PIN's state and whether commands work: `has_pin`, `locked_until`
(only while locked), `commands_enabled` and `short_code` (null while the
short code is not live). It:

* says what the PIN is for and whether one is set;
* sets or changes it (`PUT /users/me/sms-pin`: new PIN and confirmation; the
  signed-in session is the proof, so the current PIN is not asked for and a
  forgotten or locked PIN can be replaced here, which also unlocks it);
* checks 4 digits, the confirmation and the easy PINs before sending (the
  backend still decides; a 422 shows the "too easy to guess" message);
* while `commands_enabled` and a `short_code`: the short code and the CARD,
  APPT, RESULT, REPORT and RX commands; otherwise "coming soon", no number.

## Settings

In `platform_settings` (key `sms.<NAME>`, for the super admin later) or the
environment; the secrets (`SMS_INBOUND_SECRET`, `AFRICASTALKING_API_KEY`,
`AFRICASTALKING_API_URL`) from the environment only. Read on every use.

| Name | Default |
|---|---|
| `SMS_INBOUND_ENABLED` | `false` |
| `SMS_SHORT_CODE` | (none) |
| `SMS_INBOUND_SECRET` | (none: inbound refused) |
| `SMS_REPLY_PROVIDER` | `africastalking` (`default`: the outbound provider) |
| `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY` | (none) |
| `AFRICASTALKING_API_URL` | `https://api.africastalking.com/version1/messaging` |
| `SMS_PIN_MAX_ATTEMPTS`, `SMS_PIN_LOCK_MINUTES` | `5`, `60` |
| `SMS_INBOUND_MAX_PER_PHONE_PER_HOUR`, `SMS_INBOUND_MAX_PER_HOUR` | `20`, `5000` |
| `SMS_REPLY_MAX_SEGMENTS`, `SMS_RESULTS_PER_REPLY` | `3`, `3` |
| `SMS_ENROL_CODE_TTL_MINUTES`, `SMS_ENROL_MAX_ATTEMPTS` | `10`, `5` |
| `SMS_ENROL_RESEND_SECONDS`, `SMS_ENROL_MAX_PER_PHONE_PER_HOUR`, `SMS_ENROL_MAX_PER_HOSPITAL_PER_HOUR` | `60`, `5`, `200` |
| `SMS_SENSITIVE_LOINC`, `SMS_SENSITIVE_KEYWORDS`, `SMS_SENSITIVE_ICD10` | comma-separated lists (sms_settings.py) |

## Switching the commands on

See deploy/README.md, "SMS-first". In short: the short code, then
`SMS_SHORT_CODE`, `SMS_INBOUND_SECRET`, the Africa's Talking credentials and
`EDGE_SHARED_SECRET`; register the callback URL; `SMS_INBOUND_ENABLED=true`.
