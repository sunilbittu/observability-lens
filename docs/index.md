# tracemelt

!!! warning "Status: planned"
    tracemelt is at the design stage. This repository contains documentation
    tooling only. There is no collector config, query API, UI, alert engine or
    SDK to install yet. Applies to: `dev` (no release exists).

tracemelt is a planned open-source, OpenTelemetry-native observability
platform for metrics, events, logs and traces (MELT). It is intended to be
self-hostable and licensed under Apache-2.0.

## What exists today

| Component | Status |
|---|---|
| Documentation site (MkDocs Material, mike, GitHub Pages) | prototype |
| OTLP ingest (OpenTelemetry Collector to ClickHouse) | planned |
| Query API | planned |
| Web UI | planned |
| Alert engine | planned |
| Node.js and Python SDKs | planned |
| Infrastructure metrics receivers | planned |

"Planned" means no code for it is in the repository.

## Intended design

These are design decisions, not working features:

- OTLP is the only ingest contract. No proprietary telemetry protocol.
- The OpenTelemetry Collector (contrib) receives OTLP on gRPC `4317` and HTTP `4318`.
- ClickHouse stores telemetry in tables owned by the collector's `clickhouseexporter`.
- Events are structured logs tagged with `tracemelt.event = "true"`, not a new signal.

## Where to go next

- [Quickstart](getting-started/quickstart.md): what the first-run flow will be, and why it cannot be run yet.
- [Roadmap](project/roadmap.md): phases, their acceptance criteria and current state.
- [Changelog](project/changelog.md): what has changed in this repository.
