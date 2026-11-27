# Roadmap

!!! warning "Status: planned"
    Everything below Phase -1 is planned work with no code in the repository.
    There are no dates. Applies to: `dev` (no release exists).

Phases are worked in order. A phase is complete only when its acceptance
checks have been run and the results recorded.

## Phase -1: truth and docs live

State: in progress.

| Check | State |
|---|---|
| Docs URL returns 200 | done |
| GitHub Pages serves the `gh-pages` branch root | done |
| `mkdocs build --strict` passes | done |
| Navigation references only existing files | done |
| Every page carries a status banner | done |
| `/latest/` returns 200 | not done: no release exists, the site root points at `dev` |
| Remaining Wave 1 pages (MELT model, architecture, data model, ports, environment variables, alerting limitations, no-data troubleshooting) | not done: they describe components that do not exist yet |

## Phase 0: verify the quickstart

State: blocked. The collector config, ClickHouse setup, query API, UI, alert
engine and demo workload have to be added to the repository before anything
can be verified.

Acceptance: a new user can follow the quickstart without guessing, and every
command has a recorded expected output.

## Phase 1: harden single-node

State: planned.

Scope: secrets from the environment, authenticated OTLP ingest, an
authenticated UI and API, a persistent collector queue, query guardrails,
webhook allowlisting with SSRF protection, self-metrics, disk and retention
alerts, backup and restore, PII redaction defaults, fail-open SDK defaults.

## Phase 2: production shape

State: planned.

Scope: Postgres for rules, state, outbox and audit; OIDC and RBAC; separate
ClickHouse users; alert resolution, silences, dedup and durable notification
retries; histogram averages and real percentiles; per-series alerting; a Helm
chart; upgrade documentation.

## Phase 3: scale and enterprise

State: planned.

Scope: highly available ClickHouse, collector gateway replicas, downsampling,
tiered storage, multi-tenancy, quotas, tail sampling, cardinality controls and
migration guides.

## Related

- [Project status](../index.md)
- [Changelog](changelog.md)
