"""
Day 23 – Disk cache for LLM calls.

Avoids redundant API calls by persisting model responses to disk.
The cache key is a SHA-256 hash of the full request: model, messages,
temperature, and max_tokens. Each entry is stored as an individual JSON
file under cache/llm/ so entries can be inspected and deleted individually.

Usage
-----
from production.cache import get_cached, set_cached, cache_stats, clear_cache

# In _llm():
cached = get_cached(model, messages, temperature=0, max_tokens=1024)
if cached is not None:
    return cached
response = call_api(...)
set_cached(model, messages, temperature=0, max_tokens=1024, response=response)

# Inspect the cache:
stats = cache_stats()   # {"entries": 42, "size_kb": 310}
clear_cache()           # wipe all entries
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "llm"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_key(model: str, messages: list[dict], temperature: float, max_tokens: int) -> str:
    """
    Derive a stable SHA-256 hex key from the request parameters.
    """
    payload = json.dumps(
        {
            "model":       model,
            "messages":    messages,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _entry_path(key: str) -> Path:
    """
    Return the file path for a cache key.
    """
    return CACHE_DIR / f"{key}.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_cached(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
) -> str | None:
    """
    Return the cached response string for this request, or None on a miss.
    """
    key = _make_key(model, messages, temperature, max_tokens)
    path = _entry_path(key)
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text())
    return data["response"]


def set_cached(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    response: str,
) -> None:
    """
    Persist a model response to disk under its cache key.

    Stores the full request alongside the response so entries are
    self-documenting and can be inspected without the original code.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _make_key(model, messages, temperature, max_tokens)
    entry: dict[str, Any] = {
        "key":         key,
        "ts":          datetime.now(timezone.utc).isoformat(),
        "model":       model,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "messages":    messages,
        "response":    response,
    }
    _entry_path(key).write_text(json.dumps(entry, indent=2))


def cache_stats() -> dict[str, Any]:
    """
    Return a summary of the current cache state:
      - entries   : number of cached responses
      - size_kb   : total size of all cache files in kilobytes
      - cache_dir : absolute path to the cache directory
    """
    if not CACHE_DIR.exists():
        return {"entries": 0, "size_kb": 0.0, "cache_dir": str(CACHE_DIR)}
    files = list(CACHE_DIR.glob("*.json"))
    size_kb = round(sum(f.stat().st_size for f in files) / 1024, 1)
    return {
        "entries":   len(files),
        "size_kb":   size_kb,
        "cache_dir": str(CACHE_DIR),
    }


def clear_cache() -> int:
    """
    Delete all cache entries.
    Returns the number of files removed.
    """
    if not CACHE_DIR.exists():
        return 0
    files = list(CACHE_DIR.glob("*.json"))
    for f in files:
        f.unlink()
    return len(files)
