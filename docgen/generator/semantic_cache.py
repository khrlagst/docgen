"""Opt-in semantic cache for documentation generation (improvement #4).

The exact-hash cache (``ResponseCache``) is the default and cheapest layer.
This semantic layer is *off by default* and only engages when explicitly
enabled in config (``generation.semantic_cache = true``). It stores a small
offline bag-of-words embedding for each prompt and, on a cache miss, returns
a previously cached response when an incoming prompt is sufficiently similar
(cosine >= threshold). This recovers responses across trivial edits
(whitespace, word reordering) without a heavy embedding model or network.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def _tokenize(text: str) -> list[str]:
    # Alphanumeric word tokens (punctuation/whitespace stripped) so near-duplicate
    # prompts that only differ in spacing or symbol placement still match.
    words = re.findall(r"[a-z0-9]+", text.lower())
    bigrams = [f"{a} {b}" for a, b in zip(words, words[1:])]
    return words + bigrams


def _embed(text: str) -> dict[str, float]:
    grams = _tokenize(text)
    counts = Counter(grams)
    norm = sum(v * v for v in counts.values()) ** 0.5 or 1.0
    return {g: c / norm for g, c in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    return sum(a[g] * b[g] for g in a.keys() & b.keys())


class SemanticCache:
    def __init__(
        self,
        store_path: Path,
        threshold: float = 0.85,
        enabled: bool = True,
    ):
        self.store_path = Path(store_path)
        self.threshold = threshold
        self.enabled = enabled
        self._entries: list[dict[str, Any]] = []
        if self.enabled:
            self._load()

    def _load(self) -> None:
        if not self.store_path.exists():
            return
        for line in self.store_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self._entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _append(self, obj: dict[str, Any]) -> None:
        self._entries.append(obj)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with self.store_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj) + "\n")

    def get(self, prompt: str) -> str | None:
        if not self.enabled:
            return None
        emb = _embed(prompt)
        best: dict[str, Any] | None = None
        best_score = 0.0
        for entry in self._entries:
            score = _cosine(emb, entry["embed"])
            if score > best_score:
                best_score = score
                best = entry
        if best is not None and best_score >= self.threshold:
            return best["response"]
        return None

    def set(self, prompt: str, response: str) -> None:
        if not self.enabled:
            return
        self._append({"embed": _embed(prompt), "response": response})
