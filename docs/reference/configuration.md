# Configuration reference

!!! warning "Status: prototype"
    Describes the single-node Docker Compose stack as verified on 2026-11-27.
    Applies to: `dev`.

## Ports

| Port | Service | Bound to | Purpose |
|---|---|---|---|
| 4317 | collector | `TRACEMELT_BIND`, default `127.0.0.1` | OTLP gRPC, bearer token required |
| 4318 | collector | `TRACEMELT_BIND`, default `127.0.0.1` | OTLP HTTP, bearer token required |
| 13133 | collector | `127.0.0.1` only | Health check, no authentication |
| 8123, 9000 | ClickHouse | not published | Reachable only on the Compose network |

The stack has no TLS. Keep `TRACEMELT_BIND` on loopback unless a TLS
terminating proxy sits in front of the collector.

## Environment variables

All values live in `.env`, written by `scripts/init-env.sh`. The file is
ignored by git.

| Variable | Default | Meaning |
|---|---|---|
| `TRACEMELT_INGEST_TOKEN` | generated | Bearer token every OTLP request must carry. One shared token for all senders. |
| `TRACEMELT_CLICKHOUSE_USER` | `tracemelt` | ClickHouse user, created on first start. |
| `TRACEMELT_CLICKHOUSE_PASSWORD` | generated | Password for that user. |
| `TRACEMELT_CLICKHOUSE_DB` | `otel` | Database that holds the `otel_*` tables. |
| `TRACEMELT_RETENTION` | `72h` | TTL for all signals. Applied when tables are created; changing it later does not alter existing tables. |
| `TRACEMELT_BIND` | `127.0.0.1` | Host address for the OTLP ports. |
| `TRACEMELT_OTLP_GRPC_PORT` | `4317` | Host port for OTLP gRPC. |
| `TRACEMELT_OTLP_HTTP_PORT` | `4318` | Host port for OTLP HTTP. |
| `TRACEMELT_COLLECTOR_HEALTH_PORT` | `13133` | Host port for the collector health check. |

The ClickHouse user and password are set only when the data volume is first
created. Editing them in `.env` afterwards does not change the database.

## Tables

The collector's `clickhouseexporter` creates and owns every table. tracemelt
does not define telemetry schema. The DDL runs in the one-shot `schema-init`
job on every `docker compose up`, see
[ADR 0001](../project/adr/0001-schema-init-job.md).

`otel_logs`, `otel_traces`, `otel_traces_trace_id_ts`,
`otel_traces_trace_id_ts_mv`, `otel_metrics_gauge`, `otel_metrics_sum`,
`otel_metrics_histogram`, `otel_metrics_exponential_histogram`,
`otel_metrics_summary`.

Events are rows in `otel_logs` with `LogAttributes['tracemelt.event'] = 'true'`
and `LogAttributes['event.name']` set.

## Limits

| Limit | Value |
|---|---|
| OTLP request size | 4 MiB (gRPC and HTTP) |
| Collector memory | 512 MiB container limit, `GOMEMLIMIT` 400 MiB, `memory_limiter` at 80% |
| Export queue | 5000 batches, stored on disk in the `collector-queue` volume |
| Export retry | Up to 10 minutes per batch, then the batch is dropped |

## Durability, as tested

On 2026-11-27 `scripts/outage-test.sh 300` passed: ClickHouse was stopped for
300 seconds, 20 log records were sent, the collector was restarted while
ClickHouse was still down, 20 more records were sent, and all 40 were in
ClickHouse 26 seconds after it came back, with no duplicates.

## Known limitations

- **A collector started during a ClickHouse outage leaves `EventName` empty.**
  It cannot inspect the table columns at startup, so the optional `EventName`
  column in `otel_logs` stays empty until the collector is restarted with
  ClickHouse up. See [ADR 0001](../project/adr/0001-schema-init-job.md).
- **Up to 5 seconds of data sits in memory.** The batch processor holds data
  before it reaches the on-disk queue. A collector crash loses that window.
- **Outages longer than 10 minutes drop data.** Retries are bounded on
  purpose. Nothing alerts on queue size yet.
- **One shared ingest token.** No per-service credentials, no rate limits.
- **No TLS**, no self-metrics pipeline, no backups, no PII redaction.

## Related

- [Quickstart](../getting-started/quickstart.md)
- [Roadmap](../project/roadmap.md)
