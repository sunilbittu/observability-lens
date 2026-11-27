#!/bin/sh
# Start a collector whose exporters have create_schema: true. Its health endpoint
# answers only after every exporter has started, which means the DDL has run.
/otelcol-contrib --config=/etc/otelcol/config.yaml &
pid=$!

i=0
while [ "$i" -lt 60 ]; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "schema-init: collector exited before the schema was created" >&2
    exit 1
  fi
  if wget -q -O /dev/null http://127.0.0.1:13133/ 2>/dev/null; then
    kill "$pid"
    wait "$pid" 2>/dev/null
    echo "schema-init: schema is in place"
    exit 0
  fi
  sleep 1
  i=$((i + 1))
done

echo "schema-init: timed out waiting for the schema" >&2
kill "$pid"
exit 1
