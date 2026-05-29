# Production Module

Three independent modules that add production-readiness on top of the agent. None of these change agent behaviour — they wrap it.

## Modules

### `observability.py`
Structured logging for every agent run. Two outputs:
- **`logs/lecturn.jsonl`** — always-on JSONL log with `ts`, `run_id`, `event`, and per-node metrics (duration, chunk counts, draft length, etc.)
- **Langfuse** — when `LANGFUSE_SECRET_KEY` is set, every LLM call appears as a generation in the Langfuse UI, grouped under one trace per run

Key functions: `new_run(query)`, `end_run(output)`, `log_event(event, data)`, `timed_node(name)` (context manager).

### `cache.py`
Disk cache for LLM calls. Cache key = SHA-256 of (model + messages + temperature + max_tokens). Responses stored as individual JSON files under `cache/llm/`.

On a hit, the model is not called. On a miss, the response is written after the call. Makes the eval harness cheap to re-run — second run on the same queries is nearly instant.

Key functions: `get_cached(...)`, `set_cached(...)`, `cache_stats()`, `clear_cache()`.

### `guardrails.py`
Two checks, no LLM required:
- **`check_query(query)`** — scans for prompt injection patterns before the graph runs (instruction overrides, role switches, prompt extraction, template injection). Returns `{"safe": bool, "reason": str | None}`.
- **`validate_citations(draft, chunks)`** — checks that every `[source: X]` citation name matches a retrieved chunk title. Returns `{"pass": bool, "valid": [...], "invalid": [...]}`.

## Usage

```python
from production.observability import new_run, end_run, log_event, timed_node
from production.cache import get_cached, set_cached, cache_stats
from production.guardrails import check_query, validate_citations
```

All three are already wired into the agent: `nodes.py` uses observability and cache; `format_output` calls `validate_citations`; `run_agent.py` and `app.py` call `check_query` before invoking the graph.
