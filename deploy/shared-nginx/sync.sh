#!/bin/sh
# Keeps Endod's config inside the server's existing nginx container.
#
# That container's own config is generated when it starts, so a redeploy of
# it drops files added from outside. Run every minute (endod-nginx-sync.timer):
# it copies Endod's files in when they are missing or changed, checks the
# whole config with `nginx -t`, and reloads only if the check passes.
set -eu

CONTAINER="${NGINX_CONTAINER:-eyita-nginx-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TLS_DIR="$HERE/tls"

docker inspect "$CONTAINER" >/dev/null 2>&1 || exit 0

# Endod's own origin certificate (self-signed; Cloudflare "Full" accepts it).
# Made again when it lacks a host name added since (hospital., meet.).
if ! openssl x509 -in "$TLS_DIR/origin.crt" -noout -text 2>/dev/null | grep -q "DNS:api.endod-health.com"; then
    mkdir -p "$TLS_DIR"
    openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
        -subj "/CN=endod-health.com" \
        -addext "subjectAltName=DNS:endod-health.com,DNS:www.endod-health.com,DNS:hospital.endod-health.com,DNS:meet.endod-health.com,DNS:pharmacy.endod-health.com,DNS:admin.endod-health.com,DNS:organisation.endod-health.com,DNS:api.endod-health.com" \
        -keyout "$TLS_DIR/origin.key" -out "$TLS_DIR/origin.crt" 2>/dev/null
    chmod 600 "$TLS_DIR/origin.key"
fi

# The edge key: nginx adds it to every request it forwards (X-Endod-Edge-Key),
# and the apps on the shared network refuse requests without it, so other
# containers on that network cannot call them directly and forge the client
# address. Made once; the apps get the same value as EDGE_SHARED_SECRET.
if [ ! -s "$TLS_DIR/edge.key" ]; then
    mkdir -p "$TLS_DIR"
    (umask 077; openssl rand -hex 32 > "$TLS_DIR/edge.key")
fi
(umask 077; printf 'proxy_set_header X-Endod-Edge-Key "%s";\n' "$(cat "$TLS_DIR/edge.key")" > "$TLS_DIR/edge-key.conf")

same() {  # same <local file> <path in container>
    docker exec "$CONTAINER" cat "$2" 2>/dev/null | cmp -s - "$1"
}

if same "$HERE/endod.conf" /etc/nginx/conf.d/endod.conf \
    && same "$HERE/proxy.conf" /etc/nginx/endod/proxy.conf \
    && same "$TLS_DIR/origin.crt" /etc/nginx/endod/origin.crt     && same "$TLS_DIR/edge-key.conf" /etc/nginx/endod/edge-key.conf     && same "$HERE/integrations-proxy.conf" /etc/nginx/endod/integrations-proxy.conf; then
    exit 0
fi

docker exec "$CONTAINER" mkdir -p /etc/nginx/endod
docker cp "$HERE/proxy.conf" "$CONTAINER:/etc/nginx/endod/proxy.conf"
docker cp "$HERE/integrations-proxy.conf" "$CONTAINER:/etc/nginx/endod/integrations-proxy.conf"
docker cp "$TLS_DIR/origin.crt" "$CONTAINER:/etc/nginx/endod/origin.crt"
docker cp "$TLS_DIR/origin.key" "$CONTAINER:/etc/nginx/endod/origin.key"
docker cp "$TLS_DIR/edge-key.conf" "$CONTAINER:/etc/nginx/endod/edge-key.conf"
docker cp "$HERE/endod.conf" "$CONTAINER:/etc/nginx/conf.d/endod.conf"

if docker exec "$CONTAINER" nginx -t >/dev/null 2>&1; then
    docker exec "$CONTAINER" nginx -s reload
    echo "endod nginx config installed and reloaded"
else
    # Never leave the shared nginx with a config that fails its check.
    docker exec "$CONTAINER" rm -f /etc/nginx/conf.d/endod.conf
    echo "endod nginx config rejected by nginx -t; removed" >&2
    exit 1
fi
