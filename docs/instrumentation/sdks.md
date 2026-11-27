# Node.js and Python SDK reference

!!! warning "Status: prototype, unpublished"
    Verified on 2026-11-28 with Node.js 24.16 and Python 3.12: 28 Node tests,
    31 Python tests, and a run of each against the local stack. Neither
    package is on npm or PyPI. Applies to: `dev`.

Each SDK is a thin wrapper over the upstream OpenTelemetry SDK. It configures
OTLP/HTTP export to a tracemelt collector and adds four helpers. Everything
the upstream SDK and its instrumentations offer still works, because the
wrapper registers the standard global providers.

## Install

The packages are not published. Install from a checkout of this repository.
Node.js 22.15 or newer is required, because the upstream OpenTelemetry
packages require it. Python 3.10 or newer is required.

=== "Node.js"

    ```bash
    npm install /path/to/observability-lens/sdk/node
    ```

=== "Python"

    ```bash
    pip install /path/to/observability-lens/sdk/python
    ```

The names `tracemelt` on npm and on PyPI were unclaimed on 2026-11-28.
Nothing has been published under them.

## Run an application

Set three variables and start the application through the SDK.

=== "Node.js"

    ```bash
    TRACEMELT_SERVICE_NAME=api \
    TRACEMELT_ENDPOINT=http://127.0.0.1:4318 \
    TRACEMELT_INGEST_TOKEN="$(grep TRACEMELT_INGEST_TOKEN .env | cut -d= -f2)" \
    node -r tracemelt/register app.js
    ```

=== "Python"

    ```bash
    TRACEMELT_SERVICE_NAME=api \
    TRACEMELT_ENDPOINT=http://127.0.0.1:4318 \
    TRACEMELT_INGEST_TOKEN="$(grep TRACEMELT_INGEST_TOKEN .env | cut -d= -f2)" \
    tracemelt app.py
    ```

    `tracemelt -m package.module` runs a module. Arguments after the script
    are passed to it, and its exit code is kept.

The service appears under **Overview** in the UI once it has sent a span,
normally within 10 seconds of the first request it handles.

To start telemetry from code instead, call `tracemelt.init()` before the
application imports the libraries it wants instrumented.

## Settings

| Variable | Meaning |
|---|---|
| `TRACEMELT_ENDPOINT` | Collector base URL. Falls back to `OTEL_EXPORTER_OTLP_ENDPOINT`. Required. |
| `TRACEMELT_INGEST_TOKEN` | Sent as `Authorization: Bearer`. |
| `TRACEMELT_SERVICE_NAME` | Falls back to `OTEL_SERVICE_NAME`, then `unknown_service`. |
| `TRACEMELT_CAPTURE_CONSOLE` (Node.js), `TRACEMELT_CAPTURE_LOGGING` (Python) | `true` also sends `console` output, or records from the `logging` module at INFO and above, as log records. Off by default. |
| `TRACEMELT_NO_AUTO_INSTRUMENT` (Node.js) | `true` skips loading the auto-instrumentations. |
| `TRACEMELT_DEBUG` | `true` prints the SDK's own warnings to stderr. |
| `TRACEMELT_DISABLED` | `true` turns telemetry off. `OTEL_SDK_DISABLED` does the same. |

Each can also be passed to `init()`: `endpoint`, `token`, `serviceName` or
`service_name`, `captureConsole` or `capture_logging`, `debug`, `disabled`.

## Helpers

=== "Node.js"

    ```js
    const tracemelt = require('tracemelt');

    tracemelt.count('orders');                          // add 1
    tracemelt.count('bytes.sent', 512, { route: '/x' });
    tracemelt.gauge('queue.depth', 7);
    tracemelt.timing('checkout.latency', 12.5);         // milliseconds
    tracemelt.event('order.placed', { product: 'kettle', quantity: 2, value_cents: 2598, order_id: 'o-12345' });
    await tracemelt.shutdown();                         // flush before exit
    ```

=== "Python"

    ```python
    import tracemelt

    tracemelt.count("orders")                           # add 1
    tracemelt.count("bytes.sent", 512, {"route": "/x"})
    tracemelt.gauge("queue.depth", 7)
    tracemelt.timing("checkout.latency", 12.5)          # milliseconds
    tracemelt.event("order.placed", {"product": "kettle", "quantity": 2, "value_cents": 2598, "order_id": "o-12345"})
    tracemelt.shutdown()                                # flush before exit
    ```

