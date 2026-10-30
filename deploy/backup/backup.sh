#!/usr/bin/env bash
# Nightly encrypted backup of every Endod service on this server.
#
# Each database dump and file volume is streamed straight into `age`, so no
# unencrypted copy is ever written to disk. Only the public key
# (recipient.pub) is on the server; the private key that opens the backups
# is kept offline by Endod. Backups older than KEEP_DAYS are deleted here;
# OFFSITE (an rclone remote such as "r2:endod-backups") gets a copy when set.
#
# Restore one part:  age -d -i endod-backup-key <part>.age | gunzip > part.sql
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RECIPIENT="${RECIPIENT:-$HERE/recipient.pub}"
OUT_ROOT="${OUT_ROOT:-/opt/endod-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
OFFSITE="${OFFSITE:-}"

command -v age >/dev/null || { echo "age is not installed (apt install age)" >&2; exit 1; }
[ -s "$RECIPIENT" ] || { echo "missing $RECIPIENT" >&2; exit 1; }

STAMP=$(date -u +%Y-%m-%dT%H%MZ)
OUT="$OUT_ROOT/$STAMP"
umask 077
mkdir -p "$OUT"
FAILED=0

enc() {  # enc <name>: stdin -> gzip -> age -> $OUT/<name>.gz.age
    gzip -c | age -R "$RECIPIENT" > "$OUT/$1.gz.age"
}

db() {  # db <name> <compose dir> <env file or -> <user> <database>
    name=$1; dir=$2; env=$3; user=$4; database=$5
    [ -d "$dir" ] || { echo "skip $name: $dir missing"; return 0; }
    set -- docker compose
    [ "$env" = "-" ] || set -- "$@" --env-file "$env"
    if (cd "$dir" && "$@" exec -T postgres pg_dump -U "$user" "$database" < /dev/null) | enc "db-$name"; then
        echo "db $name: $(stat -c %s "$OUT/db-$name.gz.age") bytes"
    else
        echo "db $name: FAILED" >&2; FAILED=1
    fi
}

vol() {  # vol <docker volume>
    docker volume inspect "$1" >/dev/null 2>&1 || { echo "skip volume $1: missing"; return 0; }
    if docker run --rm -v "$1:/v:ro" alpine:3.20 tar -C /v -cf - . | enc "files-$1"; then
        echo "files $1: $(stat -c %s "$OUT/files-$1.gz.age") bytes"
    else
        echo "files $1: FAILED" >&2; FAILED=1
    fi
}

db platform     /opt/endod/deploy                   -                           endod    endod
db hospital     /opt/endod-hospital/deploy          /opt/endod-hospital/deploy/.env hospital hospital
db admin        /opt/endod-admin/app/deploy         /opt/endod-admin/.env       postgres admin
db organisation /opt/endod-organisation/app/deploy  /opt/endod-organisation/.env postgres organisation

vol endod_records
vol endod-hospital_files
vol endod-organisation_organisation_receipts

# Every part must be a real age file, not an empty one left by a failure.
for f in "$OUT"/*.age; do
    head -c 21 "$f" | grep -q "age-encryption.org/v1" || { echo "not encrypted: $f" >&2; FAILED=1; }
done

if [ -n "$OFFSITE" ] && command -v rclone >/dev/null; then
    rclone copy "$OUT" "$OFFSITE/$STAMP" && echo "copied off-site to $OFFSITE/$STAMP" || { echo "off-site copy FAILED" >&2; FAILED=1; }
fi

find "$OUT_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "backup $STAMP: $(du -sh "$OUT" | cut -f1) in $OUT$( [ "$FAILED" = 0 ] && echo ', all parts ok' || echo ', WITH FAILURES')"
exit "$FAILED"
