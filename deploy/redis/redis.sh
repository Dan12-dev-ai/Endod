#!/bin/sh
# Starts one Redis server in the role the Sentinels currently give it.
#
# After a failover the master may be the other server; starting from a fixed
# role would make the old master a master again and drop what was written
# on the new one. So ask the Sentinels first (they keep the current master
# on their volumes); only when none answers, as on the very first start, use
# the default: redis-1 master, redis-2 its replica.
set -eu

: "${MY_IP:?}" "${DEFAULT_MASTER_IP:?}" "${REDIS_PASSWORD:?}"
SENTINELS="172.30.77.21 172.30.77.22 172.30.77.23"

master=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
    for sentinel in $SENTINELS; do
        if [ -n "${REDIS_SENTINEL_PASSWORD:-}" ]; then
            answer=$(REDISCLI_AUTH="$REDIS_SENTINEL_PASSWORD" timeout 2 redis-cli -h "$sentinel" -p 26379 \
                sentinel get-master-addr-by-name endod 2>/dev/null | head -1 || true)
        else
            answer=$(timeout 2 redis-cli -h "$sentinel" -p 26379 \
                sentinel get-master-addr-by-name endod 2>/dev/null | head -1 || true)
        fi
        case "$answer" in
            172.30.77.*) master="$answer"; break 2 ;;
        esac
    done
    sleep 2
done
master="${master:-$DEFAULT_MASTER_IP}"

# Event payloads can carry clinical data in plaintext while in flight; the
# platform deletes each entry once every consumer has acknowledged it
# (backend-v2/dedan_platform/eventbus.py). On disk: the append-only file only
# (no RDB snapshots: --save ""), rewritten every hour below so deleted entries
# do not linger in it. Durability is unchanged: the AOF is the persistence.
set -- redis-server --requirepass "$REDIS_PASSWORD" --masterauth "$REDIS_PASSWORD" \
    --appendonly yes --save "" --replica-announce-ip "$MY_IP"
if [ "$master" != "$MY_IP" ]; then
    set -- "$@" --replicaof "$master" 6379
fi
# Hourly AOF rewrite on this server (master or replica: each has its own file).
(
    while sleep 3600; do
        REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -h 127.0.0.1 -p 6379 bgrewriteaof >/dev/null 2>&1 || true
    done
) &
echo "starting as $([ "$master" = "$MY_IP" ] && echo master || echo "replica of $master")"
exec "$@"
