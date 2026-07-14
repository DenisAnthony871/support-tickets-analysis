"""
Knowledge base retrieval using TF-IDF for matching support tickets to KB docs.

Scans all Markdown files under starter-repo/knowledge-base/, builds a TF-IDF
index, and returns the best-matching document path for a given query.
"""

import math
import os
import re
from pathlib import Path
from typing import Optional


_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will "
    "would shall should may might must can could need dare to of in for on "
    "with at by from as into through during before after above below between "
    "out up down and but or nor not so yet both either neither each every all "
    "some any no this that these those it its i we you he she they me him her "
    "us them my our your his their what which who whom how where when why if "
    "than too very just also about more than most other such only own same "
    "again further then once here there once".split()
)


def _tokenise(text: str) -> list[str]:
    """Lowercase, strip non-alphanumeric, remove stop-words."""
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


class KBIndex:
    """Simple in-memory TF-IDF index over knowledge-base Markdown files."""

    def __init__(self, kb_root: str | Path):
        self.kb_root = Path(kb_root)
        self.docs: dict[str, list[str]] = {}
        self.idf: dict[str, float] = {}
        self._build()

    def _build(self) -> None:
        """Walk KB directory, read Markdown files, compute IDF."""
        for md_file in sorted(self.kb_root.rglob("*.md")):
            rel = md_file.relative_to(self.kb_root.parent).as_posix()
            text = md_file.read_text(encoding="utf-8", errors="replace")
            self.docs[rel] = _tokenise(text)

        n_docs = len(self.docs)
        if n_docs == 0:
            return

        df: dict[str, int] = {}
        for tokens in self.docs.values():
            for tok in set(tokens):
                df[tok] = df.get(tok, 0) + 1

        self.idf = {
            tok: math.log((n_docs + 1) / (freq + 1)) + 1
            for tok, freq in df.items()
        }

    def _tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        """Compute TF-IDF vector for a list of tokens."""
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        return {
            t: (1 + math.log(c)) * self.idf.get(t, 1.0)
            for t, c in tf.items()
        }

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        """Cosine similarity between two sparse vectors."""
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[k] * b[k] for k in common)
        mag_a = math.sqrt(sum(v * v for v in a.values()))
        mag_b = math.sqrt(sum(v * v for v in b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def search(
        self, query: str, *, top_k: int = 1, threshold: float = 0.05
    ) -> list[tuple[str, float]]:
        """
        Return up to *top_k* (path, score) tuples for the best-matching KB docs.

        Only docs with score >= *threshold* are returned.
        """
        q_vec = self._tfidf_vector(_tokenise(query))
        if not q_vec:
            return []

        scored = []
        for rel_path, tokens in self.docs.items():
            d_vec = self._tfidf_vector(tokens)
            score = self._cosine(q_vec, d_vec)
            if score >= threshold:
                scored.append((rel_path, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def best_match(self, query: str, *, threshold: float = 0.05) -> Optional[str]:
        """Return the path of the single best-matching KB doc, or None."""
        results = self.search(query, top_k=1, threshold=threshold)
        return results[0][0] if results else None
