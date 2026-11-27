# Quickstart

!!! warning "Status: prototype"
    Verified on 2026-11-27 with Docker 29.5.3, Compose v5.1.4, collector
    contrib 0.166.0 and ClickHouse 26.8.48.11 on macOS (arm64). This covers
    OTLP ingest into ClickHouse, the query API, the web UI and alerting.
    The SDKs have their own page. Applies to: `dev`.

This tutorial starts the single-node stack and proves that authenticated
OTLP data reaches ClickHouse.

## Before you start

You need Docker with Compose v2, `curl`, `openssl` and `python3`. Ports `4317`,
`4318`, `8000` and `13133` must be free on loopback, or change them in `.env` after step 1.

## 1. Generate secrets

```bash
scripts/init-env.sh
```

Expected output:

```text
wrote .env
```

The script generates an ingest token and a ClickHouse password. It refuses to
overwrite an existing `.env`.

## 2. Start the stack

```bash
docker compose --profile demo up -d --build
docker compose ps --format '{{.Service}}\t{{.State}}'
```

Expected output, after the images have been pulled:

```text
alerts	running
api	running
clickhouse	running
collector	running
demo	running
webhook-sink	running
```

The `demo` profile adds a sample workload (three services that send traces,
logs, events and gauges) and a receiver for alert webhooks. Leave the flag
out to run without them.

## 3. Run the smoke test

```bash
scripts/smoke.sh
```

Expected output:

```text
PASS  collector health (200)
PASS  logs without token rejected (401)
...
PASS  slow query killed by time limit (Code: 159)
PASS  large result killed by row limit (Code: 396)
smoke: all checks passed
```

There are 60 `PASS` lines. Some checks wait for the next metrics scrape or
alert evaluation, so the test takes up to two minutes. Any `FAIL` line names the check and what it got.

The test sends one span, two log records (one of them an event) and one gauge
over OTLP HTTP, reads them back from ClickHouse and through the query API,
checks that the API's database user is read-only and limited, that secrets
are masked and that the stack reports its own metrics, and checks that
an alert rule fires, its webhook is delivered and a webhook to the cloud
metadata address is blocked.

## 4. Send your own telemetry

Use the [Node.js or Python SDK](../instrumentation/sdks.md), or point any
OpenTelemetry SDK at the collector:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer $(grep TRACEMELT_INGEST_TOKEN .env | cut -d= -f2)"
```

## 5. Look at it

Open `http://127.0.0.1:8000/`, paste the value of `TRACEMELT_API_TOKEN` from
`.env` and sign in. With the demo workload running, **Overview** lists
`storefront`, `inventory` and `payments`. See [Use the web UI](../using-tracemelt/ui.md).

The same data is available from the query API:

```bash
TOKEN=$(grep TRACEMELT_API_TOKEN .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/services"
```

Expected output, with your own service names:

```text
[{"service":"smoke-1795785046-21234","spans":1,"error_spans":0}]
```

## 6. See an alert

The demo payments service fails for 3 minutes out of every 12. When it does,
the shipped rules fire and the receiver prints what it was sent:

```bash
docker compose logs webhook-sink
```

Expected output within 12 minutes of starting the demo:

```text
webhook-sink-1  | alert 1: payments-failed-spans: failed spans for payments is 40, which is > 5 over 60s
```

The same firings are listed under **Alerts** in the UI. See
[Alert rules and limitations](../alerting/rules.md) to write your own.

## If something fails

| Symptom | Cause and fix |
|---|---|
| `required variable ... is missing a value: run scripts/init-env.sh` | No `.env`. Run step 1. |
| `port is already allocated` | Another process holds an OTLP port. Change the `TRACEMELT_*_PORT` values in `.env`. |
| `alerts` keeps restarting | The rules file is invalid. `docker compose logs alerts` names the rule and the reason. |
| Smoke test fails at `collector health` | The collector is still starting or is restarting. Check `docker compose logs collector`. |
| `schema-init` exits with an error | ClickHouse was not reachable when the tables were being created. Check `docker compose logs schema-init clickhouse`, then run `docker compose up -d` again. |

## Stop and clean up

```bash
docker compose down        # keeps data
docker compose down -v     # deletes stored telemetry and the collector queue
```

## Related

- [Node.js and Python SDKs](../instrumentation/sdks.md)
- [Use the web UI](../using-tracemelt/ui.md)
- [Alert rules and limitations](../alerting/rules.md)
- [Query API reference](../api/query-api.md): endpoints and guardrails.
- [Configuration reference](../reference/configuration.md): ports, environment variables, limits.
- [Roadmap](../project/roadmap.md)
