"""Unit tests: auth and input validation. Storage is replaced by a fake that records calls."""

import os

os.environ.update(
    TRACEMELT_API_TOKEN="test-token",
    TRACEMELT_CLICKHOUSE_HOST="unused",
    TRACEMELT_CLICKHOUSE_READER_USER="unused",
    TRACEMELT_CLICKHOUSE_READER_PASSWORD="unused",
    TRACEMELT_CLICKHOUSE_DB="unused",
)

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError
from fastapi.testclient import TestClient

from app import main

AUTH = {"Authorization": "Bearer test-token"}
TRACE = "a" * 32


class FakeResult:
    column_names = ("n",)
    result_rows = [(1,)]


class FakeClient:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def query(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        if self.error:
            raise self.error
        return FakeResult()


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(main, "get_client", lambda: client)
    return client


@pytest.fixture
def http():
    return TestClient(main.app)


PROTECTED = ["/api/services", "/api/traces", f"/api/traces/{TRACE}", "/api/logs",
             "/api/events", "/api/metrics", "/api/metrics/gauge?name=x"]


@pytest.mark.parametrize("path", PROTECTED)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "test-token"},
                                     {"Authorization": "Basic test-token"}])
def test_rejects_missing_or_bad_token(http, fake, path, headers):
    assert http.get(path, headers=headers).status_code == 401
    assert fake.calls == []


@pytest.mark.parametrize("path", PROTECTED)
def test_accepts_valid_token(http, fake, path):
    assert http.get(path, headers=AUTH).status_code == 200


def test_health_needs_no_token(http, fake):
    assert http.get("/api/health").json() == {"status": "ok"}


@pytest.mark.parametrize("path", [
    "/api/traces/abc",                                # too short
    f"/api/traces/{'A' * 32}",                        # upper case
    f"/api/traces/{'g' * 32}",                        # not hex
    f"/api/traces/{'a' * 33}",                        # too long
    "/api/logs?trace_id=1%27%20OR%201=1",             # injection attempt
    "/api/logs?limit=1001",
    "/api/logs?limit=0",
    "/api/logs?since_minutes=10081",
    f"/api/logs?q={'x' * 201}",
    f"/api/traces?service={'x' * 201}",
    "/api/metrics/gauge",                             # name required
    f"/api/metrics/gauge?name={'x' * 256}",
    "/api/metrics/gauge?name=x&step_seconds=5",
    "/api/metrics/gauge?name=x&since_minutes=10080&step_seconds=10",  # too many buckets
])
def test_rejects_invalid_input_before_storage(http, fake, path):
    assert http.get(path, headers=AUTH).status_code == 422
    assert fake.calls == []


def test_user_input_is_bound_not_interpolated(http, fake):
    hostile = "x' OR 1=1 --"
    assert http.get("/api/logs", params={"q": hostile, "service": hostile}, headers=AUTH).status_code == 200
    sql, parameters = fake.calls[0]
    assert hostile not in sql
    assert parameters["q"] == hostile and parameters["service"] == hostile


@pytest.mark.parametrize("message,status", [
    ("Code: 159. DB::Exception: Timeout exceeded", 504),
    ("Code: 241. DB::Exception: Memory limit exceeded", 422),
    ("Code: 396. DB::Exception: Limit for result exceeded", 422),
    ("Code: 62. DB::Exception: Syntax error near secret_table", 502),
])
def test_storage_errors_map_to_status_without_leaking(http, monkeypatch, message, status):
    client = FakeClient(error=DatabaseError(message))
    monkeypatch.setattr(main, "get_client", lambda: client)
    response = http.get("/api/logs", headers=AUTH)
    assert response.status_code == status
    assert "DB::Exception" not in response.text and "secret_table" not in response.text


def test_unknown_trace_is_404(http, monkeypatch):
    class Empty(FakeClient):
        def query(self, sql, parameters=None):
            result = FakeResult()
            result.result_rows = []
            return result
    monkeypatch.setattr(main, "get_client", lambda: Empty())
    assert http.get(f"/api/traces/{TRACE}", headers=AUTH).status_code == 404


# --- browser session -------------------------------------------------------

def test_sign_in_with_wrong_token_sets_no_cookie(http):
    response = http.post("/api/session", json={"token": "wrong"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_sign_in_sets_hardened_cookie_that_is_not_the_token(http):
    response = http.post("/api/session", json={"token": "test-token"})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "test-token" not in cookie


def test_session_cookie_grants_access_and_sign_out_revokes_it(http, fake):
    assert http.get("/api/session").status_code == 401
    http.post("/api/session", json={"token": "test-token"})
    assert http.get("/api/session").json() == {"signed_in": True}
    assert http.get("/api/traces").status_code == 200
    assert http.delete("/api/session").status_code == 204
    assert http.get("/api/traces").status_code == 401


def test_forged_cookie_is_rejected(http, fake):
    http.cookies.set("tracemelt_session", "0" * 64)
    assert http.get("/api/traces").status_code == 401
    assert fake.calls == []


def test_cookie_is_marked_secure_when_configured(http, monkeypatch):
    monkeypatch.setenv("TRACEMELT_COOKIE_SECURE", "1")
    assert "Secure" in http.post("/api/session", json={"token": "test-token"}).headers["set-cookie"]


def test_security_headers_on_api_and_ui(http, fake):
    for path in ("/api/health", "/"):
        headers = http.get(path).headers
        assert "default-src 'self'" in headers["content-security-policy"]
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert headers["x-content-type-options"] == "nosniff"
    assert http.get("/api/health").headers["cache-control"] == "no-store"


def test_ui_shell_is_served_without_a_token(http):
    response = http.get("/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
