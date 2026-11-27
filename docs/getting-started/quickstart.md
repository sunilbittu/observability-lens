# Quickstart

!!! warning "Status: prototype, ingest only"
    Verified on 2026-11-27 with Docker 29.5.3, Compose v5.1.4, collector
    contrib 0.166.0 and ClickHouse 26.8.48.11 on macOS (arm64). This covers
    OTLP ingest into ClickHouse. There is no UI, query API, alerting or SDK
    yet. Applies to: `dev`.

This tutorial starts the single-node stack and proves that authenticated
OTLP data reaches ClickHouse.

## Before you start

You need Docker with Compose v2, `curl` and `openssl`. Ports `4317`, `4318`
and `13133` must be free on loopback, or change them in `.env` after step 1.

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
docker compose up -d
docker compose ps --format '{{.Service}}\t{{.State}}'
```

Expected output, after the images have been pulled:

```text
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
PASS  logs with wrong token rejected (401)
PASS  traces without token rejected (401)
PASS  metrics without token rejected (401)
PASS  traces accepted (200)
PASS  logs accepted (200)
PASS  metrics accepted (200)
PASS  trace stored (1)
PASS  log stored with trace id (1)
PASS  event stored as tagged log (1)
PASS  gauge stored (1)
PASS  rejected requests stored nothing (2)
smoke: all checks passed
```

The test sends one span, two log records (one of them an event) and one gauge
over OTLP HTTP, then reads them back from ClickHouse.

## 4. Send your own telemetry

Point any OpenTelemetry SDK at the collector:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer $(grep TRACEMELT_INGEST_TOKEN .env | cut -d= -f2)"
```

There is no UI to view the data yet. To look at it, query ClickHouse:

```bash
docker compose exec clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --database "$CLICKHOUSE_DB" -q "SELECT ServiceName, count() FROM otel_logs GROUP BY ServiceName"'
```

## If something fails

| Symptom | Cause and fix |
|---|---|
| `required variable ... is missing a value: run scripts/init-env.sh` | No `.env`. Run step 1. |
| `port is already allocated` | Another process holds an OTLP port. Change the `TRACEMELT_*_PORT` values in `.env`. |
| Smoke test fails at `collector health` | The collector is still starting or is restarting. Check `docker compose logs collector`. |
| Collector restarts in a loop with `create database` errors | ClickHouse is not reachable. See [known limitations](../reference/configuration.md#known-limitations). |

## Stop and clean up

```bash
docker compose down        # keeps data
docker compose down -v     # deletes stored telemetry and the collector queue
```

## Related

- [Configuration reference](../reference/configuration.md): ports, environment variables, limits.
- [Roadmap](../project/roadmap.md)
