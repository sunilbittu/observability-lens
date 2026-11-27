"""Outbound webhook delivery with egress controls. Status: prototype.

A destination is used only if its host is on the allowlist and every address it resolves
to is public. Hosts on a second, explicit list may resolve to private addresses (for a
receiver on the same private network). Loopback, link-local (which covers cloud metadata
at 169.254.169.254), multicast and reserved ranges are refused for every host.

The request connects to the address that was checked, so a second DNS answer cannot
redirect it. Redirects are not followed. Standard library only.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urlsplit

TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 4096


class Blocked(Exception):
    """The destination is not allowed. The message says why and is safe to store."""


@dataclass(frozen=True)
class Destination:
    host: str
    ip: str
    port: int
    tls: bool
    path: str


def _refusal(ip: ipaddress._BaseAddress, private_ok: bool) -> str | None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return "reserved address"
    if ip.is_global:
        return None
    if ip.is_private and private_ok:
        return None
    return "private address"


def check(url: str, allowed_hosts: frozenset[str], private_hosts: frozenset[str],
          resolve=socket.getaddrinfo) -> Destination:
    """Returns where to connect, or raises Blocked."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise Blocked("malformed url") from exc
    if parts.scheme not in ("http", "https"):
        raise Blocked("scheme is not http or https")
    if parts.username or parts.password:
        raise Blocked("url carries credentials")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise Blocked("url has no host")
    if host not in allowed_hosts:
        raise Blocked("host is not on the allowlist")
    tls = parts.scheme == "https"
    port = port or (443 if tls else 80)
    try:
        infos = resolve(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise Blocked("host does not resolve") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise Blocked("host does not resolve")
    for text in addresses:
        reason = _refusal(ipaddress.ip_address(text.split("%")[0]), host in private_hosts)
        if reason:
            raise Blocked(f"resolves to a {reason}")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return Destination(host=host, ip=addresses[0], port=port, tls=tls, path=path)


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Connects to a fixed address while verifying the certificate for the host name."""

    def __init__(self, ip: str, port: int, hostname: str, timeout: float):
        super().__init__(ip, port, timeout=timeout, context=ssl.create_default_context())
        self._hostname = hostname

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._hostname)


def send(destination: Destination, payload: dict) -> tuple[str, str]:
    """POSTs the payload once. Returns (outcome, detail): outcome is 'delivered' or 'failed'."""
    body = json.dumps(payload).encode()
    if destination.tls:
        conn = _PinnedHTTPS(destination.ip, destination.port, destination.host, TIMEOUT_SECONDS)
    else:
        conn = http.client.HTTPConnection(destination.ip, destination.port, timeout=TIMEOUT_SECONDS)
    default_port = 443 if destination.tls else 80
    host_header = destination.host if destination.port == default_port else f"{destination.host}:{destination.port}"
    try:
        conn.request("POST", destination.path, body=body, headers={
            "Host": host_header, "Content-Type": "application/json", "User-Agent": "tracemelt-alerts"})
        response = conn.getresponse()
        response.read(MAX_RESPONSE_BYTES)
        if 200 <= response.status < 300:
            return "delivered", f"http {response.status}"
        if 300 <= response.status < 400:
            return "failed", f"http {response.status}, redirects are not followed"
        return "failed", f"http {response.status}"
    except (OSError, http.client.HTTPException) as exc:
        return "failed", type(exc).__name__
    finally:
        conn.close()
