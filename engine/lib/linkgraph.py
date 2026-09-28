"""Internal link graph over the sampled pages (shared by S7 and, later, A3 journey paths).

Nodes are sampled HTML pages keyed by normalised final URL. A link to a sampled page's
original URL that redirected is resolved to its final page and flagged `via_redirect`.
Links to pages outside the sample are counted but not followed: every result is about the
sample, not the whole site.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.lib.urls import norm

if TYPE_CHECKING:  # type hints only: lib must not depend on the agent layer at runtime
    from engine.agents.common import PageView


@dataclass
class Edge:
    source: str
    target: str
    text: str
    placement: str  # nav | footer | body
    via_redirect: bool
    link: dict


@dataclass
class LinkGraph:
    nodes: dict[str, "PageView"]
    edges: list[Edge] = field(default_factory=list)
    outside_sample: int = 0

    @classmethod
    def build(cls, html_pages: list["PageView"], all_pages: list["PageView"]) -> "LinkGraph":
        nodes = {norm(p.url): p for p in html_pages}
        alias, redirected = {}, set()
        for p in all_pages:
            original, final = norm(p.record.url), norm(p.url)
            if original != final:
                alias[original] = final
                if p.record.fetch.get("redirects"):
                    redirected.add(original)
        graph = cls(nodes)
        for page in html_pages:
            source = norm(page.url)
            for link in page.model.get("links", []):
                if not link.get("internal"):
                    continue
                raw = norm(link["href"])
                target = alias.get(raw, raw)
                if target == source:
                    continue
                if target not in nodes:
                    graph.outside_sample += 1
                    continue
                placement = "nav" if link.get("in_nav") else "footer" if link.get("in_footer") else "body"
                graph.edges.append(Edge(source, target, link.get("text", ""), placement, raw in redirected, link))
        return graph

    def inbound(self, node: str, placement: str | None = None) -> list[Edge]:
        return [e for e in self.edges if e.target == node and (placement is None or e.placement == placement)]

    def outbound(self, node: str, placement: str | None = None) -> list[Edge]:
        return [e for e in self.edges if e.source == node and (placement is None or e.placement == placement)]

    def depths(self, start: str) -> dict[str, int]:
        """Clicks from `start` to every reachable sampled page (breadth-first)."""
        depth = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for edge in self.outbound(node):
                if edge.target not in depth:
                    depth[edge.target] = depth[node] + 1
                    queue.append(edge.target)
        return depth
