#!/usr/bin/env bash
# Smoke test against a running stack: ingest auth, every signal stored, query API
# auth and results, and the read-only user's guardrails.
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

# --- query API -------------------------------------------------------------
api="http://127.0.0.1:${TRACEMELT_API_PORT:-8000}/api"
get_code() { # path token -> http status
  local auth=()
  [ -n "$2" ] && auth=(-H "Authorization: Bearer $2")
  curl -s -o /dev/null -w '%{http_code}' -m 15 ${auth[@]+"${auth[@]}"} "$api$1"
}
get() { curl -s -m 15 -H "Authorization: Bearer $TRACEMELT_API_TOKEN" "$api$1"; }
count() { python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'; }
reader() { # runs SQL as the API's read-only user, prints the ClickHouse error code or "ok"
  docker compose exec -T clickhouse sh -c \
    'clickhouse-client --user tracemelt_reader --password "$TRACEMELT_CLICKHOUSE_READER_PASSWORD" --database "$CLICKHOUSE_DB" -q "$1" </dev/null >/dev/null 2>/tmp/err && echo ok || grep -o "Code: [0-9]*" /tmp/err | head -1' _ "$1"
}

check "api health"                        200 "$(get_code /health '')"
check "api without token rejected"        401 "$(get_code /traces '')"
check "api with wrong token rejected"     401 "$(get_code /traces wrong-token)"
check "api with ingest token rejected"    401 "$(get_code /traces "$TRACEMELT_INGEST_TOKEN")"
check "api rejects malformed trace id"    422 "$(get_code "/traces/not-a-trace-id" "$TRACEMELT_API_TOKEN")"
check "api unknown trace is 404"          404 "$(get_code "/traces/00000000000000000000000000000000" "$TRACEMELT_API_TOKEN")"
check "api lists the trace"               1 "$(get "/traces?service=$run" | count)"
check "api returns the trace's span"      1 "$(get "/traces/$trace_id" | count)"
check "api finds the log by trace id"     1 "$(get "/logs?trace_id=$trace_id" | count)"
check "api finds the log by text"         1 "$(get "/logs?service=$run&q=SMOKE%20LOG" | count)"
check "api lists the event"               1 "$(get "/events?service=$run&name=order.placed" | count)"
check "api lists the service"             1 "$(get "/services" | python3 -c 'import json,sys; print(sum(1 for r in json.load(sys.stdin) if r["service"]==sys.argv[1]))' "$run")"
check "api charts the gauge"              1 "$(get "/metrics/gauge?name=smoke.gauge&service=$run" | count)"

ui="http://127.0.0.1:${TRACEMELT_API_PORT:-8000}"
jar=$(mktemp)
check "ui shell is served"                200 "$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$ui/")"
check "ui sends a content security policy" 1 "$(curl -s -D - -o /dev/null -m 10 "$ui/" | grep -ci "^content-security-policy: default-src 'self'")"
check "sign in with wrong token rejected" 401 "$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST "$api/session" -H 'Content-Type: application/json' --data '{"token":"wrong"}')"
check "sign in sets a session"            204 "$(curl -s -o /dev/null -w '%{http_code}' -m 10 -c "$jar" -X POST "$api/session" -H 'Content-Type: application/json' --data '{"token":"'"$TRACEMELT_API_TOKEN"'"}')"
check "session cookie is HttpOnly"        1 "$(grep -c '#HttpOnly_' "$jar")"
check "session cookie reads the api"      200 "$(curl -s -o /dev/null -w '%{http_code}' -m 10 -b "$jar" "$api/traces")"
rm -f "$jar"

check "reader can select"                 ok          "$(reader "SELECT count() FROM otel_logs")"
check "reader cannot insert"              "Code: 497" "$(reader "INSERT INTO otel_logs (Body) SELECT 'x'")"
check "reader cannot drop"                "Code: 497" "$(reader "DROP TABLE otel_logs")"
check "reader cannot raise its limits"    "Code: 164" "$(reader "SET max_execution_time = 0")"
check "reader cannot read other databases" "Code: 497" "$(reader "SELECT count() FROM system.users")"
check "slow query killed by time limit"   "Code: 159" "$(reader "SELECT count() FROM numbers(100000000000) WHERE sipHash64(number) = 1")"
check "large result killed by row limit"  "Code: 396" "$(reader "SELECT number FROM numbers(1000000)")"

[ $fail = 0 ] && echo "smoke: all checks passed" || { echo "smoke: FAILED"; exit 1; }
