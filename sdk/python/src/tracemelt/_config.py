"""Resolves settings from arguments, then TRACEMELT_* variables, then the standard OTEL_* ones.

Returns a Config with enabled=False and a reason, instead of raising, when telemetry cannot be set up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_TRUE = {"1", "true", "yes", "on"}


def _flag(value) -> bool:
    return str(value or "").strip().lower() in _TRUE


@dataclass(frozen=True)
class Config:
    enabled: bool
    service_name: str
    reason: str = ""
    endpoint: str = ""
    headers: dict = field(default_factory=dict)
    capture_logging: bool = False
    debug: bool = False


def resolve(endpoint=None, token=None, service_name=None, capture_logging=None, debug=None,
            disabled=False, env=None) -> Config:
    env = os.environ if env is None else env
    base = dict(
        service_name=service_name or env.get("TRACEMELT_SERVICE_NAME") or env.get("OTEL_SERVICE_NAME") or "unknown_service",
        capture_logging=_flag(env.get("TRACEMELT_CAPTURE_LOGGING")) if capture_logging is None else capture_logging is True,
        debug=_flag(env.get("TRACEMELT_DEBUG")) if debug is None else debug is True,
    )
    if disabled is True or _flag(env.get("TRACEMELT_DISABLED")) or _flag(env.get("OTEL_SDK_DISABLED")):
        return Config(enabled=False, reason="disabled by configuration", **base)
    raw = endpoint or env.get("TRACEMELT_ENDPOINT") or env.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not raw:
        return Config(enabled=False, reason="no endpoint set (TRACEMELT_ENDPOINT)", **base)
    try:
        parts = urlsplit(str(raw))
        host = parts.hostname
        parts.port  # raises ValueError on a bad port
    except ValueError:
        return Config(enabled=False, reason="endpoint is not a valid URL", **base)
    if parts.scheme not in ("http", "https"):
        return Config(enabled=False, reason="endpoint must start with http:// or https://", **base)
    if not host:
        return Config(enabled=False, reason="endpoint is not a valid URL", **base)
    clean = f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")
    secret = token or env.get("TRACEMELT_INGEST_TOKEN")
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    return Config(enabled=True, endpoint=clean, headers=headers, **base)
