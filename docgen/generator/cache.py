from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_CACHE_PATH = Path("~/.config/docgen/cache/generate.json").expanduser()


def _stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ResponseCache:
    """Prompt-hash keyed cache for LLM responses.

    The cache key is derived from the provider/model prefix plus the full
    system + user prompt. Because the prompt embeds the project source, an
    unchanged codebase produces identical hashes and is served from disk with
    no provider call -- saving tokens on re-runs. Editing source changes the
    prompt hash, so only the affected units are regenerated.
    """

    def __init__(self, path: Path = DEFAULT_CACHE_PATH, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        self._store: dict[str, str] = {}
        self.hits = 0
        self.misses = 0
        if self.enabled:
            self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._store = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._store = {}

    def _save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._store), encoding="utf-8")

    def key_for(self, prefix: str, system_prompt: str, user_prompt: str) -> str:
        payload = f"{prefix}\n{system_prompt}\n{user_prompt}"
        return _stable_hash(payload)

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        value = self._store.get(key)
        if value is not None:
            self.hits += 1
        else:
            self.misses += 1
        return value

    def set(self, key: str, value: str) -> None:
        if not self.enabled:
            return
        self._store[key] = value
        self._save()

    def clear(self) -> None:
        self._store = {}
        if self.path.exists():
            self.path.unlink()
