"""tracemelt for Python. Status: prototype.

A thin layer over the OpenTelemetry SDK: it wires OTLP export to a tracemelt collector
and adds four one-line helpers. Every public function is fail-open: it returns normally
whatever goes wrong, and telemetry problems never reach the application.
"""

from __future__ import annotations

import atexit
import functools
import sys
import threading

from . import _safe
from ._config import resolve

__all__ = ["init", "count", "gauge", "timing", "event", "shutdown", "is_enabled"]

MAX_INSTRUMENTS = 500          # distinct metric names this process may create
MAX_QUEUE = 2048
MAX_BATCH = 512
SCHEDULE_DELAY_MS = 5000
EXPORT_TIMEOUT_S = 5           # per request; also bounds how long exit can be delayed
METRIC_INTERVAL_MS = 30000
SHUTDOWN_TIMEOUT_S = 5.0


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = False
        self.enabled = False
        self.debug = False
        self.providers = []
        self.meter = None
        self.logger = None
        self.severity = None
        self.instruments = {}
        self.warned = set()
        self.logging_handler = None


_state = _State()


def _warn(key: str, message: str) -> None:
    if key in _state.warned:
        return
    _state.warned.add(key)
    try:
        sys.stderr.write(f"tracemelt: {message}\n")
    except Exception:
        pass


def _guard(default=None):
    def wrap(fn):
        @functools.wraps(fn)
        def guarded(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # telemetry must never break the caller
                if _state.debug:
                    _warn(f"error:{fn.__name__}", f"{fn.__name__} failed: {exc}")
                return default
        return guarded
    return wrap


@_guard(default=False)
def init(endpoint=None, token=None, service_name=None, capture_logging=None, debug=None,
         disabled=False, _exporters=None, _queue=None) -> bool:
    """Starts telemetry. Returns whether it is on. Never raises. Later calls do nothing."""
    with _state.lock:
        if _state.started:
            return _state.enabled
        _state.started = True
        config = resolve(endpoint, token, service_name, capture_logging, debug, disabled)
        _state.debug = config.debug
        if not config.enabled:
            _warn("disabled", f"telemetry is off: {config.reason}")
            return False

        from opentelemetry import _logs, metrics, trace
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if not config.debug:
            # The upstream exporters log every failed attempt. Keep an unreachable collector quiet.
            import logging
            logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)

        exporters = _exporters
        if exporters is None:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            common = dict(headers=config.headers, timeout=EXPORT_TIMEOUT_S)
            exporters = {
                "trace": OTLPSpanExporter(endpoint=f"{config.endpoint}/v1/traces", **common),
                "metric": OTLPMetricExporter(endpoint=f"{config.endpoint}/v1/metrics", **common),
                "log": OTLPLogExporter(endpoint=f"{config.endpoint}/v1/logs", **common),
            }
        queue = dict(max_queue_size=MAX_QUEUE, max_export_batch_size=MAX_BATCH,
                     schedule_delay_millis=SCHEDULE_DELAY_MS, export_timeout_millis=EXPORT_TIMEOUT_S * 1000)
        queue.update(_queue or {})

        resource = Resource.create({"service.name": config.service_name})
        # shutdown_on_exit is off: this module registers one exit hook with a time limit instead.
        tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        tracer_provider.add_span_processor(BatchSpanProcessor(exporters["trace"], **queue))
        reader = exporters.get("metric_reader") or PeriodicExportingMetricReader(
            exporters["metric"], export_interval_millis=METRIC_INTERVAL_MS, export_timeout_millis=EXPORT_TIMEOUT_S * 1000)
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader], shutdown_on_exit=False)
        logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporters["log"], **queue))

        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)
        _logs.set_logger_provider(logger_provider)

        _state.providers = [tracer_provider, logger_provider, meter_provider]
        _state.meter = meter_provider.get_meter("tracemelt")
        _state.logger = logger_provider.get_logger("tracemelt")
        _state.severity = _logs.SeverityNumber.INFO
        _state.enabled = True

        if config.capture_logging:
            import logging
            from opentelemetry.sdk._logs import LoggingHandler
            _state.logging_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
            logging.getLogger().addHandler(_state.logging_handler)

        atexit.register(shutdown)
        return True


