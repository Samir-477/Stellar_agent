"""Execution contexts handed to collectors and agents.

Collectors get a SnapshotWriter; agents get only a SnapshotReader. Neither
context exposes other agents' findings, which enforces agent independence.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from engine.core.config import Settings
from engine.integrations.pagespeed import PageSpeedClient
from engine.integrations.search import SearchClient
from engine.llm import LLMClient
from engine.store import SnapshotReader, SnapshotWriter


@dataclass
class ClientProfile:
    id: str
    name: str
    primary_url: str
    archetype: str | None = None
    locations: list[str] = field(default_factory=list)
    competitors: list[str] = field(default_factory=list)
    crawl_cap: int = 25


@dataclass
class WorkUnit:
    """One short, retryable piece of work (docs/spec/03: tasks target ≤120 s)."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectorContext:
    snapshot: SnapshotWriter
    client: ClientProfile
    settings: Settings
    llm: LLMClient | None = None
    http_transport: httpx.AsyncBaseTransport | None = None  # injected in tests
    resolver: Callable = socket.getaddrinfo  # injected in tests
    search: SearchClient | None = None
    pagespeed: PageSpeedClient | None = None

    def http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.http_transport, timeout=self.settings.crawl_timeout_s)


@dataclass
class AgentContext:
    snapshot: SnapshotReader
    client: ClientProfile
    settings: Settings
    llm: LLMClient | None = None
