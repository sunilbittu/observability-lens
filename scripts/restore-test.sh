#!/usr/bin/env bash
# Proves a backup can be read: restores it into a scratch database next to the live one,
# counts the rows, reads one back, then drops the scratch database. The live data is not touched.
# Usage: scripts/restore-test.sh backups/<name>.zip
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${TRACEMELT_BACKUP_PASSWORD:?add TRACEMELT_BACKUP_PASSWORD to .env}"
archive="${1:?usage: scripts/restore-test.sh backups/<name>.zip}"
[ -f "$archive" ] || { echo "no such file: $archive" >&2; exit 1; }

db="${TRACEMELT_CLICKHOUSE_DB:-otel}"
scratch="tracemelt_restore_check"
inside="/var/lib/clickhouse/backups/restore-check.zip"
fail=0

# BACKUP and RESTORE do not accept a bound parameter for the password, so it is restricted
# to letters and digits and substituted for __PW__ inside the container, off the host's process list.
case "$TRACEMELT_BACKUP_PASSWORD" in *[!A-Za-z0-9]*) echo "TRACEMELT_BACKUP_PASSWORD may contain only letters and digits" >&2; exit 1;; esac
ch() {
  docker compose exec -T -e BACKUP_PASSWORD="$TRACEMELT_BACKUP_PASSWORD" clickhouse sh -c \
    'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" -q "$(printf "%s" "$1" | sed "s/__PW__/$BACKUP_PASSWORD/")"' _ "$1" </dev/null
}
check() { if [ "$2" = "$3" ]; then echo "PASS  $1 ($3)"; else echo "FAIL  $1: expected $2, got $3"; fail=1; fi; }
cleanup() {
  ch "DROP DATABASE IF EXISTS $scratch SYNC" >/dev/null 2>&1 || true
  docker compose exec -T clickhouse rm -f "$inside" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker compose exec -T clickhouse mkdir -p /var/lib/clickhouse/backups
docker compose cp "$archive" "clickhouse:$inside" >/dev/null 2>&1
docker compose exec -T -u root clickhouse chown clickhouse:clickhouse "$inside"

wrong=$(docker compose exec -T clickhouse sh -c \
  'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" -q "$1" >/dev/null 2>&1 && echo restored || echo refused' _ \
  "RESTORE DATABASE \`$db\` AS $scratch FROM File('$inside') SETTINGS password = 'not-the-password'" </dev/null)
check "restore with a wrong password is refused" refused "$wrong"
ch "DROP DATABASE IF EXISTS $scratch SYNC" >/dev/null

ch "RESTORE DATABASE \`$db\` AS $scratch FROM File('$inside') SETTINGS password = '__PW__'" >/dev/null
check "restore completed" 1 "$(ch "SELECT count() FROM system.databases WHERE name = '$scratch'")"

echo "rows restored (live count in brackets):"
for table in otel_logs otel_traces otel_metrics_gauge otel_metrics_sum alert_events; do
  restored=$(ch "SELECT count() FROM $scratch.$table" 2>/dev/null || echo missing)
  live=$(ch "SELECT count() FROM \`$db\`.$table" 2>/dev/null || echo missing)
  echo "  $table: $restored ($live)"
done

check "restored logs are not empty"   1 "$(ch "SELECT toUInt8(count() > 0) FROM $scratch.otel_logs")"
check "restored traces are not empty" 1 "$(ch "SELECT toUInt8(count() > 0) FROM $scratch.otel_traces")"
check "a restored log record reads back" 1 "$(ch "SELECT toUInt8(length(Body) > 0 AND ServiceName != '') FROM $scratch.otel_logs ORDER BY Timestamp DESC LIMIT 1")"
check "a restored trace reads back by id" 1 "$(ch "SELECT toUInt8(count() > 0) FROM $scratch.otel_traces WHERE TraceId = (SELECT any(TraceId) FROM $scratch.otel_traces)")"

[ $fail = 0 ] && echo "restore test: all checks passed" || { echo "restore test: FAILED"; exit 1; }
