"""Unit tests for the alert engine and webhook egress controls. No network, no ClickHouse."""

import socket

import pytest

from app import alerts, webhook

ALLOWED = frozenset({"hooks.example.com", "webhook-sink", "169.254.169.254", "localhost", "10.0.0.5", "[::1]", "::1"})
PRIVATE = frozenset({"webhook-sink"})


def resolver(*addresses):
    def resolve(host, port, type=None):
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]
    return resolve


def blocked(url, *addresses, allowed=ALLOWED, private=PRIVATE):
    with pytest.raises(webhook.Blocked) as info:
        webhook.check(url, allowed, private, resolve=resolver(*addresses))
    return str(info.value)


# --- webhook egress --------------------------------------------------------

def test_public_allowlisted_host_is_accepted_and_pinned():
    d = webhook.check("https://hooks.example.com/services/T1?x=1", ALLOWED, PRIVATE, resolve=resolver("93.184.216.34"))
    assert (d.host, d.ip, d.port, d.tls, d.path) == ("hooks.example.com", "93.184.216.34", 443, True, "/services/T1?x=1")


def test_host_not_on_allowlist_is_blocked_before_resolving():
    def never(*a, **k):
        raise AssertionError("resolved a host that is not allowlisted")
    with pytest.raises(webhook.Blocked, match="allowlist"):
        webhook.check("https://evil.example.net/", ALLOWED, PRIVATE, resolve=never)


def test_empty_allowlist_blocks_everything():
    assert "allowlist" in blocked("https://hooks.example.com/", "93.184.216.34", allowed=frozenset())


@pytest.mark.parametrize("url,address,reason", [
    ("http://169.254.169.254/latest/meta-data/", "169.254.169.254", "link-local"),   # cloud metadata
    ("http://hooks.example.com/", "169.254.169.254", "link-local"),                  # public name, metadata address
    ("http://localhost/", "127.0.0.1", "loopback"),
    ("http://hooks.example.com/", "127.0.0.1", "loopback"),
    ("http://[::1]/", "::1", "loopback"),
    ("http://hooks.example.com/", "::ffff:127.0.0.1", "loopback"),                   # IPv4-mapped IPv6
    ("http://hooks.example.com/", "::ffff:169.254.169.254", "link-local"),
    ("http://10.0.0.5/", "10.0.0.5", "private"),
    ("http://hooks.example.com/", "10.1.2.3", "private"),
    ("http://hooks.example.com/", "172.16.0.9", "private"),
    ("http://hooks.example.com/", "192.168.1.1", "private"),
    ("http://hooks.example.com/", "fd00::1", "private"),
    ("http://hooks.example.com/", "fe80::1", "link-local"),
    ("http://hooks.example.com/", "0.0.0.0", "reserved"),
    ("http://hooks.example.com/", "224.0.0.1", "reserved"),
])
def test_non_public_addresses_are_blocked(url, address, reason):
    assert reason in blocked(url, address)


def test_one_bad_address_among_several_blocks_the_host():
    assert "loopback" in blocked("https://hooks.example.com/", "93.184.216.34", "127.0.0.1")


def test_private_host_list_allows_private_but_never_loopback_or_metadata():
    d = webhook.check("http://webhook-sink:8080/alerts", ALLOWED, PRIVATE, resolve=resolver("172.25.0.7"))
    assert (d.ip, d.port, d.tls) == ("172.25.0.7", 8080, False)
    assert "loopback" in blocked("http://webhook-sink:8080/", "127.0.0.1")
    assert "link-local" in blocked("http://webhook-sink:8080/", "169.254.169.254")


@pytest.mark.parametrize("url,reason", [
    ("ftp://hooks.example.com/", "scheme"),
    ("file:///etc/passwd", "scheme"),
    ("gopher://hooks.example.com/", "scheme"),
    ("https://user:pw@hooks.example.com/", "credentials"),
    ("https:///path", "no host"),
    ("https://hooks.example.com:99999/", "malformed"),
])
def test_bad_urls_are_blocked(url, reason):
    assert reason in blocked(url, "93.184.216.34")


def test_unresolvable_host_is_blocked():
    def fail(*a, **k):
        raise socket.gaierror("no such host")
    with pytest.raises(webhook.Blocked, match="does not resolve"):
        webhook.check("https://hooks.example.com/", ALLOWED, PRIVATE, resolve=fail)


# --- rules -----------------------------------------------------------------

GOOD = '''
[[rule]]
name = "payments-failed-spans"
signal = "error_spans"
service = "payments"
comparator = ">"
threshold = 5
window_seconds = 60
cooldown_seconds = 300
webhook_url = "https://hooks.example.com/x"
'''


def test_parses_a_valid_rule():
    (rule,) = alerts.parse_rules(GOOD)
    assert (rule.name, rule.signal, rule.threshold, rule.window_seconds) == ("payments-failed-spans", "error_spans", 5, 60)


def test_empty_file_means_no_rules():
    assert alerts.parse_rules("") == []


