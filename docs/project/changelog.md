# Changelog

!!! warning "Status: prototype"
    No version of tracemelt has been released. Entries below describe changes
    to this repository. Applies to: `dev`.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- Single-node Docker Compose stack: OpenTelemetry Collector contrib 0.166.0
  writing to ClickHouse 26.8.48.11.
- OTLP ingest requires a bearer token. Requests without it get HTTP 401.
- On-disk collector export queue with bounded retries.
- One-shot `schema-init` job creates the exporter's tables, so the collector
  can start and queue data while ClickHouse is down.
- `scripts/outage-test.sh` to test durability across a ClickHouse outage.
- Read-only query API (FastAPI) for services, traces, logs, events and gauge
  metrics, guarded by a bearer token.
- Web UI served by the query API: overview, traces with a span waterfall,
  logs with a jump to the trace, gauge charts and events.
- Browser sign-in: `POST /api/session` exchanges the API token for an
  `HttpOnly` session cookie. Strict content security policy on every response.
- Demo workload behind `docker compose --profile demo`.
- Alert engine: `log_count`, `error_spans` and `metric_avg` threshold rules
  from `deploy/alerts/rules.toml`, with cooldowns that survive a restart.
- Alert webhooks with egress controls: host allowlist, public addresses only
  unless a host is explicitly listed as private, loopback and link-local
  always refused, no redirects, connection pinned to the checked address.
- `alert_events` table, `GET /api/alerts` and an Alerts view in the UI.
- ClickHouse user `tracemelt_alert`: reads telemetry, writes only
  `alert_events`.
- Demo webhook receiver in the `demo` profile.
- ClickHouse user `tracemelt_reader`: select-only, with time, memory and row
  limits it cannot raise.
- `scripts/init-env.sh` to generate secrets and `scripts/smoke.sh` to verify
  ingest end to end.
- Configuration reference page.
- Apache-2.0 `LICENSE` and a `README`.
- Roadmap and changelog pages.
- Strict docs build as a gate before every docs deploy.

### Changed

- Project name in the docs is now tracemelt. The repository and docs URL
  remain `observability-lens`.
- The landing page and quickstart describe only what is in the repository.
  The quickstart is now a verified ingest tutorial.
- Quickstart moved to `getting-started/quickstart.md`. The old
  `/quickstart/` URL no longer resolves.

### Fixed

- Broken link to a missing roadmap page, which made `mkdocs build --strict`
  fail.
- Unclosed code block in the quickstart.
- GitHub Pages 404: Pages now serves the `gh-pages` branch root and the site
  root redirects to `dev`.
