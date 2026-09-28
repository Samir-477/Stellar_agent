"""Shared test fixtures. Tests never touch the network, the database or a live LLM."""

from __future__ import annotations

import socket
from pathlib import Path

import httpx
import pytest

from engine.core.config import Settings

PUBLIC_IP = "93.184.216.34"


def fake_resolver(host, port, *args, **kwargs):
    """Every hostname resolves to one public IP, except names that say otherwise."""
    ip = {"internal.test": "10.0.0.5", "metadata.test": "169.254.169.254"}.get(host, PUBLIC_IP)
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, llm_mode="replay", llm_fixture_dir=tmp_path / "llm",
                    blob_store="local", local_blob_dir=tmp_path / "blobs",
                    deepseek_api_key="test-deepseek", groq_api_key="test-groq")


def site_transport(routes: dict[str, tuple[int, dict, str | bytes]]) -> httpx.MockTransport:
    """routes: absolute URL → (status, headers, body). Unknown URLs return 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        status, headers, body = routes.get(url, (404, {"content-type": "text/html"}, "<h1>Not found</h1>"))
        return httpx.Response(status, headers=headers, content=body.encode() if isinstance(body, str) else body)

    return httpx.MockTransport(handler)


class FakeLLM:
    """Scripted stand-in for LLMClient: responses keyed by prompt id (dict or callable(vars) -> dict)."""

    def __init__(self, responses: dict):
        self.responses, self.calls = responses, []

    def complete_json(self, prompt, schema, prefer=None, **variables):
        from engine.llm.client import LLMResult
        self.calls.append((prompt.id, variables))
        response = self.responses[prompt.id]
        data = response(variables) if callable(response) else response
        return LLMResult(schema.model_validate(data), "fake", "fake-model", prompt.ref, source="replay")

    def probe_text(self, provider, prompt, **variables):
        from engine.llm.client import LLMResult
        self.calls.append((f"{prompt.id}:{provider}", variables))
        response = self.responses[f"{prompt.id}:{provider}"]
        text = response(variables) if callable(response) else response
        return LLMResult(text, provider, f"{provider}-model", prompt.ref, source="replay")
