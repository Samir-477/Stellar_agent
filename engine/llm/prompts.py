"""Versioned prompt files.

Prompts are code: each lives in engine/llm/prompt_files/<id>.v<version>.md, is
reviewed like code, and every LLM call records the id + version it used.

File format:

    ---
    id: s3.title_relevance
    version: 1
    tier: fast            # fast | reasoning
    max_tokens: 600
    ---
    [system]
    ...fixed instructions: no dates, IDs or other per-call data, so provider
    prompt caching keeps working...
    [user]
    ...template with {placeholders}; untrusted page content goes inside
    <data>...</data> blocks and is treated as data, never instructions...
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_files"
_FRONT = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


@dataclass(frozen=True)
class PromptSpec:
    id: str
    version: int
    tier: Literal["fast", "reasoning"]
    max_tokens: int
    system: str
    user_template: str

    @property
    def ref(self) -> str:
        return f"{self.id}@v{self.version}"

    def render_user(self, **variables: str) -> str:
        safe = {k: _neutralize(v) for k, v in variables.items()}
        return self.user_template.format(**safe)


def _neutralize(value: object) -> str:
    """Stop untrusted text from closing our <data> delimiters."""
    return str(value).replace("</data>", "&lt;/data&gt;").replace("<data>", "&lt;data&gt;")


def parse_prompt(text: str) -> PromptSpec:
    match = _FRONT.match(text.replace("\r\n", "\n"))
    if not match:
        raise ValueError("prompt file needs a --- front matter block")
    meta = dict(line.split(":", 1) for line in match[1].splitlines() if ":" in line)
    meta = {k.strip(): v.split("#")[0].strip() for k, v in meta.items()}
    body = match[2]
    if "[system]" not in body or "[user]" not in body:
        raise ValueError("prompt file needs [system] and [user] sections")
    system, user = body.split("[user]", 1)
    return PromptSpec(
        id=meta["id"],
        version=int(meta["version"]),
        tier=meta.get("tier", "fast"),  # type: ignore[arg-type]
        max_tokens=int(meta.get("max_tokens", 800)),
        system=system.replace("[system]", "", 1).strip(),
        user_template=user.strip(),
    )


@lru_cache
def load_prompt(prompt_id: str, version: int) -> PromptSpec:
    path = PROMPT_DIR / f"{prompt_id}.v{version}.md"
    spec = parse_prompt(path.read_text(encoding="utf-8"))
    if (spec.id, spec.version) != (prompt_id, version):
        raise ValueError(f"{path.name}: front matter says {spec.ref}")
    return spec
