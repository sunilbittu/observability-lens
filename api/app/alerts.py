"""tracemelt alert engine. Status: prototype.

Evaluates threshold rules from a TOML file against the telemetry tables and records
what fired in the tracemelt-owned alert_events table. Cooldowns are read back from that
table, so a restart does not re-fire a rule that is still cooling down.

Run exactly one instance. There is no lock between instances yet.
"""

from __future__ import annotations

import logging
import os
import re
import signal as os_signal
import sys
import threading
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone

from . import webhook

log = logging.getLogger("tracemelt.alerts")

SIGNALS = ("log_count", "error_spans", "metric_avg")
COMPARATORS = {
    ">": lambda value, threshold: value > threshold,
    ">=": lambda value, threshold: value >= threshold,
    "<": lambda value, threshold: value < threshold,
    "<=": lambda value, threshold: value <= threshold,
}
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    name: str
    signal: str
    comparator: str
    threshold: float
    window_seconds: int
    cooldown_seconds: int
    service: str = ""
    search: str = ""
    severity: str = ""
    metric: str = ""
    webhook_url: str = ""


def parse_rules(text: str) -> list[Rule]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuleError(f"rules file is not valid TOML: {exc}") from exc
    rules, seen = [], set()
    for i, raw in enumerate(data.get("rule", []), start=1):
        where = f"rule {i} ({raw.get('name', 'unnamed')})"
        unknown = set(raw) - set(Rule.__dataclass_fields__)
        if unknown:
            raise RuleError(f"{where}: unknown field {sorted(unknown)[0]}")
        try:
            rule = Rule(**raw)
        except TypeError as exc:
            raise RuleError(f"{where}: {exc}") from exc
        if not isinstance(rule.name, str) or not _NAME.match(rule.name):
            raise RuleError(f"{where}: name must be 1 to 64 characters of a-z, 0-9, dot, dash or underscore")
        if rule.name in seen:
            raise RuleError(f"{where}: duplicate name")
        seen.add(rule.name)
        if rule.signal not in SIGNALS:
            raise RuleError(f"{where}: signal must be one of {', '.join(SIGNALS)}")
        if rule.comparator not in COMPARATORS:
            raise RuleError(f"{where}: comparator must be one of {', '.join(COMPARATORS)}")
        if isinstance(rule.threshold, bool) or not isinstance(rule.threshold, (int, float)):
            raise RuleError(f"{where}: threshold must be a number")
        for field, low, high in (("window_seconds", 10, 86400), ("cooldown_seconds", 0, 604800)):
            value = getattr(rule, field)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise RuleError(f"{where}: {field} must be a whole number from {low} to {high}")
        for field in ("service", "search", "severity", "metric", "webhook_url"):
            value = getattr(rule, field)
            if not isinstance(value, str) or len(value) > 500:
                raise RuleError(f"{where}: {field} must be text of at most 500 characters")
        if rule.signal == "metric_avg" and not rule.metric:
            raise RuleError(f"{where}: metric_avg needs a metric name")
        if rule.signal != "metric_avg" and rule.metric:
            raise RuleError(f"{where}: metric is only used by metric_avg")
        if rule.signal != "log_count" and (rule.search or rule.severity):
            raise RuleError(f"{where}: search and severity are only used by log_count")
        rules.append(rule)
    return rules


# Fixed statements with server-side bound parameters. Nothing from a rule is put into SQL text.
_QUERIES = {
    "log_count": """
        SELECT toFloat64(count()), count() FROM otel_logs
        WHERE Timestamp >= now() - toIntervalSecond({window:UInt32})
          AND ({service:String} = '' OR ServiceName = {service:String})
          AND ({search:String} = '' OR positionCaseInsensitive(Body, {search:String}) > 0)
          AND ({severity:String} = '' OR upper(SeverityText) = upper({severity:String}))""",
    "error_spans": """
        SELECT toFloat64(count()), count() FROM otel_traces
        WHERE Timestamp >= now() - toIntervalSecond({window:UInt32})
          AND ({service:String} = '' OR ServiceName = {service:String})
          AND lower(StatusCode) IN ('error', 'status_code_error')""",
    "metric_avg": """
        SELECT avg(Value), count() FROM otel_metrics_gauge
        WHERE TimeUnix >= now() - toIntervalSecond({window:UInt32})
          AND MetricName = {metric:String}
          AND ({service:String} = '' OR ServiceName = {service:String})""",
}

_CREATE = """
    CREATE TABLE IF NOT EXISTS alert_events (
        Timestamp DateTime64(3) DEFAULT now64(3),
        Kind LowCardinality(String),
        RuleName String,
        Signal LowCardinality(String),
        Value Float64,
        Comparator LowCardinality(String),
        Threshold Float64,
        WindowSeconds UInt32,
        Outcome LowCardinality(String),
        Detail String
    ) ENGINE = MergeTree
    ORDER BY (RuleName, Timestamp)
    TTL toDateTime(Timestamp) + toIntervalDay(30)"""

_INSERT = """
    INSERT INTO alert_events (Kind, RuleName, Signal, Value, Comparator, Threshold, WindowSeconds, Outcome, Detail)
    VALUES ({kind:String}, {rule:String}, {signal:String}, {value:Float64}, {comparator:String},
            {threshold:Float64}, {window:UInt32}, {outcome:String}, {detail:String})"""


