# Appointment Reminders — Operations Runbook

Appointment reminders, the notification worker, and the queue behind them.

> **Read this first.** Reminders are queued in the database by the API and
> delivered by a worker. **If no worker runs, reminders are stored and never
> sent** — patients are told nothing, and nothing in the request path fails to
> warn you. That was this system's previous behaviour: the queue, the retry
> policy and the idempotency keys were all implemented and all tested, but the
> worker was never invoked, and the deployed database held 52 queued reminders
> and 0 delivered.

---

## 1. How it works

```
POST /users/me/appointments
        │
        ▼
AppointmentService.create_appointment        persists the booking + a timeline event
        │                                      (never sends; a mail outage cannot
        │                                       fail a patient's booking)
        ▼
scheduler.schedule_reminders                 derives offsets from the stored
        │                                      appointment + the patient's
        ▼                                      preferences; records SKIPPED rows
notifications.enqueue_reminders              durable rows in `notifications`
        │
        ▼
NotificationWorker.run_once                  claim → render → provider → mark
        │
        ▼
EmailProvider (SMTP | console)               SENT | RETRYING | FAILED
```

The `notifications` table **is** the queue. There is no broker. A durable table
beats adding Redis for a single-region deployment: it survives a restart, it is
inspectable when a patient asks why they were or were not emailed, and it needs
no new infrastructure.

### Reminder offsets

Offsets are seconds before the appointment. Precedence:

1. `appointment.reminder_offsets` (per appointment)
2. `preferences.reminder_offsets` (per patient, editable in the portal)
3. `DEFAULT_REMINDER_OFFSETS` — `604800,86400,3600` (7d / 24h / 1h)

Only offsets whose window is **still open** are queued. An appointment booked
12 hours out gets the 1-hour reminder; the 24-hour and 7-day windows are recorded
as `SKIPPED` rows rather than silently dropped, so "why did I not get a 24-hour
reminder?" is answerable.

---

## 2. Running the worker

Pick **one** of these. Running both is safe for correctness but doubles delivery
work.

### Option A — in-process (single replica)

```
NOTIFICATION_WORKER_ENABLED=true
```

The loop starts in the FastAPI lifespan. Simplest, and correct for one API
replica: claiming is an atomic conditional `UPDATE`, so several workers cannot
take the same job.

With **multiple API replicas**, every process runs its own loop. That is safe
but wasteful, and a rolling deploy restarts all of them at once. Enable it on
exactly one process.

The app logs `notification_worker_disabled_reminders_will_not_be_delivered` at
startup when this is off — that warning is the signal to act on.

### Option B — separate process (recommended for multiple replicas)

```
make worker              # foreground
make worker-once         # drain one batch and exit (cron / CronJob)
make worker-reconcile    # repair coverage, then exit
```

Run exactly one replica, supervised by systemd or a Kubernetes Deployment.
Leave `NOTIFICATION_WORKER_ENABLED=false` in the API.

It handles `SIGTERM`/`SIGINT` and drains rather than being killed, so a rolling
deploy does not strand jobs in `PROCESSING`.

---

## 3. Delivery guarantees

This is **at-least-once** processing with **idempotent** creation. Exactly-once
delivery is not achievable across an external mail provider and a local database
transaction — if the provider accepts a message and the transaction then fails,
you cannot know whether the patient received it.

What is implemented:

| Guarantee | Mechanism |
|---|---|
| No duplicate logical notification | `idempotency_key` UNIQUE, derived from (appointment, offset, channel, scheduled instant) |
| Safe re-arming | Key includes the appointment instant, so a reschedule creates a *new* job rather than colliding |
| Re-arm after cancellation | Cancelled/skipped jobs are resurrectable; `SENT` and `FAILED` are not |
| Concurrent workers | Conditional `UPDATE` claim; the loser of the race gets zero rows |
| Crash recovery | `PROCESSING` older than `NOTIFICATION_STALE_SECONDS` returns to the queue |
| Bounded retries | Exponential backoff, capped at `NOTIFICATION_MAX_ATTEMPTS` |
| Provider timeout | `SMTP_TIMEOUT_SECONDS` |
| Missing reminders repaired | `reconcile_appointments()` on worker start |

### Status meanings

| Status | Meaning |
|---|---|
| `PENDING` | Queued, waiting for `scheduled_for` |
| `PROCESSING` | Claimed by a worker |
| `SENT` | **Submitted to the transport.** Not confirmed delivered. |
| `RETRYING` | Failed transiently; `scheduled_for` holds the next eligible time |
| `FAILED` | Retry budget exhausted. Terminal. |
| `CANCELLED` | Appointment cancelled, completed, missed or rescheduled |
| `SKIPPED` | Policy decision: window closed, channel opted out, or no destination |

