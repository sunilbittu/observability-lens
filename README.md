# tracemelt

**Status: prototype.** OTLP ingest into ClickHouse and a read-only query API
exist. There is no UI, alert engine or SDK yet.

tracemelt is a planned open-source, OpenTelemetry-native observability
platform for metrics, events, logs and traces. OTLP is the ingest contract.

- Docs: https://sunilbittu.github.io/observability-lens/
- Roadmap: [docs/project/roadmap.md](docs/project/roadmap.md)
- Changelog: [docs/project/changelog.md](docs/project/changelog.md)

## Run the ingest stack

```bash
scripts/init-env.sh
docker compose up -d --build
scripts/smoke.sh
```

The last command must end with `smoke: all checks passed`. See the
[quickstart](docs/getting-started/quickstart.md) for expected output and
troubleshooting.

## Build the docs locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-docs.txt
.venv/bin/mkdocs build --strict
.venv/bin/mkdocs serve
```

`mkdocs build --strict` must exit 0 with no warnings. `mkdocs serve` prints a
local URL, by default `http://127.0.0.1:8000/observability-lens/`.

## How docs are published

- `main` holds the source. `gh-pages` holds the built HTML, managed by mike.
- A push to `main` publishes the `dev` version.
- A `v*` tag publishes that version and moves the `latest` alias to it.
- No tag exists yet, so the site root points at `dev`.

## License

Apache-2.0. See [LICENSE](LICENSE).
