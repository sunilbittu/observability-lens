#!/usr/bin/env bash
# Durability test. Stops ClickHouse, sends logs, restarts the collector while
# ClickHouse is still down, sends more logs, then checks every record arrives.
# Usage: scripts/outage-test.sh [outage_seconds]   (default 300)
# This stops and starts the stack's ClickHouse. Do not run it against data you need online.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

outage="${1:-300}"
http="http://127.0.0.1:${TRACEMELT_OTLP_HTTP_PORT:-4318}"
health="http://127.0.0.1:${TRACEMELT_COLLECTOR_HEALTH_PORT:-13133}"
run="outage-$(date +%s)-$RANDOM"
fail=0

check() { if [ "$2" = "$3" ]; then echo "PASS  $1 ($3)"; else echo "FAIL  $1: expected $2, got $3"; fail=1; fi; }
ch() {
  docker compose exec -T clickhouse sh -c \
    'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" -q "$1"' _ "$1"
}
send() { # first last -> number of requests answered 200
  local ok=0 i code
  for i in $(seq "$1" "$2"); do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST "$http/v1/logs" \
      -H 'Content-Type: application/json' -H "Authorization: Bearer $TRACEMELT_INGEST_TOKEN" \
      --data '{"resourceLogs":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"'"$run"'"}}]},"scopeLogs":[{"logRecords":[{"timeUnixNano":"'"$(date +%s)"'000000000","body":{"stringValue":"record '"$i"'"}}]}]}]}')
    [ "$code" = 200 ] && ok=$((ok + 1))
  done
  echo "$ok"
}
wait_health() {
  local n=0
  until [ "$(curl -s -o /dev/null -w '%{http_code}' -m 2 "$health")" = 200 ] || [ $n -ge 30 ]; do sleep 1; n=$((n + 1)); done
}

start=$(date +%s)
docker compose stop clickhouse >/dev/null 2>&1
echo "clickhouse stopped, outage will last ${outage}s"

check "20 records accepted while clickhouse is down" 20 "$(send 1 20)"
sleep 10   # let the batch processor hand the records to the on-disk queue

docker compose restart collector >/dev/null 2>&1
wait_health
check "collector healthy after restart with clickhouse down" 200 "$(curl -s -o /dev/null -w '%{http_code}' -m 2 "$health")"
check "20 more records accepted after the restart" 20 "$(send 21 40)"

while [ $(( $(date +%s) - start )) -lt "$outage" ]; do sleep 5; done
check "collector still running at end of outage" running "$(docker compose ps --format '{{.State}}' collector)"

docker compose start clickhouse >/dev/null 2>&1
echo "clickhouse started after $(( $(date +%s) - start ))s"

n=0; got=0
while [ $n -lt 120 ]; do
  got=$(ch "SELECT uniqExact(Body) FROM otel_logs WHERE ServiceName='$run'" 2>/dev/null || echo 0)
  [ "$got" = 40 ] && break
  sleep 2; n=$((n + 1))
done
check "distinct records in clickhouse" 40 "$got"
echo "recovered after $((n * 2))s"
check "no duplicate rows" 40 "$(ch "SELECT count() FROM otel_logs WHERE ServiceName='$run'")"

[ $fail = 0 ] && echo "outage test: all checks passed" || { echo "outage test: FAILED"; exit 1; }