class Store:
    """The alert engine's view of ClickHouse."""

    def __init__(self, client):
        self.client = client

    def ensure_table(self) -> None:
        self.client.command(_CREATE)

    def measure(self, rule: Rule) -> tuple[float, int]:
        """Returns (value, samples). samples is 0 when a metric has no data in the window."""
        row = self.client.query(_QUERIES[rule.signal], parameters={
            "window": rule.window_seconds, "service": rule.service, "search": rule.search,
            "severity": rule.severity, "metric": rule.metric}).result_rows[0]
        samples = int(row[1])
        return (float(row[0]) if samples else 0.0), samples

    def seconds_since_fired(self, rule: Rule) -> float | None:
        row = self.client.query(
            "SELECT count(), dateDiff('second', max(Timestamp), now()) FROM alert_events "
            "WHERE RuleName = {rule:String} AND Kind = 'fired'", parameters={"rule": rule.name}).result_rows[0]
        return float(row[1]) if row[0] else None

    def record(self, kind: str, rule: Rule, value: float, outcome: str = "", detail: str = "") -> None:
        self.client.command(_INSERT, parameters={
            "kind": kind, "rule": rule.name, "signal": rule.signal, "value": value,
            "comparator": rule.comparator, "threshold": float(rule.threshold),
            "window": rule.window_seconds, "outcome": outcome, "detail": detail[:500]})


def describe(rule: Rule, value: float) -> str:
    what = {"log_count": "log records", "error_spans": "failed spans", "metric_avg": f"average of {rule.metric}"}[rule.signal]
    scope = f" for {rule.service}" if rule.service else ""
    return f"{rule.name}: {what}{scope} is {value:g}, which is {rule.comparator} {rule.threshold:g} over {rule.window_seconds}s"


def evaluate(rule: Rule, store, deliver) -> str:
    """Evaluates one rule. Returns what happened: ok, no_data, cooling_down or fired."""
    value, samples = store.measure(rule)
    if rule.signal == "metric_avg" and samples == 0:
        return "no_data"
    if not COMPARATORS[rule.comparator](value, rule.threshold):
        return "ok"
    since = store.seconds_since_fired(rule)
    if since is not None and since < rule.cooldown_seconds:
        return "cooling_down"
    # The fired row is written before the webhook is attempted, so a crash in between
    # cannot cause a second notification for the same breach after restart.
    store.record("fired", rule, value, detail=describe(rule, value))
    if rule.webhook_url:
        outcome, detail = deliver(rule, value)
        store.record("delivery", rule, value, outcome=outcome, detail=detail)
    return "fired"


def make_deliver(allowed: frozenset[str], private: frozenset[str]):
    def deliver(rule: Rule, value: float) -> tuple[str, str]:
        try:
            destination = webhook.check(rule.webhook_url, allowed, private)
        except webhook.Blocked as exc:
            return "blocked", str(exc)
        return webhook.send(destination, {
            "rule": rule.name, "signal": rule.signal, "service": rule.service, "value": value,
            "comparator": rule.comparator, "threshold": rule.threshold,
            "window_seconds": rule.window_seconds,
            "fired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "text": describe(rule, value)})
    return deliver


def run_once(rules: list[Rule], store, deliver) -> dict[str, str]:
    results = {}
    for rule in rules:
        started = time.monotonic()
        try:
            results[rule.name] = evaluate(rule, store, deliver)
        except Exception as exc:  # one broken rule must not stop the others
            results[rule.name] = "error"
            log.error("rule %s failed to evaluate: %s", rule.name, str(exc)[:300])
        if results[rule.name] in ("fired", "error"):
            log.info("rule %s: %s in %.2fs", rule.name, results[rule.name], time.monotonic() - started)
    return results


def _hosts(name: str) -> frozenset[str]:
    return frozenset(h.strip().lower() for h in os.environ.get(name, "").split(",") if h.strip())


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    path = os.environ.get("TRACEMELT_ALERT_RULES", "/etc/tracemelt/rules.toml")
    try:
        with open(path, encoding="utf-8") as handle:
            rules = parse_rules(handle.read())
    except (OSError, RuleError) as exc:
        log.error("cannot load rules from %s: %s", path, exc)
        return 2
    interval = max(5, int(os.environ.get("TRACEMELT_ALERT_INTERVAL_SECONDS", "30")))
    deliver = make_deliver(_hosts("TRACEMELT_WEBHOOK_ALLOWED_HOSTS"), _hosts("TRACEMELT_WEBHOOK_PRIVATE_HOSTS"))
    log.info("loaded %d rules from %s, evaluating every %ds", len(rules), path, interval)

    stop = threading.Event()
    os_signal.signal(os_signal.SIGTERM, lambda *_: stop.set())
    os_signal.signal(os_signal.SIGINT, lambda *_: stop.set())

    store = None
    while not stop.is_set():
        started = time.monotonic()
        try:
            if store is None:
                import clickhouse_connect
                store = Store(clickhouse_connect.get_client(
                    host=os.environ["TRACEMELT_CLICKHOUSE_HOST"],
                    port=int(os.environ.get("TRACEMELT_CLICKHOUSE_HTTP_PORT", "8123")),
                    username=os.environ["TRACEMELT_CLICKHOUSE_ALERT_USER"],
                    password=os.environ["TRACEMELT_CLICKHOUSE_ALERT_PASSWORD"],
                    database=os.environ["TRACEMELT_CLICKHOUSE_DB"],
                    connect_timeout=5, send_receive_timeout=15))
                store.ensure_table()
            results = run_once(rules, store, deliver)
            log.info("evaluated %d rules in %.2fs: %s", len(rules), time.monotonic() - started,
                     ", ".join(f"{k}={v}" for k, v in sorted(results.items())) or "none")
        except Exception as exc:  # storage unreachable: keep running and try again
            store = None
            log.error("evaluation pass failed: %s", str(exc)[:300])
        stop.wait(max(1.0, interval - (time.monotonic() - started)))
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
