# Deploying Endod Health

One Docker Compose project (`endod`) on the server: Postgres, the API
(`backend-v2`), the patient web app (`frontend`) and a Cloudflare Tunnel.
Nothing is published on the host, so it runs next to other projects
(e.g. the server's existing nginx on ports 80/443) without touching them.

```
browser ──HTTPS──> Cloudflare ──tunnel──> cloudflared ──> frontend:3000 ──> backend:8000 ──> postgres
```

## One-time setup

1. **DNS**: the domain's nameservers must be Cloudflare's (registrar dashboard).
2. **Tunnel** (Cloudflare Zero Trust > Networks > Tunnels, or the API):
   create a tunnel, add a public hostname `endod-health.com` (and
   `www.endod-health.com` if wanted) with service `http://frontend:3000`,
   and copy its token.
3. **Server**: Docker with the Compose plugin. Put the repository in
   `/opt/endod` and create `deploy/.env` from `deploy/.env.example`
   (secrets: `openssl rand -base64 48`).

## Encryption of health data

Clinical data is encrypted by the application before it reaches the database
or the `records` volume (`backend-v2/dedan_platform/crypto.py`): each patient
has a data key, and those keys are encrypted ("wrapped") with one **master
key** that lives only in a file on this server. A copy of the database or of
the volume, a backup or a leaked dump is unreadable without that file.

What is encrypted, per patient (AES-256-GCM, each value bound to its table,
column, row and patient):

- hospital records: title, details, retraction reason; their files (on disk,
  in 64 KiB chunks) and file names;
- self-reported visits, AI consultations and every other timeline entry:
  title, description and details;
- the health profile: conditions, allergies, medications, blood type;
- appointments: the patient's notes (often symptoms), the department and the
  hospital's reason on a booking;
- follow-up notes; prescription quantities and the stored pharmacy answer
  (drug names and doses are in the record's details);
- inbox titles and bodies.

Not encrypted: account data needed to sign in, link and search (names, phone,
email, Endod ID, address), date of birth, sex and age range (age rules and
the pharmacy's view), emergency contacts, dates, statuses, categories, and
hospital and doctor names. Events sent to the hospital service keep their
payload only until Redis has them: a sent outbox row is emptied at once.

**Events in Redis are in plaintext while in flight.** The hospital service
(another system) reads event payloads as they are, so bookings, shared
records and records from hospitals cross Redis unencrypted. They stay only
until acknowledged: the events worker deletes each stream entry as soon as
every consumer group has acknowledged it (an entry never acknowledged, the
other side being down, at most 7 days). Dead letters keep no clinical content
(the event's id, type, identifiers and the error, input values removed) and
are capped at 10 000. On disk Redis keeps only its append-only file (no RDB
snapshots), which `redis/redis.sh` rewrites every hour, so deleted entries do
not linger in it beyond that.

**Accepted residual risk: replay.** Each value is bound to its table, column,
row and patient, so it cannot be moved. But someone able to *write* to the
database can put back an older ciphertext of the same row and column (an
earlier version of that note), and it decrypts. A per-row counter in the
binding would not stop them: they would put back the old counter too.
Database write access is what guards against this (credentials only in
`deploy/.env`, Postgres not published outside the Compose network).

**The key must be the database's.** On first start the database records a
check value of the master key and its fingerprint (`platform_settings`). Every
service checks the mounted key against it at start, and again before wrapping
any new patient's key, and refuses another key: a wrong file mounted once
would otherwise wrap new keys that no longer open once the right one is back.
The fix is to mount the right file (from its offline backup), never to clear
the check.

**Keys are never overwritten.** The platform's services share one database
role, so this is enforced in the code, not by grants: no statement may change
`user_keys` beyond its `active` flag, or delete from it, except
`tools purge-old-keys` (deleting old versions nothing uses); anything else is
refused before it reaches the database.

**No data in logs.** Statement parameters are hidden from database errors,
and every log line and dead letter is stripped of PostgreSQL `DETAIL` lines,
SQL parameter blocks and quoted input values.

**Isolation.** First data keys are created inside the request's own
transaction; this relies on READ COMMITTED, PostgreSQL's default, which the
platform uses (nothing sets REPEATABLE READ or SERIALIZABLE). Under a
stricter level a lost race would fail that request, never use a wrong key.

### The master key (once, before the first deploy with encryption)

```sh
K=/opt/endod/deploy/keys/master.key
sudo install -d -m 0700 -o root -g root /opt/endod/deploy/keys
sudo sh -c "umask 077 && openssl rand -out $K 32"
# The services run as uid 10001 (the image's "dedan" user), never root, and a
# mounted file keeps its owner and mode: owned by that uid, read-only.
sudo chown 10001:10001 $K && sudo chmod 0400 $K
sudo sha256sum $K      # note this fingerprint with the offline backup
```

The directory is root-only (0700): on the host, only root reaches the key.
`deploy/keys/` is in `.gitignore`; never commit it, mail it, paste it or keep
it in a cloud drive. Compose mounts it read-only at
`/run/secrets/platform_master_key` in `backend`, `internal-api` and
`events-worker` only, and refuses to start them if the file is missing.
They also refuse to start without a usable key file in any environment
except an explicit `ENVIRONMENT=development` or `test` (staging, production,
anything else and an unset `ENVIRONMENT` all need it); in development or test
with no key file, a published development key is used (never for real data).
Each logs its key fingerprint at start (`master_key_in_use service=... id=...`).

### The OFFLINE backup of the master key

**Losing the master key means losing the health data**: the database backups
cannot be read without it. Keep two offline copies, apart from the database
backups (a backup that contains both the data and its key protects nothing):

```sh
sudo base64 /opt/endod/deploy/keys/master.key   # 44 characters
```

Write them on paper (or put them on a USB stick) kept in two safe places,
with the date and the `sha256sum` fingerprint. Do not store it with the
nightly backups. To restore it:

```sh
echo '<the 44 characters>' | base64 -d | sudo tee /opt/endod/deploy/keys/master.key >/dev/null
sudo chown 10001:10001 /opt/endod/deploy/keys/master.key && sudo chmod 0400 /opt/endod/deploy/keys/master.key
sudo sha256sum /opt/endod/deploy/keys/master.key   # the noted fingerprint
```

### Deploying encryption

1. Make the master key and its offline backup (above).
2. Back up the database and the `records` volume (Backups, below).
3. Deploy as usual (Deploy / update, below). The three services must log
   the same key id:

   ```sh
   docker compose logs backend internal-api events-worker | grep master_key_in_use
   ```
4. Encrypt what was stored before, check that nothing is left, then enforce
   -- in this order:

   ```sh
   docker compose exec backend python -m dedan_platform.tools encrypt-existing
   docker compose exec backend python -m dedan_platform.tools check      # every line "ok", exit 0
   docker compose exec backend python -m dedan_platform.tools enforce
   ```

   `encrypt-existing` works in batches and can be run again at any time;
   values stored before stay readable until `enforce`. `enforce` runs the
   check again and refuses if anything is left; once it succeeds, a value or
   file that is not encrypted is refused (logged with its table, column and
   row, never its content) instead of being read. Running services read the
   setting again every 30 seconds.

A patient's data key can be replaced (re-encrypting their data):
`docker compose exec backend python -m dedan_platform.tools rotate-key --user DE123456`.
The old key stays (inactive) for anything begun before the rotation; delete
it at least 24 hours later with `tools purge-old-keys --user DE123456`, which
refuses while anything (a value, a stored file, a file being downloaded) may
still need it.

### Rollback of encryption

To a release from before encryption, which cannot read encrypted values:

```sh
docker compose stop backend internal-api events-worker
# Refuses while any of the three is still connected to the database; then
# turns enforcement off and writes every value and file back in plaintext.
# It deletes no key: keep the master key, the backups need it.
docker compose run --rm --no-deps backend python -m dedan_platform.tools decrypt-existing --yes
git checkout <the previous release>
docker compose -f docker-compose.yml -f shared-nginx/docker-compose.override.yml --env-file .env up -d --build
```

(Or restore the backups from step 2, losing what was written since.) The
schema changes are additive (`user_keys`, `platform_settings`, two `user_id`
columns, wider text columns), so the older release runs on it. Keep the master key and its
backup: the backups taken while encryption was on need it.

## Deploy / update

```sh
cd /opt/endod/deploy
# On this server the shared nginx fronts Endod (no tunnel): add its override.
docker compose -f docker-compose.yml -f shared-nginx/docker-compose.override.yml \n  --env-file .env up -d --build
docker compose ps            # all healthy
docker compose logs -f backend
```

The API creates and migrates its tables on start.

## Staging vs production

All messages go by SMS through SMS Ethiopia: verification codes and
appointment reminders (`REMINDER_CHANNELS=sms`; there is no email). The
patient app has no AI agent, so no model key is configured
(`AI_PROVIDER_MODE=offline`).

`.env.example` sets `ENVIRONMENT=production`, which refuses to fake an SMS
send: set `SMSETHIOPIA_API_KEY`, and turn on `NOTIFICATION_WORKER_ENABLED=true`
so reminders go out. Only before the SMS Ethiopia key exists,
`ENVIRONMENT=staging` writes codes to the API log instead
(`docker compose logs backend | grep -i code`). Both need the master key file.

## Backups

```sh
docker compose exec -T postgres pg_dump -U endod endod | gzip > endod-$(date +%F).sql.gz
```

Health data in these dumps (and in the `records` volume) is encrypted:
reading a restored copy needs the master key, from its offline backup. Never
add `deploy/keys/` to these backups.

## Rollback

Check out the previous commit in `/opt/endod` and run the deploy command again.
Database changes are additive, so an older API runs on a newer schema. To a
release from before the encryption of health data, decrypt first (see
"Rollback of encryption").

## Events, payments and video (with the hospital service)

The same Compose project also runs the event bus between Endod and the
hospital service: Redis (`redis-1` master, `redis-2` replica) with three
Sentinels that promote the replica if the master fails, and
`events-worker`, which sends Endod's events (bookings, cancellations) and
applies the hospital service's (listings, decisions, refunds). They live on
the private network `endod-bus`, which the hospital service's Compose project
joins (`Hospital-service/deploy`). Events wait in each database while Redis
is unavailable, so nothing is lost.

Set in `deploy/.env` (see `.env.example`): `REDIS_PASSWORD`, the Chapa keys,
`PUBLIC_APP_URL`, the service fee and `JITSI_APP_SECRET`. Maps use
OpenStreetMap (no key); directions open the phone's maps app.

```sh
docker compose logs -f events-worker
docker compose exec sentinel-1 redis-cli -p 26379 sentinel get-master-addr-by-name endod
```

### Patient history, follow-ups, queues and sharing

The contract is `docs/history-events.md`. Hospitals link their patients to
Endod accounts, publish clinical records, set follow-ups and send queue
places; patients see all of it in the app, get SMS (follow-ups, "your turn
is near", booking decisions, refunds) and can share records with a partner
hospital.

- `internal-api` (the same image, `main_internal:app`) serves only
  `/internal/...` (with `X-Platform-Key`) and `/health`. It joins `endod-bus`
  with the alias `endod-platform-api` and an address from the network's
  dynamic range (no fixed IP), reads the `records` volume read-only and
  trusts no forwarded-address header. The patient API (`backend`) is not on
  `endod-bus` and does not serve `/internal`.
- Set `HOSPITAL_API_URL` (default `http://endod-hospital-api:8000`) and
  `PLATFORM_ADMIN_KEY` (the same value as the hospital service's) in
  `deploy/.env`. Without the key, file downloads stop and `/internal`
  refuses every request.
- Record files are kept in the `records` volume (`/data/records`, mounted in
  `backend` and `events-worker`, and read-only in `internal-api`). The events worker downloads them (checking
  size, SHA-256 and type) and retries failures with backoff; a record shows
  in the app while its file is still arriving. Back the volume up with the
  database.
- Texts go through the notification worker: turn it on
  (`NOTIFICATION_WORKER_ENABLED=true`) together with `SMSETHIOPIA_API_KEY`.

```sh
docker compose exec backend ls /data/records | head
docker compose logs events-worker | grep record_file
```

### Prescriptions at pharmacies

The contract is `docs/pharmacy.md`. Each hospital prescription gets a QR code
and a 6-digit code (texted once to the patient's verified phone); any
pharmacy can look it up and record what it gives, partly or in full, until
everything is given, it expires (30 days) or the hospital retracts it.

- The pharmacy site's server calls `internal-api` (`endod-platform-api` on
  `endod-bus`) at `/pharmacy/lookup` and `/pharmacy/dispense` with
  `X-Pharmacy-Key`, and passes the pharmacist's address in `X-Client-IP`
  (rate limits, counted in the database). The patient API does not serve
  `/pharmacy`.
- Set `PHARMACY_API_KEY` (the same value as the pharmacy site's) and
  `RX_SIGNING_KEY` in `deploy/.env`. Compose gives the pharmacy key to
  `internal-api` only, and the signing key to `internal-api` (checks QR codes)
  and `backend` (shows them in History). Without the pharmacy key, `/pharmacy`
  refuses every request; without the signing key, no QR is shown and only
  the code works. Keep `RX_SIGNING_KEY` once set: changing it voids every QR
  already issued.
- Each dispense texts the patient, adds an inbox item and sends
  `prescription.dispensed` to the hospital service (through the events worker).

### Video (deploy/jitsi)

Jitsi Meet at `meet.endod-health.com`, joined only with a token Endod signs
for one visit. `cp jitsi/.env.example jitsi/.env`, fill it in (the JWT
secret equals `JITSI_APP_SECRET`), open **UDP 10000** on the firewall, then
`cd jitsi && docker compose --env-file .env up -d`.

### Host names

`shared-nginx/endod.conf` answers for `endod-health.com`,
`hospital.endod-health.com` (the hospital portal) and
`meet.endod-health.com` (video). Each needs a proxied DNS record in
Cloudflare pointing at the server.

## Pharmacy site (pharmacy.endod-health.com)

The pharmacy site (github.com/Habtamu-Semagn/pharmacy_scanner) runs from
`deploy/pharmacy/docker-compose.yml`, with its code checked out at
`/opt/endod-pharmacy/app`:

    cd /opt/endod/deploy/pharmacy
    docker compose --env-file ../.env up -d --build

It reads `PHARMACY_API_KEY` from the platform's `.env` (the same key the
internal API checks) and calls only the platform's internal API on endod-bus.
The shared nginx sends it `pharmacy.endod-health.com` and sets
`X-Endod-Client-IP` (Cloudflare's header only for Cloudflare's addresses), the
only client address the site trusts for rate limits.

## Super admin (admin.endod-health.com)

The Endod super admin's API (github.com/Habtamu-Semagn/endod-superadmin)
calls `internal-api` on endod-bus (`http://endod-platform-api:8000`) at
`/internal/admin/...` with `X-Superadmin-Key`: account counts and search, suspend
and reactivate (signs the patient out and refuses sign-in, by password or a
reset by phone, until reactivated), card checks and a health report
(database, Redis, the events worker's heartbeat, dead letters, the outbox
backlog). Account data only: never health data.

Suspending signs the patient out and blocks sign-in and new hospital links;
prescriptions and existing hospital links keep working (continuity of care;
docs/history-events.md).

- Set `SUPERADMIN_API_KEY` in `deploy/.env` (`openssl rand -base64 48`; at
  least 32 characters, and a new value: not that of `ADMIN_API_KEY`, which
  is the platform's session secret, nor of any other key) and the same value
  as `SUPERADMIN_API_KEY` in the super admin's `.env`.
  Compose gives it to `internal-api` only. Unset, every `/internal/admin`
  request is refused (503).
- Then `docker compose up -d internal-api events-worker backend` (the new
  `users` columns are added on start; the worker starts its heartbeat).

## Encrypted backups

`deploy/backup/backup.sh` runs nightly (`endod-backup.timer`, 01:30 Addis
Ababa) and backs up all four databases (platform, hospital, admin,
organisation) and the uploaded-file volumes into `/opt/endod-backups/<time>/`.
Every part is streamed straight into `age`, encrypted to
`deploy/backup/recipient.pub`; nothing unencrypted is written to disk. The
private key is kept offline by Endod: without it the backups cannot be read,
so keep two safe copies of it. 14 days are kept on the server; set `OFFSITE`
(an rclone remote) in `/opt/endod/deploy/backup/backup.env` for an off-site copy.

Install: `apt install age`, copy `deploy/backup` to `/opt/endod/deploy/backup`,
then `cp endod-backup.service endod-backup.timer /etc/systemd/system/ &&
systemctl daemon-reload && systemctl enable --now endod-backup.timer`.

Restore a part: `age -d -i endod-backup-key db-platform.gz.age | gunzip > platform.sql`.
