# Lecturn — Codebase Reference

## What this project is

Lecturn is an agentic RAG system for academic research. Given a query, it retrieves relevant chunks from a curated corpus of AI/ML papers and blog posts, plans a structured response, drafts it, verifies citations, and self-corrects before delivering the final output.

Built over 4 weeks as a portfolio project. Weeks 1–3 are complete. Codebase refactored: LLM config centralised in `config.py`, all agent prompts in `agent/prompts.py`.

---

## Environment

```bash
cd /home/justine/Projects/lecturn
source .venv/bin/activate
```

**Required env var:**
```bash
export GEMINI_API_KEY=<your key>
```

**Model used everywhere:** `gemini-2.5-flash-lite` via Google's OpenAI-compatible endpoint.
```
base_url: https://generativelanguage.googleapis.com/v1beta/openai/
```
Same `openai` SDK, different `base_url` and `api_key`. This pattern is consistent across the entire codebase.

**Embeddings:** ChromaDB's default (`all-MiniLM-L6-v2`), runs locally, no API key needed, 384-dim vectors.

---

## Project structure

```
lecturn/
├── corpus/                 # Source documents
│   ├── sources.yaml        # Metadata for all documents (title, authors, url, filename)
│   ├── papers/             # PDF papers (10 total)
│   └── posts/              # Markdown blog posts (9 total)
├── retrieval/
│   ├── store.py            # ChromaDB wrapper (VectorStore class)
│   ├── baseline.py         # baseline_retrieve(query, k) — cosine sim only
│   ├── contextual.py       # contextual_retrieve(query, k) — context-enriched embeddings
│   └── reranker.py         # cross-encoder reranker (optional, Day 6)
├── evals/
│   ├── golden_dataset.yaml # 17 hand-crafted Q&A examples with expected sources/claims
│   ├── golden.py           # load_golden_dataset() → list[GoldenExample]
│   ├── deterministic.py    # Fast checks: JSON valid, required fields, citation format, no dupes
│   ├── judge.py            # LLM-as-judge: judge_faithfulness(), judge_completeness()
│   └── last_run_results.json # Output from last run_evals.py run
├── agent/
│   ├── state.py            # LecturnState TypedDict — the shared whiteboard
│   ├── graph.py            # LangGraph state machine definition + lecturn_graph instance
│   ├── nodes.py            # All 7 node functions
│   └── prompts.py          # All LLM prompt strings used by agent nodes
├── scripts/
│   ├── ingest_corpus.py    # One-time: load corpus → chunk → store in ChromaDB (baseline)
│   ├── ingest_contextual.py # One-time: generate context prefixes → store in ChromaDB (contextual)
│   ├── run_query.py        # Ad-hoc retrieval test: python scripts/run_query.py "query"
│   ├── compare_retrieval.py # Side-by-side baseline vs contextual comparison
│   ├── run_agent.py        # Run agent on a single query (edit QUERY at top of file)
│   ├── run_evals.py        # Full eval harness: naive RAG vs agent comparison
│   └── fetch_corpus.py     # Downloaded corpus documents
├── interview_artifacts/    # Writeups for portfolio
│   ├── 01_retrieval_architecture.md
│   ├── 02_eval_strategy.md
│   ├── 03_agent_design.md
│   └── lecturn_failure_modes.md
├── config.py               # Shared LLM config: MODEL, GEMINI_BASE_URL, get_client()
├── ingest.py               # Core ingestion: load_corpus(), chunk_documents()
└── chroma_db/              # Persisted vector store (do not delete)
```

---

## How to run things

### Run the agent on a single query
Edit `QUERY` at the top of the file, then:
```bash
python scripts/run_agent.py
```

### Run evals
```bash
# Agent only (faster, ~$0.05)
python scripts/run_evals.py --pipeline agent

# Naive RAG only
python scripts/run_evals.py --pipeline naive

# Full comparison (both pipelines, ~$0.08)
python scripts/run_evals.py --pipeline both
```

### Ad-hoc retrieval test
```bash
python scripts/run_query.py "what is contextual retrieval"
python scripts/run_query.py --method contextual "what is contextual retrieval"
```

### Re-ingest corpus (only needed if corpus changes)
```bash
python scripts/ingest_corpus.py       # baseline ChromaDB collection
python scripts/ingest_contextual.py   # contextual ChromaDB collection (expensive — LLM per chunk)
```

---

## The agent (agent/)

### State (`state.py`)
`LecturnState` TypedDict — the shared whiteboard passed between every node:

| Field | Set by | Description |
|---|---|---|
| `query` | caller | Never mutated |
| `mode` | `parse_query` | `"structured-notes"` \| `"comparison"` \| `"lit-review"` |
| `plan` | `plan_sections` | List of section title strings |
| `retrieved_chunks` | `retrieve` | List of `{text, source_url, title}` dicts |
| `draft` | `draft` | Raw markdown with `[source: title]` citations |
| `citations_verified` | `verify_citations` | Bool flag |
| `low_confidence_claims` | `verify_citations` | List of `{claim, score, reasoning}` |
| `revision_count` | `revise` | Loop guard — max 2 revisions |
| `final_output` | `format_output` | Final polished string shown to user |

### Graph shape (`graph.py`)
```
parse_query → plan_sections → retrieve → draft → verify_citations
                                                       │
                                         low_conf + count < 2 → revise ┐
                                                       │                └→ verify_citations
                                         otherwise → format → END
```

Import the compiled graph:
```python
from agent.graph import lecturn_graph
result = lecturn_graph.invoke(initial_state)
```

### Nodes (`nodes.py`)

| Node | LLM call? | What it does |
|---|---|---|
| `parse_query` | Yes (skipped if mode already set) | Detects mode from query |
| `plan_sections` | Yes | Generates section outline for the mode |
| `retrieve` | No | Calls `contextual_retrieve(query, k=10)` |
| `draft` | Yes | Writes structured response following plan, chunks as evidence |
| `verify_citations` | Yes (per claim) | Extracts cited sentences, calls `judge_faithfulness` on each. Score ≤ 2 = low confidence |
| `revise` | Yes | Asks LLM to drop or soften low-confidence claims |
| `format_output` | No | Assembles final string, appends warning block if claims remain unverified |

Each node returns **only the fields it changed** — LangGraph merges the dict into state.

---

## Retrieval (`retrieval/`)

**`VectorStore`** (`store.py`): thin ChromaDB wrapper. Two collections exist on disk:
- `lecturn` — baseline embeddings (raw chunks)
- `lecturn_contextual` — contextual embeddings (context prefix + chunk)

**`baseline_retrieve(query, k)`**: cosine similarity, no LLM.

**`contextual_retrieve(query, k)`**: queries the contextual collection. Context prefixes were generated once by `ingest_contextual.py` and are cached on disk at `retrieval/context_cache/`. Do not regenerate unless corpus changes.

---

## Evals (`evals/`)

**`golden_dataset.yaml`**: 17 examples. Each has `question`, `mode`, `expected_sources`, `expected_key_claims`.

**`deterministic.py`** — no LLM, instant:
- `is_valid_json(output)` — JSON structure check
- `has_required_fields(output, schema)` — required keys per mode
- `citation_format_valid(output)` — every claim has `[source: X]`
- `no_duplicate_sources(output)` — source diversity

**`judge.py`** — LLM calls:
- `judge_faithfulness(claim, chunks: list[str]) → {score: 0-5, reasoning}`
  - Score ≤ 2 = not supported by sources
- `judge_completeness(output, expected_key_claims) → {score: 0-5, reasoning, missing_claims}`

**`run_evals.py`** runs two pipelines:
- **Naive RAG**: `baseline_retrieve` → one-shot JSON generation → deterministic + judge scoring
- **Agent**: `lecturn_graph.invoke()` → completeness judge only (agent ran faithfulness internally)

---

## Key design decisions

1. **One LLM pattern**: OpenAI SDK + Gemini `base_url` everywhere. No LangChain LLM abstraction — consistent and simple.

2. **Contextual embeddings are offline**: The expensive LLM-per-chunk work runs once at ingest time. Query time is free (local vector search).

3. **Nodes return patches, not full state**: `parse_query` returns `{"mode": "..."}` — LangGraph merges it. Never mutate state directly.

4. **Citation format as contract**: The `draft` node is instructed to write `[source: title]` after every claim. `verify_citations` extracts these mechanically. The format must be consistent or verification breaks.

5. **MAX_REVISIONS = 2**: The revise loop has a hard cap. After 2 cycles, `format_output` runs regardless and flags remaining low-confidence claims with a warning block.

---

## Week 4 remaining work (Days 22–28)

- Day 22: `production/observability.py` — structured logging per node
- Day 23: `production/cache.py` — disk cache for LLM calls
- Day 24: `production/guardrails.py` — citation validator
- Day 25: `guardrails.py` — prompt injection check
- Day 26: `app.py` — Streamlit UI
- Day 27: Polish READMEs, top-level README
- Day 28: `interview_artifacts/04_production_maturity.md` + interview synthesis