def _instrument(kind: str, name: str):
    key = (kind, name)
    found = _state.instruments.get(key)
    if found is not None:
        return found
    with _state.lock:
        found = _state.instruments.get(key)
        if found is not None:
            return found
        if len(_state.instruments) >= MAX_INSTRUMENTS:
            _warn("instruments", f"more than {MAX_INSTRUMENTS} metric names, new ones are dropped")
            return None
        if kind == "counter":
            found = _state.meter.create_counter(name)
        elif kind == "gauge":
            found = _state.meter.create_gauge(name)
        else:
            found = _state.meter.create_histogram(name, unit="ms")
        _state.instruments[key] = found
        return found


def _record(kind: str, name, value, attributes) -> None:
    if not _state.enabled:
        return
    if not _safe.valid_name(name):
        _warn(f"name:{str(name)[:40]}", "metric name rejected, see the SDK reference for the allowed form")
        return
    if not _safe.is_number(value) or (kind != "gauge" and value < 0):
        return
    target = _instrument(kind, name)
    if target is None:
        return
    clean = _safe.attributes(attributes)
    if kind == "counter":
        target.add(value, clean)
    elif kind == "gauge":
        target.set(value, clean)
    else:
        target.record(value, clean)


@_guard()
def count(name, value=1, attributes=None) -> None:
    """Adds to a counter. count("orders") adds 1. Negative values are ignored."""
    _record("counter", name, value, attributes)


@_guard()
def gauge(name, value, attributes=None) -> None:
    """Records the current value of something that goes up and down."""
    _record("gauge", name, value, attributes)


@_guard()
def timing(name, milliseconds, attributes=None) -> None:
    """Records a duration in milliseconds."""
    _record("histogram", name, milliseconds, attributes)


@_guard()
def event(name, attributes=None) -> None:
    """Emits a business event as a log record tagged for tracemelt, and counts it.

    Numeric attributes are treated as measurements and summed, unless the key looks
    like an identifier. Pass identifiers as strings.
    """
    if not _state.enabled:
        return
    if not _safe.valid_name(name):
        _warn(f"event:{str(name)[:40]}", "event name rejected, see the SDK reference for the allowed form")
        return
    clean = _safe.attributes(attributes)
    _state.logger.emit(severity_number=_state.severity, severity_text="INFO", body=name,
                       attributes={**clean, "tracemelt.event": "true", "event.name": name})
    counter = _instrument("counter", "tracemelt.events")
    if counter is not None:
        counter.add(1, {"event.name": name})
    for key, value in _safe.summable(clean):
        total = _instrument("counter", f"tracemelt.event.{name}.{key}")
        if total is not None:
            total.add(value)


def is_enabled() -> bool:
    return _state.enabled


def shutdown(timeout: float = SHUTDOWN_TIMEOUT_S) -> None:
    """Flushes what is queued and stops. Returns within `timeout` seconds whatever happens."""
    try:
        with _state.lock:
            if not _state.enabled:
                return
            _state.enabled = False
            providers, _state.providers = _state.providers, []
            handler, _state.logging_handler = _state.logging_handler, None
        if handler is not None:
            import logging
            logging.getLogger().removeHandler(handler)

        def work():
            for provider in providers:
                try:
                    provider.shutdown()
                except Exception:
                    pass

        # A daemon thread, so a collector that never answers cannot keep the process alive.
        worker = threading.Thread(target=work, name="tracemelt-shutdown", daemon=True)
        worker.start()
        try:
            limit = max(0.0, float(timeout))
        except (TypeError, ValueError):
            limit = SHUTDOWN_TIMEOUT_S
        worker.join(limit)
    except Exception:
        pass
