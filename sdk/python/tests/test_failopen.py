"""Runs small programs in child processes, the way a user would, against collectors that misbehave."""

import os
import socket
import subprocess
import sys
import textwrap
import threading
import time

APP = textwrap.dedent("""
    import os, time, tracemelt
    from opentelemetry import trace
    tracemelt.init()
    with trace.get_tracer("app").start_as_current_span("work"):
        tracemelt.event("order.placed", {"quantity": 1})
    tracemelt.count("requests"); tracemelt.gauge("queue", 1); tracemelt.timing("latency", 3)
    print("app result: 42", flush=True)
    started = time.time()
    tracemelt.shutdown(float(os.environ.get("SHUTDOWN_S", "5")))
    print("shutdown ms: %d" % ((time.time() - started) * 1000), flush=True)
""")


def run(env, args=None, timeout=40):
    started = time.time()
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("TRACEMELT_", "OTEL_"))}
    result = subprocess.run(args or [sys.executable, "-c", APP], env={**clean, **env},
                            capture_output=True, text=True, timeout=timeout)
    return result, time.time() - started


def test_the_app_runs_with_no_configuration_at_all():
    result, _ = run({})
    assert result.returncode == 0, result.stderr
    assert "app result: 42" in result.stdout
    assert "telemetry is off: no endpoint set" in result.stderr


def test_the_app_runs_with_an_invalid_endpoint():
    result, _ = run({"TRACEMELT_ENDPOINT": "not a url"})
    assert result.returncode == 0, result.stderr
    assert "app result: 42" in result.stdout
    assert "telemetry is off" in result.stderr


def test_the_app_runs_when_nothing_listens_on_the_collector_port():
    result, seconds = run({"TRACEMELT_ENDPOINT": "http://127.0.0.1:1", "TRACEMELT_INGEST_TOKEN": "x", "TRACEMELT_SERVICE_NAME": "app"})
    assert result.returncode == 0, result.stderr
    assert "app result: 42" in result.stdout
    assert "Traceback" not in result.stderr
    assert seconds < 12, f"took {seconds:.1f}s"


def test_exit_without_calling_shutdown_is_not_held_up():
    app = APP.split("started = time.time()")[0]
    result, seconds = run({"TRACEMELT_ENDPOINT": "http://127.0.0.1:1"}, [sys.executable, "-c", app])
    assert result.returncode == 0, result.stderr
    assert "app result: 42" in result.stdout
    assert seconds < 12, f"took {seconds:.1f}s"


def test_a_collector_that_never_answers_cannot_hold_the_app_past_the_shutdown_timeout():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    held = []
    stop = threading.Event()

    def accept():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])      # accept and never answer
            except OSError:
                pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        result, seconds = run({"TRACEMELT_ENDPOINT": f"http://127.0.0.1:{server.getsockname()[1]}", "SHUTDOWN_S": "1"})
    finally:
        stop.set()
        thread.join()
        for conn in held:
            conn.close()
        server.close()
    assert result.returncode == 0, result.stderr
    assert "app result: 42" in result.stdout
    waited = int(result.stdout.split("shutdown ms: ")[1].split()[0])
    assert 900 <= waited < 2500, f"shutdown waited {waited} ms for a 1000 ms timeout"
    assert seconds < 6, f"process took {seconds:.1f}s to exit"


def test_the_cli_runs_a_script_and_passes_its_arguments(tmp_path):
    script = tmp_path / "app.py"
    script.write_text("import sys, tracemelt\ntracemelt.count('x')\nprint('args:', sys.argv[1:], __name__)\n")
    result, _ = run({"TRACEMELT_ENDPOINT": "http://127.0.0.1:1"}, [sys.executable, "-m", "tracemelt._cli", str(script), "a", "--b"])
    assert result.returncode == 0, result.stderr
    assert "args: ['a', '--b'] __main__" in result.stdout


def test_the_cli_keeps_the_scripts_own_exit_code_and_errors(tmp_path):
    script = tmp_path / "boom.py"
    script.write_text("import sys\nsys.exit(7)\n")
    result, _ = run({}, [sys.executable, "-m", "tracemelt._cli", str(script)])
    assert result.returncode == 7


def test_logging_capture_is_opt_in_and_keeps_normal_output():
    app = "import logging, tracemelt\nlogging.basicConfig(level=logging.INFO)\ntracemelt.init()\nlogging.getLogger('app').info('hello')\nprint(len(logging.getLogger().handlers))\ntracemelt.shutdown(0.2)\n"
    off, _ = run({"TRACEMELT_ENDPOINT": "http://127.0.0.1:1"}, [sys.executable, "-c", app])
    on, _ = run({"TRACEMELT_ENDPOINT": "http://127.0.0.1:1", "TRACEMELT_CAPTURE_LOGGING": "true"}, [sys.executable, "-c", app])
    assert off.returncode == 0 and on.returncode == 0
    assert "hello" in off.stderr and "hello" in on.stderr
    assert off.stdout.strip() == "1" and on.stdout.strip() == "2"


OVERLOAD = textwrap.dedent("""
    import threading, time, tracemelt, resource, sys
    from opentelemetry import trace
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export import SpanExporter

    class Stuck(SpanExporter):
        received = 0
        def export(self, spans):
            Stuck.received += len(spans)
            threading.Event().wait()          # never returns
        def shutdown(self): threading.Event().wait()

    tracemelt.init(endpoint="http://unused:4318", _exporters={"trace": Stuck(), "log": InMemoryLogRecordExporter(), "metric_reader": InMemoryMetricReader()},
                   _queue={"max_queue_size": 100, "max_export_batch_size": 10, "schedule_delay_millis": 5})
    tracer = trace.get_tracer("t")
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for _ in range(200000):
        tracer.start_span("work").end()
    time.sleep(0.2)
    grown = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / (1048576 if sys.platform == "darwin" else 1024)
    started = time.time()
    tracemelt.shutdown(0.3)
    print("received=%d grown_mb=%d shutdown_ms=%d" % (Stuck.received, grown, (time.time() - started) * 1000), flush=True)
""")


def test_a_stuck_exporter_drops_spans_instead_of_queueing_them_forever():
    result, seconds = run({}, [sys.executable, "-c", OVERLOAD], timeout=120)
    assert result.returncode == 0, result.stderr
    fields = dict(part.split("=") for part in result.stdout.split())
    assert int(fields["received"]) <= 10, "only one batch may be in flight"
    assert int(fields["grown_mb"]) < 100, f"memory grew by {fields['grown_mb']} MB for 200000 spans"
    assert int(fields["shutdown_ms"]) < 1500
