"""JSON-LD helpers shared by collectors and agents: typed nodes from the parser's JSON-LD blocks."""

from __future__ import annotations


def types_of(node: dict) -> set[str]:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t} if isinstance(t, str) else set()


def nodes(parsed) -> list[dict]:
    """Flatten @graph and nested objects into a list of typed nodes."""
    out: list[dict] = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if types_of(node):
                out.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    walk(parsed)
    return out


def page_nodes(model: dict) -> list[dict]:
    """Every typed node in a parsed page's JSON-LD blocks."""
    return [n for block in model.get("jsonld", []) for n in nodes(block.get("parsed"))]


def page_types(model: dict) -> set[str]:
    return {t for n in page_nodes(model) for t in types_of(n)}
