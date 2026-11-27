# tracemelt for Node.js

**Status: prototype, unpublished.** Not on npm. Install from this repository.

A thin wrapper over the OpenTelemetry Node.js SDK. It sends traces, metrics, logs
and events to a tracemelt collector over OTLP/HTTP.

```bash
TRACEMELT_SERVICE_NAME=api \
TRACEMELT_ENDPOINT=http://127.0.0.1:4318 \
TRACEMELT_INGEST_TOKEN=... \
node -r tracemelt/register app.js
```

```js
const tracemelt = require('tracemelt');

tracemelt.count('orders');
tracemelt.gauge('queue.depth', 7);
tracemelt.timing('checkout.latency', 12.5);
tracemelt.event('order.placed', { product: 'kettle', quantity: 2, value_cents: 2598 });
```

Full reference, failure behaviour and limits: `docs/instrumentation/sdks.md`.

Run the tests with `npm test`.
