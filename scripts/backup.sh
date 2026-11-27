#!/usr/bin/env bash
# Backs up the telemetry database to ./backups/<name>.zip on the host.
# The archive is a password-protected zip; the password is TRACEMELT_BACKUP_PASSWORD in .env.
# Keep .env and the archives in different places: one without the other is useless or exposed.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${TRACEMELT_BACKUP_PASSWORD:?add TRACEMELT_BACKUP_PASSWORD to .env}"

db="${TRACEMELT_CLICKHOUSE_DB:-otel}"
name="tracemelt-$(date -u +%Y%m%dT%H%M%SZ)"
inside="/var/lib/clickhouse/backups/$name.zip"

# BACKUP and RESTORE do not accept a bound parameter for the password, so it is restricted
# to letters and digits and substituted for __PW__ inside the container, off the host's process list.
case "$TRACEMELT_BACKUP_PASSWORD" in *[!A-Za-z0-9]*) echo "TRACEMELT_BACKUP_PASSWORD may contain only letters and digits" >&2; exit 1;; esac
ch() {
  docker compose exec -T -e BACKUP_PASSWORD="$TRACEMELT_BACKUP_PASSWORD" clickhouse sh -c \
    'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" -q "$(printf "%s" "$1" | sed "s/__PW__/$BACKUP_PASSWORD/")"' _ "$1" </dev/null
}

mkdir -p backups
ch "BACKUP DATABASE \`$db\` TO File('$inside') SETTINGS password = '__PW__'" >/dev/null
docker compose cp "clickhouse:$inside" "backups/$name.zip" >/dev/null 2>&1
docker compose exec -T clickhouse rm -f "$inside"
chmod 600 "backups/$name.zip"
echo "wrote backups/$name.zip ($(du -h "backups/$name.zip" | cut -f1))"
