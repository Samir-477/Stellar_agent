"""Outbound URL safety (SSRF guard) and a safe fetch helper for the crawler.

A hosted crawler accepts arbitrary URLs, so every URL, including every redirect
hop, is checked before it's fetched: http/https only, no credentials in the URL,
and the host must not resolve to a private, loopback, link-local, multicast,
reserved or shared (CGNAT) address. Resolution happens right before each request;
a residual DNS-rebinding window between our check and httpx's own resolution
remains and is acceptable for this threat model.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

_SHARED_NET = ipaddress.ip_network("100.64.0.0/10")


class UnsafeURLError(ValueError):
    pass


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    if ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in _SHARED_NET:
        return False
    return True


def check_url(url: str, resolver=socket.getaddrinfo) -> str:
    """Return the URL if it is safe to fetch, otherwise raise UnsafeURLError."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme not allowed: {parts.scheme!r}")
    if not parts.hostname:
        raise UnsafeURLError("missing host")
    if parts.username or parts.password:
        raise UnsafeURLError("credentials in URL are not allowed")
    host = parts.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = resolver(host, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise UnsafeURLError(f"cannot resolve host {host!r}") from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses or not all(_ip_is_public(ip) for ip in addresses):
        raise UnsafeURLError(f"host {host!r} resolves to a non-public address")
    return url


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    redirects: list[dict] = field(default_factory=list)  # [{url, status, location}]
    elapsed_ms: int = 0
    error: str | None = None
    truncated: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    @property
    def text(self) -> str:
        return self.body.decode(_charset(self.content_type), errors="replace")


def _charset(content_type: str) -> str:
    for part in content_type.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip("\"'")
    return "utf-8"


async def safe_fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    user_agent: str,
    max_redirects: int = 5,
    max_bytes: int = 5_000_000,
    method: str = "GET",
    resolver=socket.getaddrinfo,
) -> FetchResult:
    """Fetch a URL, following redirects manually so each hop passes the SSRF guard."""
    started = time.perf_counter()
    redirects: list[dict] = []
    current = url
    for _ in range(max_redirects + 1):
        try:
            check_url(current, resolver)
        except UnsafeURLError as exc:
            return FetchResult(url, current, None, redirects=redirects, error=f"blocked: {exc}",
                               elapsed_ms=_ms(started))
        try:
            async with client.stream(method, current, headers={"User-Agent": user_agent},
                                     follow_redirects=False) as resp:
                if resp.is_redirect and "location" in resp.headers:
                    location = urljoin(current, resp.headers["location"])
                    redirects.append({"url": current, "status": resp.status_code, "location": location})
                    current = location
                    continue
                body, truncated = bytearray(), False
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        truncated = True
                        break
                return FetchResult(url, current, resp.status_code,
                                   {k.lower(): v for k, v in resp.headers.items()},
                                   bytes(body[:max_bytes]), redirects, _ms(started), None, truncated)
        except httpx.HTTPError as exc:
            return FetchResult(url, current, None, redirects=redirects,
                               error=f"{type(exc).__name__}: {exc}", elapsed_ms=_ms(started))
    return FetchResult(url, current, None, redirects=redirects, error="too many redirects",
                       elapsed_ms=_ms(started))


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
