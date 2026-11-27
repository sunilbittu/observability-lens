# Self-observability and data handling

!!! warning "Status: prototype"
    Verified on 2026-11-27 by `scripts/smoke.sh`. Applies to: `dev`.

## What tracemelt reports about itself

The collector scrapes two internal endpoints every 30 seconds and stores the
results like any other metrics. Neither endpoint is published to the host.

| Source | `service.name` | What |
|---|---|---|
| The collector | `otelcol-contrib` | Its own metrics: accepted, refused, failed and sent items per signal, export queue size and capacity, memory. |
| ClickHouse | `tracemelt-clickhouse` | A short list: free, used and total bytes on the data path, the largest part count in a partition, running queries, merges, delayed inserts, uptime. |

Gauges can be charted under **Metrics** in the UI. Counters are stored but
cannot be charted yet.

| Question | Metric |
|---|---|
| Is data backing up on the way to storage? | `otelcol_exporter_queue_size` against `otelcol_exporter_queue_capacity` |
| How much disk is left? | `ClickHouseAsyncMetrics_FilesystemMainPathAvailableBytes` |
| Are merges keeping up? | `ClickHouseAsyncMetrics_MaxPartCountForPartition` |
| Is the collector refusing data? | `otelcol_receiver_refused_spans`, `_log_records`, `_metric_points` (counters) |
| Did an export fail for good? | `otelcol_exporter_send_failed_spans`, `_log_records`, `_metric_points` (counters, present only after a failure) |

Three alert rules ship for these in `deploy/alerts/rules.toml`:
`collector-export-queue-backlog`, `clickhouse-disk-low` and
`clickhouse-too-many-parts`.

### Limitations

- **A full ClickHouse outage cannot raise an alert.** The alert engine reads
  from ClickHouse, and the collector's own metrics are stored there too. The
  queue rule catches slow or partly failing storage and tells you afterwards
  that a backlog happened. To be told that ClickHouse is down, watch the
  health endpoints from outside the stack.
- **The disk rule is an absolute number of bytes**, 10 GiB by default,
  because there is no ratio signal. Set it to about 20% of your disk.
- **Counters cannot be alerted on or charted**, so refused and failed items
  are stored but not acted on.
- **The alert engine and the query API report nothing about themselves**
  beyond their logs.
- The disk rule firing was checked with a threshold raised above the free
  space, not by filling a disk.

## What is masked by default

The collector masks sensitive values before anything is stored. This applies
to span attributes, log attributes, metric data point attributes and log
bodies.

| Rule | Effect |
|---|---|
| Attribute key contains `authorization`, `cookie`, `password`, `passwd`, `secret`, `api_key`, `cvv`, `cvc`, `card_number` | The value becomes `****`. |
| Attribute key has `token` or `ssn` as a whole word, such as `session_token` | The value becomes `****`. `gen_ai.usage.input_tokens` is kept. |
| A value or log body contains `Bearer` followed by a token | That part becomes `****`. |
| A value or log body contains a 13 to 16 digit number shaped like a Visa, Mastercard or American Express card | That part becomes `****`. |

### Limitations

- **This is a safety net, not a guarantee.** It matches known key names and
  two value shapes. A password in an attribute called `p`, an email address,
  a name or a national ID number is stored as sent.
- **Resource attributes, span names and metric names are not checked.**
- **False positives happen.** Any number that starts with 4 and is 13 or 16
  digits long is masked.
- **Masking is not reversible** and applies to everything the collector
  receives. To change the rules, edit the `redaction` processor in
  `deploy/collector/config.yaml` and restart the collector.
- Do not send card data, credentials or personal data in telemetry and rely
  on this to remove it.

## Related

- [Alert rules and limitations](../alerting/rules.md)
- [Back up and restore](backup-and-restore.md)
- [Configuration reference](../reference/configuration.md)
