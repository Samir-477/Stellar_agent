"""URL helpers shared by collectors, agents and libraries."""

from __future__ import annotations

from urllib.parse import urlsplit


def norm(url: str) -> str:
    """host + path, lowercase host, no scheme, query, fragment or trailing slash (for comparing URLs)."""
    parts = urlsplit(url)
    return f"{(parts.hostname or '').lower()}{parts.path or '/'}".rstrip("/")


def site_label(domain: str) -> str:
    """The name part of a domain: "tripadvisor" for in.tripadvisor.com, tripadvisor.in and tripadvisor.co.in."""
    parts = domain.lower().removeprefix("www.").split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "net", "gov", "ac", "edu"):
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]
