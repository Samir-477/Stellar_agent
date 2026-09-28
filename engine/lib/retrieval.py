"""Small lexical passage retrieval (BM25) used by agents to find the passages most likely to
answer a question. Deterministic, no embeddings, fits in a serverless function."""

from __future__ import annotations

import math
import re
from collections import Counter

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "from", "by", "is", "are",
         "be", "as", "it", "this", "that", "what", "how", "which", "who", "when", "where", "why", "can", "do",
         "does", "i", "you", "we", "my", "your", "there", "any", "near", "me", "best", "near"}


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1]


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.4, b: float = 0.75):
        self.docs = [tokens(d) for d in documents]
        self.k1, self.b = k1, b
        self.avg = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(set(doc))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def top(self, query: str, k: int = 3) -> list[tuple[int, float]]:
        q = tokens(query)
        scores = []
        for i, doc in enumerate(self.docs):
            tf = Counter(doc)
            score = sum(self.idf.get(t, 0) * tf[t] * (self.k1 + 1) /
                        (tf[t] + self.k1 * (1 - self.b + self.b * len(doc) / (self.avg or 1))) for t in q if t in tf)
            if score > 0:
                scores.append((i, score))
        return sorted(scores, key=lambda s: -s[1])[:k]
