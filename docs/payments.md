# Payments: each booking paid through Chapa

Endod keeps **no stored balance**. A patient pays for each paid booking at a
partner hospital (in person or video) on Chapa's checkout, choosing telebirr,
CBE Birr, M-Pesa, a bank or a card there. Refunds go back through Chapa to the
original payment method. The hospital side is unchanged: it still receives
only paid bookings (`appointment.requested`, see
[history-events.md](history-events.md) and `backend-v2/dedan_platform/hospital_bookings.py`).

Code: `backend-v2/dedan_platform/booking_payments.py` (holds, confirmation,
refunds), `hospital_bookings.py` (the booking states), `chapa.py` (Chapa's
API), `events_worker.py` (the timed jobs). Money is in santim (integers).

## Booking and paying

```
POST /users/me/appointments  (facility_id = a partner hospital)
  -> appointment: hospital_booking.state = awaiting_payment  (the slot is held)
  -> booking_payments row: tx_ref, amount = price + service fee, expires in 30 min
  -> Chapa /transaction/initialize -> checkout_url
     return_url   = {PUBLIC_APP_URL}/interview?section=appointment&payment={tx_ref}
     callback_url = {PUBLIC_APP_URL}/api/payments/chapa/callback
<- 201 { appointment, payment: { price, service_fee, total, status, checkout_url, tx_ref, expires_at } }
```

The app sends the patient to `checkout_url`. Nothing is sent to the hospital
and no reminders are set while the booking waits for payment.

**Confirmation** happens only when Chapa's own verify endpoint
(`GET /transaction/verify/{tx_ref}`) says `success` for **exactly** the amount
asked, in `ETB`. Three things trigger that check; none is trusted on its own:

| Trigger | Route |
| --- | --- |
| Chapa's webhook (signature checked with `CHAPA_WEBHOOK_SECRET`: `x-chapa-signature` = HMAC-SHA256 of the body, or `chapa-signature` = HMAC-SHA256 of the secret) | `POST /api/payments/chapa/webhook` -> `POST /payments/chapa/webhook` |
| Chapa's callback | `GET/POST /api/payments/chapa/callback` -> `/payments/chapa/callback` |
| The patient back on the return URL (signed in, their own payment only) | `GET /users/me/booking-payments/{tx_ref}` |
| The events worker, for missed notifications | `booking_payments.recheck()` every 2 minutes |

On a confirmed payment, in one transaction with the payment row locked: the
payment becomes `paid`, the appointment `awaiting_hospital` (in person) or
`awaiting_doctor` (video), the hospital's payout is held, the patient is
linked to the hospital, and `appointment.requested` is emitted exactly as
before. The payment moves out of `pending` once, so repeated webhooks,
callbacks and returns change nothing.

**Another amount or currency** is never accepted: the payment becomes
`mismatch`, the hold ends (`payment_expired`), an `ALERT
booking_payment_mismatch` is logged, and a refund is recorded as
`manual_refund_needed` for a person to settle from the Chapa dashboard.

## Holds

* A hold lasts **30 minutes** (`booking_payments.HOLD`). The events worker
  (`expire_holds`, every minute) first asks Chapa about it (a payment whose
  webhook was missed is confirmed, not expired), then ends it: the
  appointment is cancelled (`payment_expired`), freeing the slot.
* A payment Chapa confirms **after** the hold ended (or after the patient
  dropped the unpaid booking) is **refunded automatically** (the slot may be
  gone). Ended holds are re-checked with Chapa for a day.
* A patient may have at most **3** bookings waiting for payment
  (`MAX_OPEN_HOLDS`); a 4th is refused with 409.
* The patient may cancel an unpaid booking at any time; the hospital is not
  told (it never heard of it).
* Only paid bookings count as a link between a patient and a hospital
  (`patient_history.may_act_for`).

`hospital_booking.payment` in every appointment shows where the payment is:
`awaiting_payment` (with `due_at` and the `checkout_url` for "Pay now" until
the hold ends), `paid`, `expired`, `refund_pending` or `refunded`.

