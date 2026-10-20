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

set -- redis-server --requirepass "$REDIS_PASSWORD" --masterauth "$REDIS_PASSWORD" \
    --appendonly yes --replica-announce-ip "$MY_IP"
if [ "$master" != "$MY_IP" ]; then
    set -- "$@" --replicaof "$master" 6379
fi
echo "starting as $([ "$master" = "$MY_IP" ] && echo master || echo "replica of $master")"
exec "$@"
