# tracemelt for Python

**Status: prototype, unpublished.** Not on PyPI. Install from this repository.

A thin wrapper over the OpenTelemetry Python SDK. It sends traces, metrics, logs
and events to a tracemelt collector over OTLP/HTTP.

```bash
TRACEMELT_SERVICE_NAME=api \
TRACEMELT_ENDPOINT=http://127.0.0.1:4318 \
TRACEMELT_INGEST_TOKEN=... \
tracemelt app.py
```

```python
import tracemelt

tracemelt.count("orders")
tracemelt.gauge("queue.depth", 7)
tracemelt.timing("checkout.latency", 12.5)
tracemelt.event("order.placed", {"product": "kettle", "quantity": 2, "value_cents": 2598})
```

Full reference, failure behaviour and limits: `docs/instrumentation/sdks.md`.

Run the tests with `pip install -e ".[dev]" && pytest`.
