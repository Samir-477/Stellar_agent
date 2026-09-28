"""Minimal robots.txt evaluation (RFC 9309): groups by user agent, longest match wins,
Allow beats Disallow on equal length, `*` and `$` wildcards supported.
Shared by S1 (search crawlers) and G1 (AI crawlers).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class RobotsGroup:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[str, str, int]] = field(default_factory=list)  # (allow|disallow, pattern, line no)


@dataclass
class RobotsFile:
    groups: list[RobotsGroup]
    sitemaps: list[str]

    def group_for(self, user_agent: str) -> RobotsGroup | None:
        ua = user_agent.lower()
        best, best_len = None, -1
        for group in self.groups:
            for agent in group.agents:
                if agent != "*" and agent in ua and len(agent) > best_len:
                    best, best_len = group, len(agent)
        if best is None:
            best = next((g for g in self.groups if "*" in g.agents), None)
        return best

    def matching_rule(self, user_agent: str, url: str) -> tuple[str, str, int] | None:
        """The rule that decides access for this agent and URL, or None (allowed by default)."""
        group = self.group_for(user_agent)
        if group is None:
            return None
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        winner = None
        for kind, pattern, line in group.rules:
            if pattern and _matches(pattern, path):
                if winner is None or len(pattern) > len(winner[1]) or (
                        len(pattern) == len(winner[1]) and kind == "allow"):
                    winner = (kind, pattern, line)
        return winner

    def is_allowed(self, user_agent: str, url: str) -> bool:
        rule = self.matching_rule(user_agent, url)
        return rule is None or rule[0] == "allow"


def _matches(pattern: str, path: str) -> bool:
    regex = re.escape(pattern).replace(r"\*", ".*")
    if regex.endswith(r"\$"):
        regex = regex[:-2] + "$"
    return re.match(regex, path) is not None


def parse_robots(text: str) -> RobotsFile:
    groups: list[RobotsGroup] = []
    sitemaps: list[str] = []
    current: RobotsGroup | None = None
    last_was_agent = False
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = RobotsGroup()
                groups.append(current)
            current.agents.append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if key == "sitemap":
            sitemaps.append(value)
        elif key in ("allow", "disallow") and current is not None:
            if key == "disallow" and value == "":
                continue  # empty Disallow = allow everything
            current.rules.append((key, value, number))
    return RobotsFile(groups, sitemaps)
