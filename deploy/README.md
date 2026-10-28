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
In production (`ENVIRONMENT=production`) they also refuse to start without a
usable key; outside production, with no key file, a published development key
is used (never for real data).

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
3. Deploy as usual (Deploy / update, below). The three services must show
   the same key id:

   ```sh
   for s in backend internal-api events-worker; do
     docker compose exec $s python -c "from dedan_platform import crypto; print(crypto.require_master_key())"
   done
   ```
4. Encrypt what was stored before, then check that nothing is left:

   ```sh
   docker compose exec backend python -m dedan_platform.tools encrypt-existing
   docker compose exec backend python -m dedan_platform.tools check    # every line "ok", exit 0
   ```

   `encrypt-existing` works in batches and can be run again at any time;
   values stored before stay readable until it has run.

A patient's data key can be replaced (re-encrypting their data):
`docker compose exec backend python -m dedan_platform.tools rotate-key --user DE123456`
(add `--purge-old` to delete the old key once nothing uses it).

### Rollback of encryption

To a release from before encryption, which cannot read encrypted values:

```sh
docker compose stop backend internal-api events-worker
docker compose run --rm --no-deps backend python -m dedan_platform.tools decrypt-existing --yes
git checkout <the previous release>
docker compose -f docker-compose.yml -f shared-nginx/docker-compose.override.yml --env-file .env up -d --build
```

(Or restore the backups from step 2, losing what was written since.) The
schema changes are additive (`user_keys`, two `user_id` columns, wider text
columns), so the older release runs on it. Keep the master key and its
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

`ENVIRONMENT=staging` works before the SMS Ethiopia key exists: codes are
written to the API log (`docker compose logs backend | grep -i code`).
Switch to `ENVIRONMENT=production` once `SMSETHIOPIA_API_KEY` is set
(production refuses to fake a send), and turn on
`NOTIFICATION_WORKER_ENABLED=true` at the same time so reminders go out.

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
