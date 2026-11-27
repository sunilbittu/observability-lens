# ADR 0001: Create the ClickHouse schema in a one-shot job

!!! warning "Status: prototype"
    Accepted on 2026-11-27. Applies to: `dev`.

## Context

The collector's `clickhouseexporter` creates its tables at startup when
`create_schema` is `true`. If ClickHouse is unreachable at that moment the
collector exits. A collector that restarts during a ClickHouse outage then
refuses OTLP until ClickHouse returns, and senders lose data once their own
retries run out. This was observed on 2026-11-27.

tracemelt must not hand-write the telemetry schema, because the exporter owns
it and changes it between versions.

## Decision

- The long-running collector sets `create_schema: false`.
- A one-shot `schema-init` job runs the same pinned collector binary with
  `create_schema: true`, waits until its health endpoint answers, then exits.
  The long-running collector starts only after the job succeeds.

The DDL is still produced by the exporter, at the same version as the
collector that writes the data.

## Consequences

- The collector starts, accepts data and queues it to disk while ClickHouse
  is down. Tested with a 300 second outage and a collector restart in the
  middle: 40 of 40 records arrived, none duplicated.
- The `schema-init` image tag must be bumped together with the collector
  image tag. Both are pinned in `docker-compose.yml` and its Dockerfile.
- A collector that starts while ClickHouse is down cannot inspect the table
  columns, so it leaves optional columns (currently `EventName` in
  `otel_logs`) empty until its next restart.
- `TRACEMELT_RETENTION` is read by the job. It still only applies when tables
  are first created.

## Alternatives rejected

- **Keep `create_schema: true` and document the gap.** Leaves a data loss
  path open.
- **Check the exporter's DDL into the repository.** Makes tracemelt the owner
  of a schema it does not control, and it would drift on every upgrade.
