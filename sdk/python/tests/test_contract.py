"""Runs the real SDK with in-memory exporters and checks what would be sent.

The SDK starts once per process, so this module starts it once and every test reads the result.
"""

import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import tracemelt


@pytest.fixture(scope="module")
def sent():
    spans, logs, reader = InMemorySpanExporter(), InMemoryLogRecordExporter(), InMemoryMetricReader()
    handlers_before = list(logging.getLogger().handlers)
    assert tracemelt.init(endpoint="http://unused:4318", service_name="contract",
                          _exporters={"trace": spans, "log": logs, "metric_reader": reader}) is True
    assert tracemelt.init(endpoint="http://other:4318") is True      # a second init is ignored
    assert logging.getLogger().handlers == handlers_before           # logging is not captured by default

    with trace.get_tracer("test").start_as_current_span("checkout") as span:
        trace_id = span.get_span_context().trace_id
        tracemelt.event("order.placed", {"product": "kettle", "quantity": 2, "value_cents": 2598,
                                         "order_id": 12345, "user_id": "u-1", "nested": {"a": 1}})
    tracemelt.event("order.placed", {"quantity": 1, "value_cents": 1000})
    tracemelt.count("requests")
    tracemelt.count("requests", 4, {"route": "/x"})
    tracemelt.gauge("queue.depth", 7)
    tracemelt.gauge("temperature", -3.5)
    tracemelt.timing("latency", 12.5)

    # None of these may raise or record anything.
    for bad in (None, float("nan"), float("inf"), "5", {}, [], object(), True):
        tracemelt.count("bad.count", bad)
        tracemelt.gauge("bad.gauge", bad)
        tracemelt.timing("bad.timing", bad)
    tracemelt.count("requests", -1)
    tracemelt.timing("latency", -5)
    for name in (None, "", "has space", 42, {}, "x" * 500):
        tracemelt.count(name)
        tracemelt.gauge(name, 1)
        tracemelt.timing(name, 1)
        tracemelt.event(name, {"a": 1})
    tracemelt.event("weird.attrs", "not a dict")
    tracemelt.event("weird.attrs", None)
    tracemelt.count()                # missing arguments are swallowed too
    tracemelt.gauge("only.name")

    for provider in tracemelt._state.providers:
        provider.force_flush()
    points = {}
    for resource_metrics in reader.get_metrics_data().resource_metrics:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                points[metric.name] = list(metric.data.data_points)
    result = {"trace_id": trace_id, "spans": list(spans.get_finished_spans()),
              "logs": list(logs.get_finished_logs()), "points": points}
    tracemelt.shutdown()
    return result


def record_of(item):
    return getattr(item, "log_record", item)


def values(sent, name, match=lambda a: True):
    return [p.value for p in sent["points"][name] if match(dict(p.attributes))]


def test_events_are_log_records_with_the_tracemelt_tags(sent):
    records = [record_of(r) for r in sent["logs"] if record_of(r).body == "order.placed"]
    assert len(records) == 2
    first = records[0]
    assert first.attributes["tracemelt.event"] == "true"
    assert first.attributes["event.name"] == "order.placed"
    assert first.severity_text == "INFO"
    assert (first.attributes["product"], first.attributes["quantity"], first.attributes["user_id"]) == ("kettle", 2, "u-1")
    assert "nested" not in first.attributes


def test_an_event_emitted_inside_a_span_carries_its_trace_id(sent):
    first = next(record_of(r) for r in sent["logs"] if record_of(r).body == "order.placed")
    assert first.trace_id == sent["trace_id"]
    assert len(sent["spans"]) == 1


def test_events_are_counted_by_name(sent):
    assert values(sent, "tracemelt.events", lambda a: a.get("event.name") == "order.placed") == [2]


def test_numeric_attributes_are_summed_and_identifiers_are_not(sent):
    assert values(sent, "tracemelt.event.order.placed.quantity") == [3]
    assert values(sent, "tracemelt.event.order.placed.value_cents") == [3598]
    assert "tracemelt.event.order.placed.order_id" not in sent["points"]
    assert "tracemelt.event.order.placed.user_id" not in sent["points"]


def test_count_gauge_and_timing_record_without_declaring_instruments(sent):
    assert values(sent, "requests", lambda a: "route" not in a) == [1]
    assert values(sent, "requests", lambda a: a.get("route") == "/x") == [4]
    assert values(sent, "queue.depth") == [7]
    assert values(sent, "temperature") == [-3.5]
    (latency,) = sent["points"]["latency"]
    assert (latency.count, latency.sum) == (1, 12.5)


def test_bad_values_and_bad_names_recorded_nothing(sent):
    for name in ("bad.count", "bad.gauge", "bad.timing", "only.name"):
        assert name not in sent["points"]
    assert not any(" " in name for name in sent["points"])


def test_after_shutdown_every_call_is_a_quiet_no_op(sent):
    tracemelt.count("requests")
    tracemelt.event("order.placed")
    tracemelt.gauge("g", 1)
    tracemelt.timing("t", 1)
    tracemelt.shutdown()
    assert tracemelt.is_enabled() is False
