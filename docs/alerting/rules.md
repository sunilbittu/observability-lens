# Alert rules reference

!!! warning "Status: prototype"
    Verified on 2026-11-27 by `scripts/smoke.sh` and the unit tests in
    `api/tests/test_alerts.py`. Read the limitations on this page before
    relying on an alert. Applies to: `dev`.

The alert engine is the `alerts` service. Every 30 seconds it evaluates the
rules in `deploy/alerts/rules.toml` and records what fired in the
`alert_events` table. A rule can also POST to a webhook.

## Limitations

These are the ways this prototype can mislead you.

- **Three signals only.** `log_count`, `error_spans` and `metric_avg`. There
  is no max, min, rate, ratio or percentile.
- **`metric_avg` is an average of gauge data points.** It cannot see one hot
  instance behind a healthy average. Without `service` it averages across
  every service. It does not work on counters or histograms. It is not a
  percentile and must not be read as one.
- **No per-series alerting.** One rule produces one value. You cannot alert
  per pod, node or GPU.
- **No resolution.** A rule fires and then stays silent for its cooldown.
  Nothing tells you the condition has cleared.
- **No "for" duration.** A rule fires the first time its window breaches.
- **One webhook attempt.** A failed delivery is recorded and never retried.
- **A metric with no data does not fire.** A service that stops reporting is
  not detected.
- **It cannot report a ClickHouse outage.** The engine reads from ClickHouse,
  so while ClickHouse is down no rule is evaluated.
- **Run one instance.** Two `alerts` containers would both fire.
- **Rules are a file.** Changing them needs a restart, and there is no audit
  trail of edits. There are no silences.
- **Slow webhooks delay evaluation.** Rules run one after another, and each
  delivery can wait up to 5 seconds.

## Rule fields

```toml
[[rule]]
name = "payments-failed-spans"
signal = "error_spans"
service = "payments"
comparator = ">"
threshold = 5
window_seconds = 60
cooldown_seconds = 300
webhook_url = "http://webhook-sink:8080/alerts"
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Unique. 1 to 64 characters of `a-z`, `0-9`, dot, dash, underscore. |
| `signal` | yes | `log_count`, `error_spans` or `metric_avg`. |
| `comparator` | yes | `>`, `>=`, `<` or `<=`. |
| `threshold` | yes | Number the measured value is compared with. |
| `window_seconds` | yes | How far back to measure, 10 to 86400. |
| `cooldown_seconds` | yes | Minimum time between two firings, 0 to 604800. |
| `service` | no | Limit the rule to one `service.name`. |
| `search` | `log_count` only | Case-insensitive text the log body must contain. |
| `severity` | `log_count` only | Severity text the record must have, for example `ERROR`. |
| `metric` | `metric_avg` only, required | Gauge metric name. |
| `webhook_url` | no | Where to POST when the rule fires. |

What each signal measures:

| Signal | Value |
|---|---|
| `log_count` | Number of log records in the window that match `service`, `search` and `severity`. |
| `error_spans` | Number of spans in the window with an error status. |
| `metric_avg` | Average of all data points of the gauge in the window. |

An invalid rules file stops the service at startup with the reason in
`docker compose logs alerts`.

## Apply a change

```bash
docker compose restart alerts
docker compose logs --tail 3 alerts
```

Expected output, with your own rule names:

```text
INFO tracemelt.alerts loaded 5 rules from /etc/tracemelt/rules.toml, evaluating every 30s
INFO tracemelt.alerts evaluated 5 rules in 0.04s: payments-failed-spans=ok, ...
```

Each rule reports `ok`, `fired`, `cooling_down`, `no_data` or `error`.

## Tuning

- Start with a window of at least twice the interval at which the data
  arrives. A 60 second window on a gauge reported every 60 seconds holds one
  point.
- Set `cooldown_seconds` to how often you are willing to be told about the
  same problem. With `0`, a breaching rule fires on every pass.
- Give every `metric_avg` rule a `service`.
- Prefer `error_spans` or `log_count` for failures. They count events and are
  not diluted by healthy traffic.

## Webhooks

When a rule fires, the engine POSTs JSON once:

```json
{"rule": "payments-failed-spans", "signal": "error_spans", "service": "payments",
 "value": 40.0, "comparator": ">", "threshold": 5, "window_seconds": 60,
 "fired_at": "2026-11-27T18:15:17+00:00",
 "text": "payments-failed-spans: failed spans for payments is 40, which is > 5 over 60s"}
```

A `2xx` response counts as delivered. Redirects are not followed.

### Where webhooks may go

| Variable | Default | Meaning |
|---|---|---|
| `TRACEMELT_WEBHOOK_ALLOWED_HOSTS` | `webhook-sink` | Comma-separated host names. A webhook to any other host is blocked. |
| `TRACEMELT_WEBHOOK_PRIVATE_HOSTS` | `webhook-sink` | Hosts from the first list that may resolve to private addresses. |

A destination is used only if its host is on the allowlist and every address
it resolves to is public. Loopback, link-local (which includes the cloud
metadata address `169.254.169.254`), multicast and reserved addresses are
refused for every host, including hosts on the private list. The request
connects to the address that was checked. The defaults allow only the demo
receiver.

To send to a real receiver, set both in `.env` and restart:

```bash
TRACEMELT_WEBHOOK_ALLOWED_HOSTS=hooks.example.com
TRACEMELT_WEBHOOK_PRIVATE_HOSTS=
```

Do not put secrets in a webhook URL you would not want stored: the rules file
is plain text.

## What is recorded

`alert_events` is the only telemetry-side table tracemelt owns. It keeps 30
days.

| `Kind` | `Outcome` | Meaning |
|---|---|---|
| `fired` | empty | The rule breached and was not cooling down. |
| `delivery` | `delivered` | The webhook answered `2xx`. |
| `delivery` | `failed` | The webhook did not answer, or answered with another status. |
| `delivery` | `blocked` | The destination was refused. `Detail` says why. |

The `fired` row is written before the webhook is attempted. Cooldowns are
read from this table, so restarting the service does not re-fire a rule that
is cooling down. Read the table through `GET /api/alerts` or the **Alerts**
view.

## Related

- [ADR 0002: alert rules in a file, state in ClickHouse](../project/adr/0002-alert-rules-file.md)
- [Query API reference](../api/query-api.md)
- [Configuration reference](../reference/configuration.md)