@pytest.mark.parametrize("change,message", [
    ('signal = "error_spans"|signal = "metric_p95"', "signal must be one of"),
    ('comparator = ">"|comparator = "!="', "comparator must be one of"),
    ("threshold = 5|threshold = \"5\"", "threshold must be a number"),
    ("window_seconds = 60|window_seconds = 1", "window_seconds"),
    ("cooldown_seconds = 300|cooldown_seconds = -1", "cooldown_seconds"),
    ('name = "payments-failed-spans"|name = "Bad Name"', "name must be"),
    ('service = "payments"|service = "payments"\nmetric = "x"', "metric is only used by metric_avg"),
    ('service = "payments"|service = "payments"\nsearch = "x"', "only used by log_count"),
    ('service = "payments"|service = "payments"\ngroup_by = "x"', "unknown field group_by"),
    ('signal = "error_spans"|signal = "metric_avg"', "needs a metric name"),
])
def test_invalid_rules_are_rejected_with_a_reason(change, message):
    old, new = change.split("|")
    with pytest.raises(alerts.RuleError, match=message):
        alerts.parse_rules(GOOD.replace(old, new))


def test_duplicate_names_are_rejected():
    with pytest.raises(alerts.RuleError, match="duplicate"):
        alerts.parse_rules(GOOD + GOOD)


def test_not_toml_is_rejected():
    with pytest.raises(alerts.RuleError, match="not valid TOML"):
        alerts.parse_rules("[[rule\nname=")


# --- evaluation ------------------------------------------------------------

class FakeStore:
    def __init__(self, value, samples=1, since=None):
        self.value, self.samples, self.since, self.rows = value, samples, since, []

    def measure(self, rule):
        return self.value, self.samples

    def seconds_since_fired(self, rule):
        return self.since

    def record(self, kind, rule, value, outcome="", detail=""):
        self.rows.append((kind, outcome, detail))
        if kind == "fired":
            self.since = 0


def rule(**over):
    base = dict(name="r", signal="error_spans", comparator=">", threshold=5, window_seconds=60, cooldown_seconds=300)
    return alerts.Rule(**{**base, **over})


def no_delivery(*_):
    raise AssertionError("a webhook was attempted")


def test_below_threshold_records_nothing():
    store = FakeStore(5)
    assert alerts.evaluate(rule(), store, no_delivery) == "ok"
    assert store.rows == []


@pytest.mark.parametrize("comparator,value,fires", [(">", 6, True), (">", 5, False), (">=", 5, True),
                                                    ("<", 4, True), ("<", 5, False), ("<=", 5, True)])
def test_comparators(comparator, value, fires):
    result = alerts.evaluate(rule(comparator=comparator), FakeStore(value), no_delivery)
    assert (result == "fired") is fires


def test_fires_without_webhook_when_none_is_set():
    store = FakeStore(9)
    assert alerts.evaluate(rule(), store, no_delivery) == "fired"
    assert [row[0] for row in store.rows] == ["fired"]


def test_fired_row_is_written_before_delivery_and_outcome_is_recorded():
    store = FakeStore(9)
    seen = []

    def deliver(r, value):
        seen.append(list(store.rows))
        return "delivered", "http 200"

    assert alerts.evaluate(rule(webhook_url="https://hooks.example.com/x"), store, deliver) == "fired"
    assert [row[0] for row in seen[0]] == ["fired"]
    assert store.rows[1] == ("delivery", "delivered", "http 200")


def test_cooldown_suppresses_a_second_firing():
    store = FakeStore(9)
    r = rule()
    assert alerts.evaluate(r, store, no_delivery) == "fired"
    assert alerts.evaluate(r, store, no_delivery) == "cooling_down"
    assert len(store.rows) == 1


def test_cooldown_read_from_storage_survives_a_restart():
    assert alerts.evaluate(rule(), FakeStore(9, since=120), no_delivery) == "cooling_down"
    assert alerts.evaluate(rule(), FakeStore(9, since=301), no_delivery) == "fired"


def test_metric_with_no_data_does_not_fire_even_for_less_than():
    store = FakeStore(0, samples=0)
    assert alerts.evaluate(rule(signal="metric_avg", metric="queue.depth", comparator="<", threshold=1), store, no_delivery) == "no_data"
    assert store.rows == []


def test_blocked_destination_is_recorded_not_sent(monkeypatch):
    monkeypatch.setattr(webhook, "send", lambda *a: (_ for _ in ()).throw(AssertionError("sent to a blocked host")))
    monkeypatch.setattr(webhook.socket, "getaddrinfo", resolver("169.254.169.254"))
    deliver = alerts.make_deliver(frozenset({"169.254.169.254"}), frozenset())
    store = FakeStore(9)
    assert alerts.evaluate(rule(webhook_url="http://169.254.169.254/latest/meta-data/"), store, deliver) == "fired"
    assert store.rows[1][0:2] == ("delivery", "blocked") and "link-local" in store.rows[1][2]


def test_one_failing_rule_does_not_stop_the_others():
    class Flaky(FakeStore):
        def measure(self, r):
            if r.name == "broken":
                raise RuntimeError("storage timeout")
            return super().measure(r)

    results = alerts.run_once([rule(name="broken"), rule(name="fine")], Flaky(9), no_delivery)
    assert results == {"broken": "error", "fine": "fired"}


def test_queries_bind_rule_values_instead_of_interpolating():
    class Client:
        def __init__(self):
            self.calls = []

        def query(self, sql, parameters=None):
            self.calls.append((sql, parameters))
            return type("R", (), {"result_rows": [(0.0, 0)]})()

    client = Client()
    hostile = "x' OR 1=1 --"
    alerts.Store(client).measure(rule(signal="log_count", search=hostile, service=hostile))
    sql, parameters = client.calls[0]
    assert hostile not in sql and parameters["search"] == hostile