`provider_message_id` holds the transport's reference when one is offered. Its
**absence does not mean failure** — SMTP returns no id. `SENT` is a submission
receipt, never a delivery confirmation. There is no delivery-receipt webhook in
this system, so nothing here should be reported as "delivered".

---

## 4. Monitoring

Structured logs (one JSON object per event):

| Event | Carries |
|---|---|
| `notification_worker_started` | poll interval, batch size |
| `notification_batch_complete` | claimed, sent, retrying, failed, recovered_stale |
| `notification_queue_metrics` | pending, oldest_pending_seconds, by status |
| `notification_failed_permanently` | job id, attempts |
| `notification_failures_in_batch` | batch summary, when a batch contains failures |
| `appointment_reminders_repaired` | appointment, queued, expected, found |
| `appointment_reminders_cancelled` | appointment, count |
| `reminders_skipped_channel_opted_out` | appointment, channel |
| `notification_worker_pass_failed` | stack trace; the loop continues |

### Alert on

- `notification_worker_disabled_reminders_will_not_be_delivered` at startup — **page**.
- `oldest_pending_seconds` above your SLO (e.g. 15 min) — the queue is stalled.
- Any `FAILED` — reminders are being permanently lost.
- `appointment_reminders_repaired` appearing repeatedly — enqueue is failing at
  booking time.
- Steady `SKIPPED` growth with no `SENT` — patients are opted out or have no
  address on file.

---

## 5. Operational tasks

```bash
make worker-reconcile   # repair coverage, exit
make migrate            # apply pending schema migrations
```

`reconcile_appointments()` repairs two silent conditions:

- appointments whose reminders were lost during a failed enqueue;
- cancelled/completed/missed appointments still holding open reminders.

It is idempotent and safe to run on a schedule.

### Inspecting the queue

```sql
SELECT status, COUNT(*) FROM notifications GROUP BY status;

-- Oldest job still waiting
SELECT id, appointment_id, status, scheduled_for
FROM notifications
WHERE status IN ('PENDING','RETRYING')
ORDER BY scheduled_for LIMIT 10;

-- What a patient was actually sent
SELECT n.id, n.status, n.sent_at, n.provider_message_id, a.scheduled_at
FROM notifications n JOIN appointments a ON a.id = n.appointment_id
WHERE n.user_id = '<internal_user_id>' ORDER BY n.created_at DESC;
```

### Clearing a stuck job

```sql
UPDATE notifications SET status = 'RETRYING', scheduled_for = CURRENT_TIMESTAMP
WHERE id = '<job_id>' AND status = 'PROCESSING';
```

The worker's stale-job recovery will do this automatically after
`NOTIFICATION_STALE_SECONDS`; do it by hand only when investigating.

---

## 6. Schema migrations

`create_all()` can create a table but cannot **add a column** to one that
already exists. New columns therefore ship through
`dedan_platform/migrations.py`, which is:

- additive only (`ADD COLUMN`, backfill, `CREATE INDEX`) — nothing dropped or
  retyped, so no data is at risk;
- idempotent — guarded by schema inspection, safe on every startup;
- portable between SQLite and PostgreSQL.

Applied automatically by `create_all()` at startup, or explicitly via
`make migrate`.

`appointment_id` is backfilled for rows enqueued before the column existed, so
legacy reminders can still be cancelled by the indexed lookup.

---

## 7. Known limitations

- **Console transport by default.** With `SMTP_HOST` unset the worker *logs*
  messages and marks them `SENT`. Nothing reaches a patient. The app warns on
  every pass. **Set `SMTP_HOST` in production.**
- **No delivery receipts.** `SENT` means submitted. Confirming delivery would
  need a signed provider webhook, which is not implemented.
- **One worker on multiple API replicas** wastes throughput. Use Option B.
- **Patient timezone is display-only.** Appointment instants are stored and
  scheduled in UTC; the IANA zone is retained for rendering and calendar maths.
  Changing a patient's zone does not re-compute pending reminder instants.
- **Reminders are logistics-only.** No diagnosis, medication or condition ever
  enters a subject line or the queue payload.
- **`/realtime/token` mints a token for any supplied subject** and is
  unauthenticated. It is self-documented as a bootstrap weakness and predates
  this work, but it is an authentication gap worth closing before production.
- **No follow-up, medication-record or safety-check domain.** Not yet
  implemented; see the phase plan.

---

## 8. Tests

```bash
make test-backend
```

`tests/test_reminders.py` covers scheduling, lifecycle suppression, delivery,
retries, crash recovery, concurrency, consent, timezone and reconciliation.
`tests/test_notification_delivery.py` drives the worker **loop** itself (the
component that was never invoked), covers the notification API's ownership
rules, and tests the migration against a simulated legacy schema.

No test sends real email: every provider is a fake that records into a list.