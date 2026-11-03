# Endod's service fee

**The decision (CEO):** Endod covers the cost of SMS and earns a **service
fee charged to the patient** (never to the hospital) on **every payment the
patient makes for a hospital service**: a booking, a lab test, imaging, a
procedure, any other charge. The hospital's bill is 200 ETB; the patient pays
225 ETB (25 ETB fee). A second test: the same again. The fee is not hard-coded:
the super admin sets it. Every payment for a hospital service is recorded with
its fee.

Code: `backend-v2/dedan_platform/fee_settings.py` (the settings and the rule),
`fee_ledger.py` (Endod's books), `hospital_bookings.py` (bookings),
`hospital_charges.py` (charges and the patient's bills), `api_admin.py` (the
super admin's API). The hospital service: `app/fees.py`, `app/charges.py`,
`app/integrations/charges.py` (Hospital-service repository). The super admin:
the "Service fee" and "Fees" pages (endod-superadmin repository). Money is in
santim (integers) everywhere.

## 1. The settings (single source of truth: this platform)

`platform_settings` rows:

| Key | Meaning | Default |
| --- | --- | --- |
| `fees.enabled` | `true` / `false`: whether any fee is charged | `true` |
| `fees.flat_santim` | the flat part, santim | `2500` (25 birr) |
| `fees.percent_bp` | an optional share of the subtotal, basis points (150 = 1.5%) | `0` |
| `fees.version` | raised on every change | `0` |
| `fees.updated_by` | the super admin who last changed them | |

Until the super admin first saves them, the defaults come from the
environment (`SERVICE_FEE_FLAT_SANTIM`, `SERVICE_FEE_PERCENT_BP`,
`SERVICE_FEE_ENABLED`), then the built-in values above. **Production: set
`SERVICE_FEE_FLAT_SANTIM=2500`** in `deploy/.env` (it was 500), or save the
settings once in the super admin.

Limits: flat 0 to 1,000 birr (`100000` santim), share 0 to 20% (`2000` bp);
an enabled fee needs a flat part or a share. Not done (cheap to add later):
per-category settings (a different fee for lab tests than for bookings).

## 2. The rule

```
fee = 0                                                   if not enabled, or subtotal = 0
fee = flat_santim + round_half_up(subtotal * percent_bp / 10000)   otherwise (santim)
total = subtotal + fee
```

* **One fee per payment**: per booking, and per charge (a charge with three
  lab tests is one payment: one fee). The CEO's "per service" is per payment
  the patient makes; a hospital that bills each test separately creates a
  charge per test.
* **Free is free**: a free visit (price 0) carries no fee, and is not in the
  ledger.
* The share is rounded half up to the santim; the fee is never refunded
  separately (a refund returns price and fee together).
* The same function on both sides (`fee_settings.fee_for` here,
  `app/fees.py` in the hospital service; tests on both sides pin it).

## 3. How the hospital service knows the fee

`fees.updated` (platform -> hospital, on `endod:patient`):

```json
{"version": 3, "enabled": true, "flat_santim": 2500, "percent_bp": 0, "currency": "ETB",
 "updated_at": "2026-11-03T08:00:00+00:00"}
```

Sent in the same transaction as every change (outbox), and by the events
worker at its start and every 6 hours (`fee_settings.BROADCAST_EVERY`). The
hospital service keeps the newest version it received (a table of its own),
so it quotes the right fee while this platform is down; before it has ever
received one it uses its own default (`HOSPITAL_DEFAULT_SERVICE_FEE_SANTIM`,
2500).

## 4. Bookings

| How paid | Fee | Ledger |
| --- | --- | --- |
| Online (Chapa configured) | fee, paid with the price on Chapa | when Chapa confirms: `collected_by` endod, `collected`; a refund or reversal makes it `refunded` |
| At the hospital (no Chapa key) | **fee, now charged too** (it was 0 before) | when the hospital says it was paid (`appointment.paid`, method and reference) or, at the latest, when it completes the visit (method `unrecorded`): `collected_by` hospital, `owed` |
| Free (price 0) | none | none |

`appointment.requested` carries `price`, `service_fee` and `total`. For
`"payment": "at_hospital"` the hospital collects `total` and owes Endod
`service_fee`. The patient is told "Pay ETB 125.00 at the hospital (including
the Endod service fee of ETB 25.00)". A booking cancelled or declined before
the visit owes nothing.

hospital -> platform `appointment.paid`
`{"appointment_id", "hospital_id", "method": "cash"|"card"|"mobile_money"|"other", "reference"?, "paid_at"?}`
(only for a booking paid at the hospital; the platform's own price and fee
are recorded, not the hospital's numbers).

## 5. Charges: any other hospital service

The hospital's system creates a charge through the integration API
(`POST /charges`, scope `charges.write`; Hospital-service
`docs/integrations.md`, "Charges"). The hospital service adds the fee and
tells this platform:

hospital -> platform `charge.created` (only for a patient linked to an Endod account)
```json
{"charge_id": "...", "hospital_id": "...", "dedan_id": "DE123456", "appointment_id": null,
 "items": [{"category": "lab_test", "code": "CBC", "name": "Complete blood count", "amount": 35000, "quantity": 1}],
 "subtotal": 35000, "service_fee": 2500, "total": 37500, "currency": "ETB"}
```
The patient's bill appears in the app (`GET /users/me/bills`), with an inbox
item and an SMS when they allow SMS: "Endod: your bill at the hospital is ETB
375.00 (incl. Endod service fee ETB 25.00). Please pay at the hospital." Never
clinical: no test, no hospital name.

hospital -> platform `charge.paid` (every charge, linked patient or not)
`{...the amounts..., "dedan_id"?, "method": "cash"|"card"|"mobile_money"|"other", "reference"?, "paid_at"}`
The fee ledger gets the entry (`collected_by` hospital, `owed`); the bill is `paid`.

hospital -> platform `charge.voided` `{"charge_id", "hospital_id", "dedan_id"?}`
The bill is `voided` (only an open charge can be voided).

**Online payment of charges is not offered yet** (production has no Chapa
key). When it is configured, paying a bill online is the next step: it needs
a Chapa checkout per bill, a payout of the subtotal to the hospital and
refunds, as for bookings; until then `pay_at` is always `hospital`.

## 6. The ledger (Endod's books)

`fee_ledger`: one row per paid hospital service: `source_type` (`booking` |
`charge`), `source_id`, `hospital_id`, the patient (`user_id`, `dedan_id`;
none for a charge to a patient not on Endod), `subtotal`, `fee`, `total`,
`method`, `reference`, `collected_by` (`endod` | `hospital`), `paid_at`, and
`settlement_status`:

* `collected`: paid online, Endod has the fee;
* `owed`: paid at the hospital, the hospital owes Endod the fee;
* `settled`: the hospital paid it over (a super admin marked it, with the
  reference of the transfer);
* `refunded`: the payment went back to the patient; no fee is due.

Written once per source (unique `source_type`, `source_id`): redelivered
events change nothing.

## 7. The super admin's API (`/internal/admin`, `X-Superadmin-Key`)

| | |
| --- | --- |
| `GET /internal/admin/fees` | the settings, what a 200 ETB bill becomes, the limits, the latest changes |
| `PUT /internal/admin/fees` | `{"enabled", "flat_santim", "percent_bp", "reason", "actor_email"}`: validated (422), kept in `fee_setting_changes` (who, why, before, after), sent as `fees.updated` |
| `GET /internal/admin/fees/summary?from=&to=` | per hospital: payments, subtotal, fees collected online, owed, settled, refunded (days in Addis Ababa) |
| `GET /internal/admin/fees/entries?hospital_id=&status=&source=&from=&to=&limit=&offset=` | the entries, newest first |
| `POST /internal/admin/fees/settle` | `{"hospital_id", "entry_ids", "reference", "actor_email"}`: owed entries of that hospital become `settled`, all or none (409) |

The super admin asks for a fresh authenticator code before changing the
settings or settling, and writes both to its own audit log.

## 8. Deploy order

1. This platform (new tables are created at start; the events worker starts
   sending `fees.updated`). Set `SERVICE_FEE_FLAT_SANTIM=2500` (or save the
   settings in the super admin right after step 3).
2. The hospital service (migration 0014: charges, the fee cache, the
   bookings' `service_fee`). Until it is deployed, `fees.updated` and the new
   booking fields wait in Redis / are ignored; nothing breaks.
3. The super admin.

## Tests

`backend-v2/tests/test_service_fee.py` (the rule, the settings and their
validation and audit, bookings online, at the hospital and free, charges and
bills, the ledger, summaries and settlement) and
`backend-v2/tests/test_partner_bookings.py`.
