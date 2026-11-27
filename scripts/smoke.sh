#!/usr/bin/env bash
# Ingest smoke test against a running stack: auth is enforced and every signal lands in ClickHouse.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

http="http://127.0.0.1:${TRACEMELT_OTLP_HTTP_PORT:-4318}"
health="http://127.0.0.1:${TRACEMELT_COLLECTOR_HEALTH_PORT:-13133}"
run="smoke-$(date +%s)-$RANDOM"
trace_id=$(openssl rand -hex 16)
span_id=$(openssl rand -hex 8)
now="$(date +%s)000000000"
fail=0

check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "PASS  $1 ($3)"; else echo "FAIL  $1: expected $2, got $3"; fail=1; fi
}
post() { # path token body -> http status
  local auth=()
  [ -n "$2" ] && auth=(-H "Authorization: Bearer $2")
  curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST "$http$1" \
    -H 'Content-Type: application/json' ${auth[@]+"${auth[@]}"} --data "$3"
}
ch() {
  docker compose exec -T clickhouse sh -c \
    'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" -q "$1"' _ "$1"
}
wait_count() { # name query
  local n=0 got=0
  while [ $n -lt 30 ]; do
    got=$(ch "$2" 2>/dev/null || echo 0)
    [ "$got" = "1" ] && break
    sleep 1; n=$((n+1))
  done
  check "$1" 1 "$got"
}

res='{"attributes":[{"key":"service.name","value":{"stringValue":"'"$run"'"}}]}'
traces='{"resourceSpans":[{"resource":'"$res"',"scopeSpans":[{"spans":[{"traceId":"'"$trace_id"'","spanId":"'"$span_id"'","name":"smoke","kind":2,"startTimeUnixNano":"'"$now"'","endTimeUnixNano":"'"$now"'"}]}]}]}'
logs='{"resourceLogs":[{"resource":'"$res"',"scopeLogs":[{"logRecords":[
 {"timeUnixNano":"'"$now"'","severityText":"INFO","body":{"stringValue":"smoke log"},"traceId":"'"$trace_id"'","spanId":"'"$span_id"'"},
 {"timeUnixNano":"'"$now"'","severityText":"INFO","body":{"stringValue":"order.placed"},"attributes":[
   {"key":"tracemelt.event","value":{"stringValue":"true"}},{"key":"event.name","value":{"stringValue":"order.placed"}}]}]}]}]}'
metrics='{"resourceMetrics":[{"resource":'"$res"',"scopeMetrics":[{"metrics":[{"name":"smoke.gauge","gauge":{"dataPoints":[{"timeUnixNano":"'"$now"'","asDouble":1}]}}]}]}]}'

check "collector health"            200 "$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$health")"
check "logs without token rejected"   401 "$(post /v1/logs '' "$logs")"
check "logs with wrong token rejected" 401 "$(post /v1/logs wrong-token "$logs")"
check "traces without token rejected" 401 "$(post /v1/traces '' "$traces")"
check "metrics without token rejected" 401 "$(post /v1/metrics '' "$metrics")"
check "traces accepted"  200 "$(post /v1/traces  "$TRACEMELT_INGEST_TOKEN" "$traces")"
check "logs accepted"    200 "$(post /v1/logs    "$TRACEMELT_INGEST_TOKEN" "$logs")"
check "metrics accepted" 200 "$(post /v1/metrics "$TRACEMELT_INGEST_TOKEN" "$metrics")"

wait_count "trace stored"               "SELECT count() FROM otel_traces WHERE ServiceName='$run' AND TraceId='$trace_id'"
wait_count "log stored with trace id"   "SELECT count() FROM otel_logs WHERE ServiceName='$run' AND Body='smoke log' AND TraceId='$trace_id'"
wait_count "event stored as tagged log" "SELECT count() FROM otel_logs WHERE ServiceName='$run' AND LogAttributes['tracemelt.event']='true' AND LogAttributes['event.name']='order.placed'"
wait_count "gauge stored"               "SELECT count() FROM otel_metrics_gauge WHERE ServiceName='$run' AND MetricName='smoke.gauge'"
check "rejected requests stored nothing" 2 "$(ch "SELECT count() FROM otel_logs WHERE ServiceName='$run'")"

[ $fail = 0 ] && echo "smoke: all checks passed" || { echo "smoke: FAILED"; exit 1; }
