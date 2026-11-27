# tracemelt

!!! warning "Status: prototype"
    OTLP ingest into ClickHouse and a read-only query API exist. There is no
    UI, alert engine or SDK yet. Applies to: `dev` (no release exists).

tracemelt is a planned open-source, OpenTelemetry-native observability
platform for metrics, events, logs and traces (MELT). It is intended to be
self-hostable and licensed under Apache-2.0.

## What exists today

| Component | Status |
|---|---|
| Documentation site (MkDocs Material, mike, GitHub Pages) | prototype |
| OTLP ingest (OpenTelemetry Collector to ClickHouse), token authenticated | prototype, verified 2026-11-27 |
| Query API (read-only, token guarded, gauges only for metrics) | prototype, verified 2026-11-27 |
| Web UI | planned |
| Alert engine | planned |
| Node.js and Python SDKs | planned |
| Infrastructure metrics receivers | planned |

"Planned" means no code for it is in the repository.

## Intended design

The first two items are implemented in the prototype. The rest are design decisions:

- OTLP is the only ingest contract. No proprietary telemetry protocol.
- The OpenTelemetry Collector (contrib) receives OTLP on gRPC `4317` and HTTP `4318`.
- ClickHouse stores telemetry in tables owned by the collector's `clickhouseexporter`.
- Events are structured logs tagged with `tracemelt.event = "true"`, not a new signal.

## Where to go next

- [Quickstart](getting-started/quickstart.md): start the stack and prove data reaches ClickHouse.
- [Query API reference](api/query-api.md): endpoints, limits and guardrails.
- [Configuration reference](reference/configuration.md): ports, environment variables, limits and known limitations.
- [Roadmap](project/roadmap.md): phases, their acceptance criteria and current state.
- [Changelog](project/changelog.md): what has changed in this repository.
