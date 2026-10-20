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
