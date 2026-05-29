# Lecturn Production Maturity

Week 4 added the production layer: structured observability, LLM call caching, input/output guardrails, and a Streamlit UI. This writeup covers what was built, why each piece exists, and what's still missing for a real deployment.

---

## 1. Structured Observability (`production/observability.py`)

### What it does

Every agent run now emits two parallel streams:

- **Local JSONL** (`logs/lecturn.jsonl`) — always-on, no external dependencies. One JSON object per line, each with `ts`, `run_id`, `event`, and event-specific fields. Survives Langfuse outages, works offline, machine-readable for post-hoc analysis.
- **Langfuse** (cloud.langfuse.com) — when `LANGFUSE_SECRET_KEY` is set, every LLM call appears as a generation in the Langfuse UI with input, output, latency, and token counts. The entire agent run is grouped under one trace via `@observe`.

### What a run looks like

```json
{"ts": "2026-05-29T05:16:44.344909+00:00", "run_id": "1c78ab57", "event": "run.start", "query": "structured notes on contextual retrieval"}
{"ts": "...", "run_id": "1c78ab57", "event": "parse_query.end",        "duration_s": 1.263, "mode": "structured-notes"}
{"ts": "...", "run_id": "1c78ab57", "event": "plan_sections.end",       "duration_s": 0.93,  "sections": 4}
{"ts": "...", "run_id": "1c78ab57", "event": "retrieve.end",            "duration_s": 0.328, "chunks": 10, "unique_sources": 1}
{"ts": "...", "run_id": "1c78ab57", "event": "draft.end",               "duration_s": 2.137, "draft_chars": 1610}
{"ts": "...", "run_id": "1c78ab57", "event": "verify_citations.end",    "duration_s": 9.28,  "claims_checked": 9, "low_confidence": 0}
{"ts": "...", "run_id": "1c78ab57", "event": "format_output.end",       "duration_s": 0.0,   "citations_valid": true, "invalid_citations": 0}
{"ts": "...", "run_id": "1c78ab57", "event": "run.end",                 "output_chars": 1654}
```

### What the numbers reveal

From a single real run on `"structured notes on contextual retrieval"`:

| Node | Duration |
|---|---|
| `parse_query` | 1.3s |
| `plan_sections` | 0.9s |
| `retrieve` | 0.3s |
| `draft` | 2.1s |
| `verify_citations` | **9.3s** |
| `format_output` | <0.01s |

`verify_citations` dominates — 9 cited claims × ~1s per LLM faithfulness call. This is the obvious optimization target. Batching the faithfulness calls or switching to a lighter judge model would cut it to ~2s.

### Why two outputs instead of one

Langfuse gives you a great UI for debugging individual LLM calls (what went in, what came out, how long it took). The JSONL gives you structured data you can query with `jq` or load into a dataframe. They serve different use cases. Neither alone is sufficient: Langfuse is useless offline or if you want to aggregate across 1,000 runs; raw logs are useless for interactively browsing a single trace.

---

## 2. LLM Call Cache (`production/cache.py`)

### What it does

Before every LLM call, `_llm()` in `nodes.py` checks `cache/llm/` for a matching entry. The cache key is a SHA-256 hash of the full request: model, messages, temperature, and max_tokens. On a hit, the cached string is returned immediately — no API call, no latency, no cost. On a miss, the response is persisted after the call.

Each cache entry is a self-documenting JSON file:

```json
{
  "key": "a3f4...",
  "ts": "2026-05-29T05:16:45Z",
  "model": "gemini-2.5-flash-lite",
  "temperature": 0,
  "max_tokens": 256,
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "Query: ..."}],
  "response": "..."
}
```

### Why this matters for eval

The eval harness (`run_evals.py`) runs the same or similar prompts many times across 17 golden examples and two pipelines. Without caching, that's 500+ LLM calls per eval run. With caching, the second run is nearly instant. This makes the eval harness cheap enough to run on every iteration — which means you actually run it.

The cache also makes debugging faster. If a node produces a bad output, you can inspect the cached entry to see exactly what the model was given and what it returned, without having to re-run the full graph.

### Tradeoffs

**Stale cache is a real risk.** If the system prompt in `prompts.py` changes, the cached responses are stale but the cache key won't change (the key hashes the message content, not the file). The fix: either include a `cache_version` in the key, or run `clear_cache()` after prompt changes.