| Helper | Stored as |
|---|---|
| `count(name, value=1, attributes)` | A counter, in `otel_metrics_sum`. Negative values are ignored. |
| `gauge(name, value, attributes)` | A gauge, in `otel_metrics_gauge`. Chartable in the UI. |
| `timing(name, milliseconds, attributes)` | A histogram, in `otel_metrics_histogram`. Stored, not chartable yet. |
| `event(name, attributes)` | A log record tagged as an event, plus the counters described below. |

No instrument has to be declared first. Names must start with a letter and
may contain letters, digits, `.`, `_`, `-` and `/`, up to 200 characters.
Attribute values must be strings, numbers or booleans; anything else is
dropped.

### Events

`event("order.placed", {...})` emits a log record with body `order.placed`
and the attributes `tracemelt.event = "true"` and `event.name =
"order.placed"`. Emitted inside a span, it carries that span's trace id.

Each event also updates counters:

| Counter | Value |
|---|---|
| `tracemelt.events`, with attribute `event.name` | 1 per event |
| `tracemelt.event.<event name>.<attribute>` | The attribute's value, for each numeric attribute that is a measurement |

A numeric attribute is treated as a measurement unless its key ends in a word
that marks an identifier or code: `id`, `uuid`, `key`, `code`, `number`,
`zip`, `phone`, `port`, `version`, `year`, `status`, `index`, `timestamp` and
a few like them. So `quantity` and `value_cents` are summed, and `order_id`
and `http.status` are not.

**Pass identifiers as strings.** A numeric identifier under a key the SDK
does not recognise, such as `customer: 48213`, would be summed into a
meaningless counter. Strings, booleans and negative numbers are never summed.

## What happens when things go wrong

No helper and no part of start-up raises or throws. This is covered by tests
that run real programs against misbehaving collectors.

| Situation | Behaviour |
|---|---|
| No endpoint, or an invalid one | One line on stderr, `tracemelt: telemetry is off: ...`. Every helper becomes a no-op. The application runs normally. |
| Nothing listens at the endpoint | Exports fail in the background and are retried by the upstream exporter. The application runs normally. |
| The collector accepts connections and never answers | Each export gives up after 5 seconds. `shutdown()` returns at its own timeout, 5 seconds by default. |
| The collector is slower than the application | Each signal has a queue of 2048 items. When it is full, new spans and log records are dropped. Tested: 200,000 spans against a stuck exporter grew memory by less than 100 MB. |
| A helper is given a bad name or value | Ignored. A bad name prints one line on stderr the first time. |
| More than 500 distinct metric names | New names are dropped, with one line on stderr. |
| A helper is called before `init()` or after `shutdown()` | Ignored. |

Telemetry is exported on background timers and threads: spans and logs every
5 seconds, metrics every 30 seconds. No helper makes a network call.

## Limitations

- **Process exit can be delayed when the collector is unreachable.** In
  Node.js, a program that ends by letting the event loop drain exits up to 5
  seconds late, because upstream retries are not cancelled by `shutdown()`.
  A program that calls `process.exit()` is not delayed. In Python, exit
  waits at most the shutdown timeout.
- **Data still queued at exit is lost** if the collector cannot be reached in
  time, or if the process is killed. Node.js installs no signal handlers:
  call `shutdown()` from your own `SIGTERM` handler.
- **Python instruments only what is installed.** The `tracemelt` command
  turns on every `opentelemetry-instrumentation-*` package it finds, and the
  SDK depends on none. Install the ones for your framework, for example
  `opentelemetry-instrumentation-flask`. This has not been tested here
  against a real framework.
- **Node.js loads all upstream auto-instrumentations** except the file system
  one. This adds start-up time and about 68 MB of dependencies. The overhead
  has not been measured.
- **Tested in Node.js:** HTTP client and server spans. Other libraries rely
  on the upstream instrumentations and are untested here.
- **Counters are stored but not usable yet.** Nothing can alert on them and
  the UI does not chart them.
- **Attribute limits:** 32 attributes per call, strings cut at 1024
  characters.
- **Pinned upstream versions.** The SDKs pin exact OpenTelemetry versions,
  which can conflict with other OpenTelemetry packages in the application.
- No sampling settings, no TLS client certificates, no gRPC export.
- Not tested on Windows, in browsers, with ES modules loaded through
  `--import`, or in serverless runtimes.

## Related

- [Self-observability and data handling](../operations/self-observability.md): what the collector masks.
- [Quickstart](../getting-started/quickstart.md)
- [Configuration reference](../reference/configuration.md)
