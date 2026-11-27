# Query API reference

!!! warning "Status: prototype"
    Verified on 2026-11-27 by `scripts/smoke.sh` and the unit tests in
    `api/tests`. Paths and response fields may change without notice. Applies
    to: `dev`.

The query API is a read-only HTTP service over the `otel_*` tables. It listens
on `127.0.0.1:8000` by default.

## Authentication

Every endpoint except `/api/health` and `POST /api/session` requires
`Authorization: Bearer <TRACEMELT_API_TOKEN>` or the session cookie described
below. A missing or wrong token returns
`401`. The ingest token is not accepted.

This single shared token is a temporary guard. There are no users, roles or
audit log yet.

```bash
TOKEN=$(grep TRACEMELT_API_TOKEN .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/services"
```

Expected output after the smoke test has run, with your own service names:

```text
[{"service":"smoke-1795785046-21234","spans":1,"error_spans":0}]
```

## Browser session

The web UI signs in with `POST /api/session` and a JSON body
`{"token": "<TRACEMELT_API_TOKEN>"}`. A correct token returns `204` and sets
the cookie `tracemelt_session` (`HttpOnly`, `SameSite=Strict`, 12 hours). The
cookie value is derived from the token and is not the token. `DELETE
/api/session` clears it. `GET /api/session` returns `{"signed_in": true}` or
`401`.

## Endpoints

All endpoints are `GET` and return a JSON array.

| Path | Parameters | Returns |
|---|---|---|
| `/api/health` | none | `{"status":"ok"}`, or `503` when ClickHouse does not answer. No token needed. |
| `/api/services` | `since_minutes` | Services with span and error span counts. |
| `/api/traces` | `since_minutes`, `limit`, `service`, `errors_only` | Recent traces, newest first. `service` keeps traces with at least one span from that service and still reports the whole trace. |
| `/api/traces/{trace_id}` | none | Every span of one trace, up to 5000. `404` if unknown. |
| `/api/logs` | `since_minutes`, `limit`, `service`, `q`, `trace_id` | Log records, newest first. `q` is a case-insensitive substring match on the body. |
| `/api/events` | `since_minutes`, `limit`, `service`, `name` | Log records tagged `tracemelt.event = "true"`. |
| `/api/metrics` | `since_minutes` | Gauge and sum metric names. `chartable` is `1` for gauges only. |
| `/api/metrics/gauge` | `name` (required), `since_minutes`, `step_seconds`, `service` | Per-service `avg`, `min` and `max` of a gauge per time bucket. |

## Parameter limits

Requests outside these bounds return `422` before any query runs.

| Parameter | Bound |
|---|---|
| `since_minutes` | 1 to 10080 (7 days), default 60 |
| `limit` | 1 to 1000 |
| `service`, `q`, `name` (events) | at most 200 characters |
| `name` (gauge) | 1 to 255 characters |
| `trace_id` | exactly 32 lowercase hex characters |
| `step_seconds` | 10 to 3600, and at most 1500 buckets per request |

## Query guardrails

The API connects as the ClickHouse user `tracemelt_reader`. Its limits are set
in the server profile with `readonly = 1`, so the API process cannot raise
them.

| Limit | Value | API response when hit |
|---|---|---|
| `max_execution_time` | 10 seconds | `504` |
| `max_memory_usage` | 1 GB | `422` |
| `max_result_rows` | 10000 | `422` |
| Concurrent queries for the user | 16 | `502` |
| Concurrent HTTP requests | 32 | `503` |

The user can only `SELECT` from the telemetry database. The smoke test checks
that it cannot insert, drop, change its settings or read `system.users`, and
that a slow query and an oversized result are both stopped.

All SQL is fixed text with server-side bound parameters. User input is never
concatenated into a statement.

## Limitations

- Sum metrics, histograms and percentiles cannot be queried. Only gauges are
  charted.
- `/api/traces` reports the longest span as `duration_ns`, which equals the
  trace duration only when the root span covers the whole trace.
- `q` is a substring scan, not an indexed search. On large tables it will hit
  the 10 second limit.
- No pagination, no caching, no CORS, no TLS.
- Error responses carry a short reason only. Details are in `docker compose logs api`.

## Related

- [Configuration reference](../reference/configuration.md)
- [Quickstart](../getting-started/quickstart.md)
