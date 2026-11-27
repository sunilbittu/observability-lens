"""tracemelt query API. Status: prototype.

Read-only access to the otel_* tables that the collector's clickhouseexporter owns.
Every query is a fixed statement with server-side bound parameters; no SQL is built
from user input. Time, memory and row limits are enforced by the ClickHouse profile
of the read-only user, so this process cannot raise them.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import os
import threading
from pathlib import Path as FsPath
from typing import Annotated, Any

import clickhouse_connect
from clickhouse_connect import common
from clickhouse_connect.driver.exceptions import ClickHouseError
from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, HTTPException, Path, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger("tracemelt.api")

# One shared client serves concurrent requests, so it must not pin a session.
common.set_setting("autogenerate_session_id", False)

_client = None
_client_lock = threading.Lock()


def get_client():
    """Connect lazily so the API can start, and report unhealthy, while ClickHouse is down."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = clickhouse_connect.get_client(
                    host=os.environ["TRACEMELT_CLICKHOUSE_HOST"],
                    port=int(os.environ.get("TRACEMELT_CLICKHOUSE_HTTP_PORT", "8123")),
                    username=os.environ["TRACEMELT_CLICKHOUSE_READER_USER"],
                    password=os.environ["TRACEMELT_CLICKHOUSE_READER_PASSWORD"],
                    database=os.environ["TRACEMELT_CLICKHOUSE_DB"],
                    connect_timeout=5,
                    send_receive_timeout=15,
                )
    return _client


SESSION_COOKIE = "tracemelt_session"
SESSION_SECONDS = 12 * 3600


def _session_value() -> str:
    """Cookie value for the browser UI. Derived from the API token, so the token itself
    never reaches browser storage. Rotating the token ends every session."""
    key = os.environ["TRACEMELT_API_TOKEN"].encode()
    return hmac.new(key, b"tracemelt-session-v1", hashlib.sha256).hexdigest()


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def require_token(authorization: Annotated[str | None, Header()] = None,
                  tracemelt_session: Annotated[str | None, Cookie()] = None) -> None:
    """Accepts the API token as a bearer header, or the session cookie set by POST /api/session."""
    if authorization and authorization.startswith("Bearer ") and \
            _same(authorization[len("Bearer "):], os.environ["TRACEMELT_API_TOKEN"]):
        return
    if tracemelt_session and _same(tracemelt_session, _session_value()):
        return
    raise HTTPException(status_code=401, detail="missing or invalid token",
                        headers={"WWW-Authenticate": "Bearer"})


# ClickHouse error codes that mean a guardrail stopped the query.
_LIMIT_CODES = {
    "Code: 159": (504, "query exceeded the time limit"),
    "Code: 241": (422, "query exceeded the memory limit"),
    "Code: 396": (422, "query exceeded the result row limit"),
}


