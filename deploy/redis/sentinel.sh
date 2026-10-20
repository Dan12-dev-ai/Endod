#!/bin/sh
# Starts one Redis Sentinel. Sentinel rewrites its own config file as the
# master changes, so the file lives on the container's volume: the base is
# written only the first time (keeping what Sentinel learned since), and the
# passwords are refreshed on every start so a changed password takes effect.
set -eu

: "${SENTINEL_IP:?}" "${REDIS_PASSWORD:?}"
CONF=/data/sentinel.conf

if [ ! -s "$CONF" ]; then
    cat > "$CONF" <<EOF
port 26379
dir /data
sentinel announce-ip ${SENTINEL_IP}
sentinel monitor endod 172.30.77.11 6379 2
sentinel down-after-milliseconds endod 5000
sentinel failover-timeout endod 30000
sentinel parallel-syncs endod 1
EOF
fi

# Credentials: to the Redis servers, to clients, and between Sentinels
# (which must log in to each other to agree that the master is down).
sed -i -e '/^sentinel auth-pass /d' -e '/^requirepass /d' -e '/^sentinel sentinel-pass /d' "$CONF"
echo "sentinel auth-pass endod ${REDIS_PASSWORD}" >> "$CONF"
if [ -n "${REDIS_SENTINEL_PASSWORD:-}" ]; then
    echo "requirepass ${REDIS_SENTINEL_PASSWORD}" >> "$CONF"
    echo "sentinel sentinel-pass ${REDIS_SENTINEL_PASSWORD}" >> "$CONF"
fi

exec redis-sentinel "$CONF"
