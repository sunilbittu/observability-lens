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
