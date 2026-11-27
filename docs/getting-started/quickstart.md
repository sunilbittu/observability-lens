# Quickstart

!!! warning "Status: prototype, ingest only"
    Verified on 2026-11-27 with Docker 29.5.3, Compose v5.1.4, collector
    contrib 0.166.0 and ClickHouse 26.8.48.11 on macOS (arm64). This covers
    OTLP ingest into ClickHouse and the query API. There is no UI, alerting
    or SDK yet. Applies to: `dev`.

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
docker compose up -d --build
docker compose ps --format '{{.Service}}\t{{.State}}'
```

Expected output, after the images have been pulled:

```text
api	running
clickhouse	running
collector	running
```

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

There are 33 `PASS` lines. Any `FAIL` line names the check and what it got.

The test sends one span, two log records (one of them an event) and one gauge
over OTLP HTTP, reads them back from ClickHouse and through the query API,
and checks that the API's database user is read-only and limited.

## 4. Send your own telemetry

Point any OpenTelemetry SDK at the collector:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer $(grep TRACEMELT_INGEST_TOKEN .env | cut -d= -f2)"
```

There is no UI yet. Read the data back through the query API:

```bash
TOKEN=$(grep TRACEMELT_API_TOKEN .env | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/services"
```

Expected output, with your own service names:

```text
[{"service":"smoke-1795785046-21234","spans":1,"error_spans":0}]
```

## If something fails

| Symptom | Cause and fix |
|---|---|
| `required variable ... is missing a value: run scripts/init-env.sh` | No `.env`. Run step 1. |
| `port is already allocated` | Another process holds an OTLP port. Change the `TRACEMELT_*_PORT` values in `.env`. |
| Smoke test fails at `collector health` | The collector is still starting or is restarting. Check `docker compose logs collector`. |
| `schema-init` exits with an error | ClickHouse was not reachable when the tables were being created. Check `docker compose logs schema-init clickhouse`, then run `docker compose up -d` again. |

## Stop and clean up

```bash
docker compose down        # keeps data
docker compose down -v     # deletes stored telemetry and the collector queue
```

## Related

- [Query API reference](../api/query-api.md): endpoints and guardrails.
- [Configuration reference](../reference/configuration.md): ports, environment variables, limits.
- [Roadmap](../project/roadmap.md)