def run(sql: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        result = get_client().query(sql, parameters=parameters)
    except ClickHouseError as exc:
        text = str(exc)
        for code, (status, detail) in _LIMIT_CODES.items():
            if code in text:
                raise HTTPException(status_code=status, detail=detail) from exc
        log.error("clickhouse query failed: %s", text[:500])
        raise HTTPException(status_code=502, detail="storage query failed") from exc
    except Exception as exc:  # connection refused, DNS, timeout
        global _client
        _client = None
        log.error("clickhouse unreachable: %s", str(exc)[:500])
        raise HTTPException(status_code=503, detail="storage unavailable") from exc
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


# Shared, bounded query parameters.
Since = Annotated[int, Query(ge=1, le=10080, description="Look back this many minutes (max 7 days).")]
Limit = Annotated[int, Query(ge=1, le=1000)]
Service = Annotated[str | None, Query(max_length=200)]
TraceId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
TraceIdQuery = Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")]

# The exporter has written both spellings across versions.
_IS_ERROR = "lower(StatusCode) IN ('error', 'status_code_error')"

app = FastAPI(title="tracemelt query API", version="0.0.0", docs_url=None, redoc_url=None, openapi_url=None)
api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@app.get("/api/health")
def health() -> dict[str, str]:
    """Unauthenticated. Reports only whether storage answers."""
    try:
        get_client().query("SELECT 1")
    except Exception as exc:
        global _client
        _client = None
        raise HTTPException(status_code=503, detail="storage unavailable") from exc
    return {"status": "ok"}


class SignIn(BaseModel):
    token: str = Field(min_length=1, max_length=512)


@app.post("/api/session", status_code=204)
def sign_in(body: SignIn, response: Response) -> None:
    """Exchange the API token for an HttpOnly session cookie. Used by the browser UI."""
    if not _same(body.token, os.environ["TRACEMELT_API_TOKEN"]):
        raise HTTPException(status_code=401, detail="invalid token")
    response.set_cookie(SESSION_COOKIE, _session_value(), max_age=SESSION_SECONDS, path="/",
                        httponly=True, samesite="strict",
                        secure=os.environ.get("TRACEMELT_COOKIE_SECURE") == "1")


@app.delete("/api/session", status_code=204)
def sign_out(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@api.get("/session")
def session() -> dict[str, bool]:
    """Lets the UI ask whether it is signed in."""
    return {"signed_in": True}


@api.get("/services")
def services(since_minutes: Since = 60) -> list[dict[str, Any]]:
    return run(
        f"""
        SELECT ServiceName AS service, count() AS spans, countIf({_IS_ERROR}) AS error_spans
        FROM otel_traces
        WHERE Timestamp >= now() - toIntervalMinute({{since:UInt32}})
        GROUP BY ServiceName ORDER BY spans DESC LIMIT 500
        """,
        {"since": since_minutes},
    )


@api.get("/traces")
def traces(since_minutes: Since = 60, limit: Limit = 50, service: Service = None,
           errors_only: bool = False) -> list[dict[str, Any]]:
    return run(
        f"""
        SELECT TraceId AS trace_id,
               min(Timestamp) AS started_at,
               max(Duration) AS duration_ns,
               count() AS spans,
               countIf({_IS_ERROR}) AS error_spans,
               argMin(SpanName, Timestamp) AS first_span,
               argMin(ServiceName, Timestamp) AS first_service
        FROM otel_traces
        WHERE Timestamp >= now() - toIntervalMinute({{since:UInt32}})
          AND ({{service:String}} = '' OR TraceId IN (
                SELECT TraceId FROM otel_traces
                WHERE Timestamp >= now() - toIntervalMinute({{since:UInt32}}) AND ServiceName = {{service:String}}))
        GROUP BY TraceId
        HAVING {{errors_only:UInt8}} = 0 OR error_spans > 0
        ORDER BY started_at DESC LIMIT {{limit:UInt32}}
        """,
        {"since": since_minutes, "service": service or "", "errors_only": int(errors_only), "limit": limit},
    )


@api.get("/traces/{trace_id}")
def trace(trace_id: TraceId) -> list[dict[str, Any]]:
    spans = run(
        f"""
        SELECT SpanId AS span_id, ParentSpanId AS parent_span_id, SpanName AS name,
               ServiceName AS service, SpanKind AS kind, Timestamp AS started_at,
               Duration AS duration_ns, StatusCode AS status_code, StatusMessage AS status_message,
               {_IS_ERROR} AS is_error, SpanAttributes AS attributes
        FROM otel_traces
        WHERE TraceId = {{trace_id:String}}
        ORDER BY Timestamp LIMIT 5000
        """,
        {"trace_id": trace_id},
    )
    if not spans:
        raise HTTPException(status_code=404, detail="trace not found")
    return spans


def _logs(events_only: bool, since: int, limit: int, service: str | None, q: str | None,
          trace_id: str | None, event_name: str | None) -> list[dict[str, Any]]:
    return run(
        """
        SELECT Timestamp AS timestamp, ServiceName AS service, SeverityText AS severity,
               Body AS body, TraceId AS trace_id, SpanId AS span_id, LogAttributes AS attributes
        FROM otel_logs
        WHERE Timestamp >= now() - toIntervalMinute({since:UInt32})
          AND ({service:String} = '' OR ServiceName = {service:String})
          AND ({q:String} = '' OR positionCaseInsensitive(Body, {q:String}) > 0)
          AND ({trace_id:String} = '' OR TraceId = {trace_id:String})
          AND ({events_only:UInt8} = 0 OR LogAttributes['tracemelt.event'] = 'true')
          AND ({event_name:String} = '' OR LogAttributes['event.name'] = {event_name:String})
        ORDER BY Timestamp DESC LIMIT {limit:UInt32}
        """,
        {"since": since, "service": service or "", "q": q or "", "trace_id": trace_id or "",
         "events_only": int(events_only), "event_name": event_name or "", "limit": limit},
    )


@api.get("/logs")
def logs(since_minutes: Since = 60, limit: Limit = 100, service: Service = None,
         q: Annotated[str | None, Query(max_length=200)] = None,
         trace_id: TraceIdQuery = None) -> list[dict[str, Any]]:
    return _logs(False, since_minutes, limit, service, q, trace_id, None)


@api.get("/events")
def events(since_minutes: Since = 60, limit: Limit = 100, service: Service = None,
           name: Annotated[str | None, Query(max_length=200)] = None) -> list[dict[str, Any]]:
    return _logs(True, since_minutes, limit, service, None, None, name)


@api.get("/alerts")
def alert_events(since_minutes: Since = 1440, limit: Limit = 200,
                 rule: Annotated[str | None, Query(max_length=64)] = None) -> list[dict[str, Any]]:
    """What the alert engine recorded: one 'fired' row per firing, then one 'delivery' row per webhook attempt."""
    try:
        return run(
            """
            SELECT Timestamp AS timestamp, Kind AS kind, RuleName AS rule, Signal AS signal,
                   Value AS value, Comparator AS comparator, Threshold AS threshold,
                   WindowSeconds AS window_seconds, Outcome AS outcome, Detail AS detail
            FROM alert_events
            WHERE Timestamp >= now() - toIntervalMinute({since:UInt32})
              AND ({rule:String} = '' OR RuleName = {rule:String})
            ORDER BY Timestamp DESC LIMIT {limit:UInt32}
            """,
            {"since": since_minutes, "rule": rule or "", "limit": limit},
        )
    except HTTPException as exc:
        # The table is created by the alert engine on its first pass. Before that there is nothing to list.
        if exc.status_code == 502 and "Code: 60" in str(exc.__cause__):
            return []
        raise


@api.get("/metrics")
def metrics(since_minutes: Since = 60) -> list[dict[str, Any]]:
    """Metric names seen recently. Only gauges can be charted so far."""
    return run(
        """
        SELECT MetricName AS name, 'gauge' AS type, 1 AS chartable, count() AS points
        FROM otel_metrics_gauge WHERE TimeUnix >= now() - toIntervalMinute({since:UInt32})
        GROUP BY MetricName
        UNION ALL
        SELECT MetricName AS name, 'sum' AS type, 0 AS chartable, count() AS points
        FROM otel_metrics_sum WHERE TimeUnix >= now() - toIntervalMinute({since:UInt32})
        GROUP BY MetricName
        ORDER BY name LIMIT 2000
        """,
        {"since": since_minutes},
    )


@api.get("/metrics/gauge")
def gauge_series(name: Annotated[str, Query(min_length=1, max_length=255)],
                 since_minutes: Since = 60,
                 step_seconds: Annotated[int, Query(ge=10, le=3600)] = 60,
                 service: Service = None) -> list[dict[str, Any]]:
    """Per-service avg, min and max of a gauge in fixed time buckets."""
    if since_minutes * 60 // step_seconds > 1500:
        raise HTTPException(status_code=422, detail="too many buckets: raise step_seconds or lower since_minutes")
    return run(
        """
        SELECT toStartOfInterval(TimeUnix, toIntervalSecond({step:UInt32})) AS bucket,
               ServiceName AS service, avg(Value) AS avg, min(Value) AS min, max(Value) AS max
        FROM otel_metrics_gauge
        WHERE MetricName = {name:String}
          AND TimeUnix >= now() - toIntervalMinute({since:UInt32})
          AND ({service:String} = '' OR ServiceName = {service:String})
        GROUP BY bucket, service ORDER BY bucket, service LIMIT 10000
        """,
        {"name": name, "since": since_minutes, "step": step_seconds, "service": service or ""},
    )


app.include_router(api)


_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'; "
                               "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


mimetypes.add_type("font/woff2", ".woff2")

# The UI shell is public and holds no data; everything it shows comes from /api behind the guard.
app.mount("/", StaticFiles(directory=FsPath(__file__).parent / "static", html=True), name="ui")
