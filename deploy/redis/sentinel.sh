#!/bin/sh
# Starts one Redis Sentinel. Sentinel rewrites its own config file as the
# master changes, so the file lives on the container's volume: it is written
# here only the first time and kept across restarts.
set -eu

: "${SENTINEL_IP:?}" "${REDIS_PASSWORD:?}"
CONF=/data/sentinel.conf

if [ ! -s "$CONF" ]; then
    cat > "$CONF" <<EOF
port 26379
dir /data
sentinel announce-ip ${SENTINEL_IP}
sentinel monitor endod 172.30.77.11 6379 2
sentinel auth-pass endod ${REDIS_PASSWORD}
sentinel down-after-milliseconds endod 5000
sentinel failover-timeout endod 30000
sentinel parallel-syncs endod 1
EOF
    if [ -n "${REDIS_SENTINEL_PASSWORD:-}" ]; then
        echo "requirepass ${REDIS_SENTINEL_PASSWORD}" >> "$CONF"
    fi
fi

exec redis-sentinel "$CONF"
