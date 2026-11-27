import pytest

from tracemelt import _safe
from tracemelt._config import resolve


def test_needs_an_endpoint():
    config = resolve(env={})
    assert not config.enabled and "no endpoint" in config.reason


def test_reads_tracemelt_then_otel_variables():
    c = resolve(env={"TRACEMELT_ENDPOINT": "https://t.example.com/", "TRACEMELT_INGEST_TOKEN": "abc", "TRACEMELT_SERVICE_NAME": "api"})
    assert (c.enabled, c.endpoint, c.service_name, c.headers) == (True, "https://t.example.com", "api", {"Authorization": "Bearer abc"})
    o = resolve(env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4318", "OTEL_SERVICE_NAME": "web"})
    assert (o.enabled, o.endpoint, o.service_name, o.headers) == (True, "http://c:4318", "web", {})


def test_arguments_win_over_the_environment():
    c = resolve(endpoint="http://a:1", service_name="x", token="t", env={"TRACEMELT_ENDPOINT": "http://b:2", "TRACEMELT_SERVICE_NAME": "y"})
    assert (c.endpoint, c.service_name, c.headers["Authorization"]) == ("http://a:1", "x", "Bearer t")


@pytest.mark.parametrize("bad", ["not a url", "ftp://host", "file:///etc/passwd", "://", "http://", "http://host:99999", "javascript:alert(1)"])
def test_invalid_endpoint_turns_telemetry_off_instead_of_raising(bad):
    assert resolve(env={"TRACEMELT_ENDPOINT": bad}).enabled is False


def test_logging_capture_is_off_unless_asked_for():
    env = {"TRACEMELT_ENDPOINT": "http://c:4318"}
    assert resolve(env=env).capture_logging is False
    assert resolve(env={**env, "TRACEMELT_CAPTURE_LOGGING": "true"}).capture_logging is True
    assert resolve(capture_logging=True, env=env).capture_logging is True


def test_can_be_disabled():
    env = {"TRACEMELT_ENDPOINT": "http://c:4318"}
    assert resolve(env={**env, "TRACEMELT_DISABLED": "true"}).enabled is False
    assert resolve(env={**env, "OTEL_SDK_DISABLED": "true"}).enabled is False
    assert resolve(disabled=True, env=env).enabled is False


def test_attributes_keep_only_primitives_and_are_bounded():
    assert len(_safe.attributes({f"k{i}": i for i in range(100)})) == 32
    kept = _safe.attributes({"s": "x", "n": 1, "f": 1.5, "b": True, "o": {}, "a": [1], "none": None,
                             "nan": float("nan"), "inf": float("inf"), 5: "non-string key"})
    assert kept == {"s": "x", "n": 1, "f": 1.5, "b": True}
    assert len(_safe.attributes({"long": "x" * 5000})["long"]) == 1024
    for junk in (None, "str", 5, [1, 2]):
        assert _safe.attributes(junk) == {}


def test_only_numeric_measurements_are_summable_never_identifiers():
    keys = lambda d: [k for k, _ in _safe.summable(d)]
    assert keys({"value_cents": 12999, "quantity": 2, "cart.items": 3}) == ["value_cents", "quantity", "cart.items"]
    assert keys({"order_id": 12345, "id": 7, "user.id": 9, "zip": 94107, "status": 200, "port": 8080,
                 "phone": 5551234, "card_number": 4111, "year": 2026, "version": 3}) == []
    assert keys({"currency": "USD", "paid": True, "amount": "12.50", "refund": -5}) == []


def test_names_are_validated():
    for ok in ("orders", "order.placed", "http.server/latency", "a_b-c"):
        assert _safe.valid_name(ok)
    for bad in ("", " x", "1abc", "has space", "x" * 300, 5, None, {}):
        assert not _safe.valid_name(bad)
