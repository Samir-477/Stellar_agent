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


def updated(parsed, match, update) -> object | None:
    """A copy of a JSON-LD block in which `update(node)` changed the first node `match(node)` accepts, or None
    when no node matches or the update changed nothing. The original block is left as it is."""
    import json

    copy = json.loads(json.dumps(parsed))
    for node in nodes(copy):
        if match(node):
            return copy if update(node) else None
    return None


def script_tag(parsed) -> str:
    """A JSON-LD block as the <script> element a page carries."""
    import json

    body = json.dumps(parsed, ensure_ascii=False, indent=2).replace("</", "<\/")
    return f'<script type="application/ld+json">\n{body}\n</script>'


def merge3(base, a, b):
    """Combine two edits (a, b) of the same JSON-LD value (base): each side's changes are kept. Where both
    changed the same field, lists are united (a's items first) and otherwise a wins."""
    if a == base:
        return b
    if b == base or a == b:
        return a
    if isinstance(base, dict) and isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for key in dict.fromkeys([*a, *b]):
            if key in a and key in b:
                out[key] = merge3(base.get(key), a[key], b[key])
            elif key in a:
                if not (key in base and a[key] == base[key]):  # b removed it; keep only if a changed it
                    out[key] = a[key]
            elif not (key in base and b[key] == base[key]):
                out[key] = b[key]
        return out
    if isinstance(a, list) and isinstance(b, list):
        if isinstance(base, list) and len(a) == len(b) == len(base):
            return [merge3(x, y, z) for x, y, z in zip(base, a, b)]
        return a + [item for item in b if item not in a]
    return a