**`temperature=0` is required.** At any temperature > 0, the same request can produce different valid responses. Caching non-deterministic calls would serve stale outputs. The cache is only safe because all Lecturn nodes use `temperature=0`.

**Not appropriate for production user traffic.** Two users asking slightly different questions get different cache keys even if the underlying retrieval and answer would be identical. The cache is a development-time and eval-time tool, not a latency optimization for production.

---

## 3. Guardrails (`production/guardrails.py`)

Two independent checks, no LLM required.

### Prompt injection guard

Runs before the graph. Eight regex patterns covering the most common injection vectors:

| Pattern category | Example trigger |
|---|---|
| Instruction override | "ignore previous instructions" |
| Context wipe | "forget everything you know" |
| Role switch | "you are now a pirate" |
| Prompt extraction | "print your system prompt" |
| Template injection | `{{malicious}}` |
| Script injection | `<script>` |

Queries over 1,000 characters are also rejected — legitimate research questions rarely exceed this, and very long inputs are a common vector for embedding hidden instructions.

If the check fails, the run is blocked before a single token is spent. The reason is logged.

### Citation validator

Runs inside `format_output`. Extracts every `[source: X]` citation from the draft and checks the cited name against the retrieved chunk titles. Match logic: a citation is valid if the cited name is a substring of any retrieved title, or any retrieved title is a substring of the cited name (after normalization). This handles the common case where the model abbreviates a long title.

Invalid citations — ones that don't match any retrieved source — are flagged in the final output with a warning block and logged as `format_output.invalid_citations`.

This catches the `hallucinated_citation_scope` failure mode from the failure taxonomy: the source exists in the corpus, but the specific claim being made is fabricated. The citation validator catches the case where the cited title itself doesn't match anything retrieved — a coarser but cheaper check that requires no LLM.

### What the guardrails don't catch

The injection guard uses static patterns. It will miss novel injection attempts that don't match the current patterns. A more robust approach would pass the query through an LLM safety classifier — but that adds latency and cost for every request, including the 99.9% of benign ones. Static patterns are the right tradeoff at this scale.

The citation validator catches title mismatches, not semantic hallucinations. A model can cite a real source and still fabricate the specific statistic it attributes to that source. That's what `verify_citations` (the LLM-as-judge faithfulness loop) is for. The two checks are complementary: the validator checks the citation exists, the judge checks the claim is supported.

---

## 4. Streamlit UI (`app.py`)

A single-file UI that exposes the full agent pipeline:

- **Query input** with optional mode override (`Auto` / `structured-notes` / `comparison` / `lit-review`)
- **Injection guard** fires before the graph — blocked queries show an error and stop
- **Run status** spinner while the graph executes
- **Final markdown output** rendered in the main panel
- **Sidebar** with cache stats, Langfuse status, run_id, mode, revision count, chunks retrieved, unique sources, planned sections
- **Low-confidence claims** in a collapsible expander with per-claim scores and reasoning

The UI is intentionally thin — it calls the same `lecturn_graph.invoke()` path that the CLI uses, with no agent logic duplicated. All the production machinery (observability, cache, guardrails, Langfuse tracing) fires exactly as it would from the command line.

---

## 5. What's Missing for True Production

### Async execution

LangGraph's `graph.invoke()` is synchronous. Streamlit blocks the entire UI thread while the graph runs. For a multi-user deployment, a single slow query (the 9-second `verify_citations` call) would block all other users. The fix is `graph.ainvoke()` with async Streamlit or a job queue pattern (submit query → poll for result).

### User session isolation

The current `run_id` is a module-level global in `observability.py`. Two concurrent Streamlit sessions would write to the same `_run_id`, producing a corrupt JSONL log. For multi-user deployment, `run_id` needs to live in Streamlit's session state.

### Cache invalidation strategy

No mechanism exists to invalidate cache entries when prompts change. For now: `clear_cache()` is a one-liner. For production, a versioned cache key or a TTL would be better.

### Auth and rate limiting

The UI has no authentication. Anyone with the URL can run queries that make API calls and spend tokens. For a public deployment, rate limiting per session and API key rotation are necessary.

### Eval regression testing in CI

The eval harness exists and produces good signal, but it isn't wired into any CI pipeline. A prompt change or retrieval tweak could regress faithfulness or completeness without anyone noticing. The right setup: run `run_evals.py --pipeline both` on every PR and fail the check if MRR or faithfulness drops below a threshold.