## Refunds

When a paid booking is declined or cancelled by the hospital, cancelled by the
patient before the visit, or never answered by the hospital (two hours after
its time), the price **and** the service fee are refunded, as before.

Each refund is a `booking_refunds` row, **at most one per payment** (unique on
`payment_id`; asking again returns the first). The events worker
(`process_refunds`, every 30 seconds) sends it to Chapa:

```
POST {CHAPA_BASE_URL}/refund/{tx_ref}
Authorization: Bearer {CHAPA_SECRET_KEY}
{ "amount": "158.00", "reason": "...", "reference": "endod-rf-{payment id}", "meta": {...} }
-> { "status": "success", "message": "Refund initiated successfully",
     "data": { "ref_id": "...", "payment_reference": "..." } }

GET {CHAPA_BASE_URL}/refund/{ref_id}/verify   -> data.status: initiated | processing | refunded | reversed
```

(Chapa's refund API, https://developer.chapa.co/refund. Chapa takes the
refund from the merchant's available balance; its own charges are not
refunded.)

| Refund status | Meaning |
| --- | --- |
| `pending` | to be sent; after a failed attempt, `next_attempt_at` waits 1 min, 5 min, 15 min, 1 h, 4 h, 12 h |
| `submitted` | Chapa accepted it (`chapa_ref_id`); checked every 30 min until Chapa says `refunded` |
| `succeeded` | Chapa says the payer has it; the appointment shows `refunded` |
| `manual_refund_needed` | Chapa refused it (any 4xx other than 401/403/408/429), reversed it, was unreachable through all retries, or still had not finished after 14 days |

A worker claims a refund for 10 minutes before calling Chapa, so two workers
never send it at once. The `reference` is the same on every attempt, so if a
worker dies after Chapa accepted a refund but before recording it, the retry
is refused by Chapa as a duplicate (and the refund becomes manual) instead of
paying twice.

**Manual refunds.** Each one logs `ALERT manual_refund_needed refund=... tx_ref=...
amount=... why=...` at ERROR and adds a `payment.manual_refund_needed`
audit row (`user_events`). Refund it from the Chapa dashboard by `tx_ref`,
then set the row to `succeeded` and the appointment's `payment_status` to
`refunded`:

```sql
SELECT r.id, p.tx_ref, r.amount, r.last_error FROM booking_refunds r
JOIN booking_payments p ON p.id = r.payment_id WHERE r.status = 'manual_refund_needed';
```

The patient is told, in their language (inbox and SMS), that the amount "is
being refunded to your payment method (it can take a few days)". Texts never
carry clinical details.

## The old balance

Deposits are gone: `POST /users/me/wallet/deposits` and
`GET /users/me/wallet/deposits/{id}` answer **410 Gone** ("Top-ups are no
longer available"). The `wallets`, `wallet_entries` and `deposits` tables and
their code stay, readable (`GET /users/me/wallet`), and are not dropped. A
booking paid from the old balance (none exist in production) is still
refunded there. The patient app has no balance section.

## Configuration

| Variable | |
| --- | --- |
| `CHAPA_SECRET_KEY` | Chapa secret key (`CHASECK-...`, test keys `CHASECK_TEST-...`). Without it paid bookings answer 503. |
| `CHAPA_WEBHOOK_SECRET` | Chapa > Settings > Webhooks: the secret hash. Webhook URL: `https://endod-health.com/api/payments/chapa/webhook` |
| `CHAPA_BASE_URL` | default `https://api.chapa.co/v1` |
| `PUBLIC_APP_URL` | where Chapa sends the patient back |
| `SERVICE_FEE_FLAT_SANTIM`, `SERVICE_FEE_PERCENT_BP` | Endod's fee |

## Tests

`backend-v2/tests/test_partner_bookings.py` (with `conftest.FakeChapa`, which
also answers the refund endpoints) and `frontend/tests/payments.spec.ts`
(with `frontend/tests/fake-chapa.mjs`).
