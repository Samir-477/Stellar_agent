"""LLM client: DeepSeek primary, Groq fallback, structured JSON output.

Modes (settings.llm_mode):
  off     no calls; raises LLMUnavailable so callers mark LLM checks `unverifiable`
  replay  answers come from recorded fixtures (tests and development); no network
  live    real provider calls, with cache, budget, fallback and circuit breaker

Every call is keyed by (prompt id, version, tier, rendered user message), which
is also the cache key and the replay-fixture name.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from engine.core.config import Settings
from engine.llm.prompts import PromptSpec

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """LLM calls are switched off (llm_mode=off) or no provider is configured."""


class LLMReplayMissing(LLMError):
    """llm_mode=replay and no fixture exists for this exact call."""


class BudgetExceeded(LLMError):
    pass


class ProviderError(LLMError):
    def __init__(self, provider: str, reason: str, retryable: bool):
        super().__init__(f"{provider}: {reason}")
        self.provider, self.retryable = provider, retryable


@dataclass
class TokenBudget:
    limit: int
    used: int = 0

    def charge(self, tokens: int) -> None:
        self.used += tokens
        if self.used > self.limit:
            raise BudgetExceeded(f"token budget exhausted ({self.used}/{self.limit})")

    def ensure_available(self) -> None:
        if self.used >= self.limit:
            raise BudgetExceeded(f"token budget exhausted ({self.used}/{self.limit})")


@dataclass
class LLMResult(Generic[T]):
    data: T
    provider: str
    model: str
    prompt_ref: str
    tokens_in: int = 0
    tokens_out: int = 0
    fallback_used: bool = False
    source: str = "live"  # live | cache | replay


@dataclass
class _Breaker:
    """Opens after `threshold` failures within `window_s`; stays open for `cooldown_s`."""

    threshold: int = 5
    window_s: float = 120.0
    cooldown_s: float = 300.0
    failures: deque = field(default_factory=deque)
    open_until: float = 0.0

    def is_open(self, now: float) -> bool:
        return now < self.open_until

    def record_failure(self, now: float) -> None:
        self.failures.append(now)
        while self.failures and now - self.failures[0] > self.window_s:
            self.failures.popleft()
        if len(self.failures) >= self.threshold:
            self.open_until = now + self.cooldown_s
            self.failures.clear()

    def record_success(self) -> None:
        self.failures.clear()


class OpenAICompatProvider:
    """DeepSeek and Groq both speak the OpenAI chat-completions API."""

    def __init__(self, name: str, base_url: str, api_key: str, models: dict[str, str],
                 client: httpx.Client, timeout_s: float, extra: dict[str, dict] | None = None):
        self.name, self.base_url, self.api_key = name, base_url.rstrip("/"), api_key
        self.models, self.client, self.timeout_s = models, client, timeout_s
        self.extra = extra or {}  # per-tier provider-specific parameters

    def chat(self, messages: list[dict], tier: str, max_tokens: int, _retried: bool = False, *,
             json_mode: bool = True, temperature: float = 0.1) -> tuple[str, str, int, int]:
        model = self.models[tier]
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                **self.extra.get(tier, {})}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=self.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(self.name, f"timeout: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"network: {exc}", retryable=True) from exc
        if resp.status_code == 429 and not _retried:
            wait = _retry_after_seconds(resp)
            if wait is not None and wait <= 30:
                time.sleep(wait)
                return self.chat(messages, tier, max_tokens, _retried=True, json_mode=json_mode,
                                 temperature=temperature)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(self.name, f"HTTP {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:200]}", retryable=False)
        body = resp.json()
        usage = body.get("usage") or {}
        choice = body["choices"][0]
        content = choice["message"].get("content") or ""
        if not content.strip() and choice.get("finish_reason") == "length":
            # Reasoning models can spend the whole budget thinking; a repair call would fail the same way.
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            raise ProviderError(self.name, f"output budget ({max_tokens}) used up before an answer "
                                           f"(reasoning tokens: {reasoning})", retryable=True)
        return content, body.get("model", model), int(usage.get("prompt_tokens", 0)), \
            int(usage.get("completion_tokens", 0))


CacheGet = Callable[[str], str | None]
CachePut = Callable[[str, str, str, str], None]  # key, provider, model, content
CallRecorder = Callable[[dict], None]


class LLMClient:
    _breakers: dict[str, _Breaker] = {}  # shared per process, like a real circuit breaker

    def __init__(self, settings: Settings, *, budget: TokenBudget | None = None,
                 http: httpx.Client | None = None, cache_get: CacheGet | None = None,
                 cache_put: CachePut | None = None, recorder: CallRecorder | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.settings, self.budget, self.clock = settings, budget, clock
        self.cache_get, self.cache_put, self.recorder = cache_get, cache_put, recorder
        http = http or httpx.Client()
        providers = {
            "deepseek": OpenAICompatProvider(
                "deepseek", settings.deepseek_base_url, settings.deepseek_api_key,
                {"reasoning": settings.deepseek_model, "fast": settings.deepseek_fast_model},
                http, settings.llm_timeout_s,
                # Fast-tier jobs (extraction, classification) don't need thinking; it only burns tokens.
                extra={"fast": {"thinking": {"type": "disabled"}}}),
            "groq": OpenAICompatProvider(
                "groq", settings.groq_base_url, settings.groq_api_key,
                {"reasoning": settings.groq_model, "fast": settings.groq_model},
                http, settings.llm_timeout_s,
                extra={"fast": {"reasoning_effort": "low"}, "reasoning": {"reasoning_effort": "medium"}}),
        }
        order = ["deepseek", "groq"] if settings.llm_primary == "deepseek" else ["groq", "deepseek"]
        self.chain = [providers[name] for name in order if providers[name].api_key]

    # ------------------------------------------------------------------ public

    def complete_json(self, prompt: PromptSpec, schema: type[T], *, prefer: str | None = None,
                      **variables: str) -> LLMResult[T]:
        """`prefer` puts one provider first for this call (e.g. a different model family as a second
        opinion); the others remain as fallback."""
        user = prompt.render_user(**variables)
        key = call_key(prompt, (f"{prefer}|" if prefer else "") + user)
        mode = self.settings.llm_mode
        if mode == "off":
            raise LLMUnavailable("LLM calls are off (LLM_MODE=off)")
        if mode == "replay":
            return self._replay(prompt, key, schema)
        return self._live(prompt, user, key, schema, prefer)

    def probe_text(self, provider: str, prompt: PromptSpec, **variables: str) -> LLMResult[str]:
        """Plain-text answer from ONE named provider, with no fallback: in GEO probes the provider is
        the surface being measured, so answering from another model would falsify the observation."""
        user = prompt.render_user(**variables)
        key = call_key(prompt, f"{provider}|{user}")
        mode = self.settings.llm_mode
        if mode == "off":
            raise LLMUnavailable("LLM calls are off (LLM_MODE=off)")
        if mode == "replay":
            path = self._fixture_path(prompt, key)
            if not path.exists():
                raise LLMReplayMissing(f"no fixture for {prompt.ref} ({provider}) at {path}")
            record = json.loads(path.read_text(encoding="utf-8"))
            return LLMResult(record["content"], record["provider"], record["model"], prompt.ref, source="replay")
        if self.cache_get and (cached := self.cache_get(key)):
            record = json.loads(cached)
            return LLMResult(record["content"], record["provider"], record["model"], prompt.ref, source="cache")
        target = next((p for p in self.chain if p.name == provider), None)
        if target is None:
            raise LLMUnavailable(f"provider {provider} has no API key")
        if self.budget:
            self.budget.ensure_available()
        messages = [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}]
        try:
            content, model, tin, tout = target.chat(messages, prompt.tier, prompt.max_tokens, json_mode=False,
                                                    temperature=0.3)
        except ProviderError as exc:
            self._record(prompt, key, provider, None, 0, 0, False, str(exc))
            raise LLMError(str(exc)) from exc
        if self.budget:
            self.budget.charge(tin + tout)
        if self.cache_put:
            self.cache_put(key, provider, model, json.dumps({"content": content, "provider": provider, "model": model}))
        if self.settings.llm_record:
            self._write_fixture(prompt, key, provider, model, content)
        self._record(prompt, key, provider, model, tin, tout, False, None)
        return LLMResult(content, provider, model, prompt.ref, tin, tout)

    # ----------------------------------------------------------------- replay

    def _fixture_path(self, prompt: PromptSpec, key: str) -> Path:
        return self.settings.llm_fixture_dir / prompt.id / f"v{prompt.version}" / f"{key}.json"

    def _replay(self, prompt: PromptSpec, key: str, schema: type[T]) -> LLMResult[T]:
        path = self._fixture_path(prompt, key)
        if not path.exists():
            raise LLMReplayMissing(f"no fixture for {prompt.ref} at {path}")
        record = json.loads(path.read_text(encoding="utf-8"))
        return LLMResult(schema.model_validate_json(record["content"]), record["provider"],
                         record["model"], prompt.ref, source="replay")

    # ------------------------------------------------------------------- live

    def _live(self, prompt: PromptSpec, user: str, key: str, schema: type[T],
              prefer: str | None = None) -> LLMResult[T]:
        if self.cache_get and (cached := self.cache_get(key)):
            record = json.loads(cached)
            return LLMResult(schema.model_validate_json(record["content"]), record["provider"],
                             record["model"], prompt.ref, source="cache")
        if not self.chain:
            raise LLMUnavailable("no LLM provider has an API key")
        if self.budget:
            self.budget.ensure_available()

        messages = [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}]
        errors: list[str] = []
        now = self.clock()
        chain = sorted(self.chain, key=lambda p: p.name != prefer) if prefer else self.chain
        for index, provider in enumerate(chain):
            breaker = self._breakers.setdefault(provider.name, _Breaker())
            is_last = index == len(chain) - 1
            if breaker.is_open(now) and not is_last:
                errors.append(f"{provider.name}: circuit open")
                continue
            try:
                data, model, tin, tout = self._call_with_repair(provider, messages, prompt, schema)
            except ProviderError as exc:
                breaker.record_failure(self.clock())
                errors.append(str(exc))
                self._record(prompt, key, provider.name, None, 0, 0, index > 0, str(exc))
                if exc.retryable or not is_last:
                    continue
                break
            breaker.record_success()
            if self.budget:
                self.budget.charge(tin + tout)
            content = data.model_dump_json()
            if self.cache_put:
                self.cache_put(key, provider.name, model, json.dumps({"content": content,
                                                                     "provider": provider.name,
                                                                     "model": model}))
            if self.settings.llm_record:
                self._write_fixture(prompt, key, provider.name, model, content)
            self._record(prompt, key, provider.name, model, tin, tout, index > 0, None)
            return LLMResult(data, provider.name, model, prompt.ref, tin, tout, index > 0)
        raise LLMError("all providers failed: " + "; ".join(errors))

    def _call_with_repair(self, provider: OpenAICompatProvider, messages: list[dict],
                          prompt: PromptSpec, schema: type[T]) -> tuple[T, str, int, int]:
        """One call, plus one repair attempt if the JSON doesn't match the schema."""
        content, model, tin, tout = provider.chat(messages, prompt.tier, prompt.max_tokens)
        try:
            return schema.model_validate_json(content), model, tin, tout
        except ValidationError as exc:
            repair = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "Your reply did not match the required JSON schema. "
                                            f"Errors: {exc.errors(include_url=False)[:5]}. "
                                            "Reply again with only the corrected JSON object."},
            ]
            content, model, tin2, tout2 = provider.chat(repair, prompt.tier, prompt.max_tokens)
            try:
                return schema.model_validate_json(content), model, tin + tin2, tout + tout2
            except ValidationError as exc2:
                raise ProviderError(provider.name, f"invalid JSON after repair: {exc2.error_count()} errors",
                                    retryable=True) from exc2

    def _write_fixture(self, prompt: PromptSpec, key: str, provider: str, model: str, content: str) -> None:
        path = self._fixture_path(prompt, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"prompt": prompt.ref, "provider": provider, "model": model,
                                    "content": content}, indent=2), encoding="utf-8")

    def _record(self, prompt: PromptSpec, key: str, provider: str, model: str | None, tin: int,
                tout: int, fallback: bool, error: str | None) -> None:
        if self.recorder:
            self.recorder({"prompt_ref": prompt.ref, "cache_key": key, "provider": provider, "model": model,
                           "tokens_in": tin, "tokens_out": tout, "fallback_used": fallback, "error": error})


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    try:
        return float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None


def call_key(prompt: PromptSpec, rendered_user: str) -> str:
    raw = f"{prompt.id}|{prompt.version}|{prompt.tier}|{rendered_user}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
