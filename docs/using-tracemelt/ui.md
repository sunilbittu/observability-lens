# Use the web UI

!!! warning "Status: prototype"
    Checked by hand in Chrome on 2026-11-27 against the demo workload. There
    are no automated browser tests yet. Applies to: `dev`.

The UI is static HTML, CSS and JavaScript served by the query API. It makes no
third-party requests.

## Open it

1. Start the stack with the demo workload:

    ```bash
    docker compose --profile demo up -d --build
    ```

2. Open `http://127.0.0.1:8000/`.
3. Paste the value of `TRACEMELT_API_TOKEN` from `.env` and choose **Sign in**.

The token is exchanged for an `HttpOnly`, `SameSite=Strict` session cookie
that lasts 12 hours. The token is not kept in browser storage. A wrong token
shows "That token was not accepted."

## Views

| View | What it shows |
|---|---|
| Overview | Services with span counts and failure rate, and the latest failed traces. Select a service to see its traces. |
| Traces | Recent traces, filtered by service or failed only. Select a trace to open it. |
| Trace | A waterfall of every span, nested by parent. Failed spans are hatched and marked. Select a span for its attributes. Log records that carry the trace id are listed below. |
| Logs | Log records, with a text search on the message and a service filter. **Open trace** jumps to the trace a record belongs to. |
| Metrics | Gauge metrics, charted as the average per service. Hover for values, or switch to a table. |
| Events | Log records tagged as events, with their attributes. |

The time range (15m, 1h, 6h, 24h) applies to every view. List views refresh
every 10 seconds while the tab is visible.

## Find a failed request

1. On **Overview**, select one of the latest failed traces.
2. In the waterfall, the hatched bars are the spans that failed. The deepest
   failed span is usually the cause.
3. Select that span to read its status message and attributes.
4. Read the log records under the waterfall for what each service logged.

With the demo workload, the payments service slows down and fails for 3
minutes out of every 12, so failed `POST /checkout` traces appear regularly.

## Limitations

- One shared token signs everyone in. There are no users or roles.
- The session cannot be revoked on its own. Changing `TRACEMELT_API_TOKEN`
  and restarting the API ends every session.
- Over plain HTTP the cookie is not marked `Secure`. Set
  `TRACEMELT_COOKIE_SECURE=1` when serving the UI over HTTPS.
- No Alerts, Dashboards or Infrastructure views. Sum metrics and histograms
  are listed but cannot be charted.
- Lists show the newest 100 traces or 200 records, with no paging.
- Times are shown in the browser's time zone.

## Related

- [Query API reference](../api/query-api.md)
- [Quickstart](../getting-started/quickstart.md)
