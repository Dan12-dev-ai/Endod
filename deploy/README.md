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

## Rollback

Check out the previous commit in `/opt/endod` and run the deploy command again.
Database changes are additive, so an older API runs on a newer schema.

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
