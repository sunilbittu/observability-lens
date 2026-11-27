#!/usr/bin/env bash
# Writes .env with generated secrets. Refuses to overwrite an existing file.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -e .env ]; then
  echo ".env already exists, leaving it alone" >&2
  exit 1
fi

umask 077
cat > .env <<ENV
TRACEMELT_INGEST_TOKEN=$(openssl rand -hex 32)
TRACEMELT_CLICKHOUSE_DB=otel
TRACEMELT_CLICKHOUSE_USER=tracemelt
TRACEMELT_CLICKHOUSE_PASSWORD=$(openssl rand -hex 24)
TRACEMELT_CLICKHOUSE_READER_PASSWORD=$(openssl rand -hex 24)
TRACEMELT_CLICKHOUSE_ALERT_PASSWORD=$(openssl rand -hex 24)
TRACEMELT_API_TOKEN=$(openssl rand -hex 32)
TRACEMELT_RETENTION=72h
TRACEMELT_BIND=127.0.0.1
TRACEMELT_OTLP_GRPC_PORT=4317
TRACEMELT_OTLP_HTTP_PORT=4318
TRACEMELT_COLLECTOR_HEALTH_PORT=13133
TRACEMELT_API_PORT=8000
ENV
echo "wrote .env"
