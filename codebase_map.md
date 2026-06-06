# Lecturn Codebase Mental Map

## Covered

### Project Structure
- Overall layout: `corpus/`, `retrieval/`, `agent/`, `evals/`, `production/`, `scripts/`, `app.py`
- `config.py` is the central config — model name, LLM client factory, ChromaDB paths
- Reading order: `config.py` → `ingest.py` → `retrieval/` → `agent/` → `app.py`

### Corpus (`corpus/`)
- `corpus/papers/` — PDFs downloaded manually from arxiv
- `corpus/posts/` — blog posts fetched automatically by `scripts/fetch_corpus.py` using `trafilatura`
- `corpus/sources.yaml` — auto-generated manifest of all documents (papers + posts), written by `build_sources_yaml()` in `fetch_corpus.py`
- Both the post URLs and paper metadata are hardcoded in `POSTS` and `PAPERS` lists in `fetch_corpus.py`

### Retrieval Pipeline (`retrieval/`)

#### Baseline (`retrieval/baseline.py`)
- Chunk document by chunk size + chunk overlap
- Embed each chunk independently
- Store in ChromaDB
- Query: pass query → fetch top-k chunks by cosine similarity (bi-encoder)

#### Contextual (`retrieval/contextual.py`)
- Combine all pages into one full document
- For each chunk: send `(full_doc, chunk)` to LLM → get a context prefix describing where the chunk fits
- Prepend prefix to chunk → embed the enriched chunk
- Store in ChromaDB
- Query: same as baseline but embeddings carry richer context

#### Reranking (`retrieval/reranker.py`)
- Step 1: fetch 20 candidates cheaply from ChromaDB (bi-encoder, same as baseline/contextual)
- Step 2: score all 20 `(query, chunk)` pairs through a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
- Step 3: return top 5 by cross-encoder score
- Convenience wrappers: `reranked_baseline_retrieve()` and `reranked_contextual_retrieve()`

#### Retrieval Comparison (`scripts/compare_retrieval.py`)
Runs all 4 methods against queries from `evals/queries.yaml` and scores them on 3 metrics:

**Hit Rate** — did the expected source appear in the top 3 results? Yes or no.
- Query: *"how does dense retrieval work?"*, expected: `RAG Survey`
- If `RAG Survey` is anywhere in top 3 → hit ✓

**MRR (Mean Reciprocal Rank)** — did we find it near the top? Position matters.
- Score per source = 1 / rank (rank 1 → 1.0, rank 3 → 0.33, not found → 0)
- Per-query MRR = average across all expected sources for that query
- Example with 2 expected sources: found at rank 1 and rank 4 → (1.0 + 0.25) / 2 = 0.625
- Final MRR = average of per-query scores across all queries
- Rank is just the position in the list the retriever returned — `find_source_rank()` scans top to bottom and returns the position where the expected title first appears (title substring match against `doc.metadata["title"]`)

**Source Diversity** — how many distinct documents appear in the top 5 results?
- Counts unique titles using a set — 3 chunks from the same paper still counts as 1
- diversity = 2 → retriever fixated on 2 sources, repetitive chunks
- diversity = 5 → results spread across 5 different documents, broader coverage
- Doesn't measure correctness — measures breadth. High MRR + low diversity means right answer but missing context from other sources.

Winner per query: highest hit count, MRR breaks ties.

#### Why cross-encoder vs bi-encoder
**Bi-encoder (ChromaDB):**
- Chunk → transformer → vector
- Query → transformer → vector (separate pass, later)
- Compare vectors with cosine similarity
- Two separate forward passes — query and chunk never see each other during encoding

**Cross-encoder:**
- `[query][chunk]` fed together as one sequence → transformer → single relevance score (a number, e.g. 0.87)
- No vectors produced, nothing stored
- One forward pass with both texts together

**Why cross-encoder is more precise:**
- Attention is the core mechanism inside the transformer — for every token, it asks "which other tokens in this sequence should I attend to?"
- With a bi-encoder, `"outperformed"` can only attend to tokens within its own chunk. The query never enters the picture.
- With a cross-encoder, `"BM25"` in the query can attend to `"sparse methods"` in the chunk, and `"outperformed"` can attend to `"compare"` in the query — full joint understanding before scoring
- This is why it can match semantically equivalent phrases (e.g. "no gradient updates" ↔ "no backpropagation") that a bi-encoder would miss
- Too slow to scan full DB (no pre-computation possible) → used only on 20 pre-filtered candidates

### Evaluations (`evals/`)

#### Golden Dataset (`evals/golden.py`)
Each example has 4 fields:
- `question` — the query to send to Lecturn
- `mode` — one of `comparison`, `lit-review`, `notes`
- `expected_sources` — source titles that must be cited
- `expected_key_claims` — claims the output should contain

#### Deterministic Checks (`evals/deterministic.py`)
Fast, no LLM calls. Run first before spending money on judge evals. 4 checks in order:

**1. Valid JSON**
Output must be parseable JSON. If this fails, nothing else can run.
```
{"answer": "ok", "sources": []}   ✓
{"answer": "ok", "sources": [}    ✗  syntax error
```

**2. Required fields**
Each mode has a schema of required keys. Checks all are present.
```
comparison needs: query, similarities, differences, sources
lit-review needs: query, summary, sources
notes needs:      query, key_points, sources
```
If `answer` is missing from a `default` mode response → fail.

**3. Citation format**
Every content claim must have a `[source: X]` marker after it. Citations follow the claim they support. The check splits on citation markers and looks at the tail — if text after the last citation is longer than 40 chars, it's flagged as uncited.
```
"RAG reduces hallucinations. [source: Lewis 2020]"  ✓
"RAG reduces hallucinations."                        ✗  no citation
"RAG reduces hallucinations. [source: Lewis 2020] But it also increases latency significantly."
                                                     ✗  tail after last citation is too long
```

**4. No duplicate sources**
Counts `[source: X]` markers across the whole output. Any source cited more than 3 times is flagged — catches the case where the model summarises one document instead of synthesising across sources.
```
[source: Weng 2023] x4  →  ✗ flagged
[source: Weng 2023] x2 + [source: Lewis 2020] x2  →  ✓
```

#### LLM-as-Judge (`evals/judge.py`)
Two separate LLM calls, both score 0-5:

**Completeness** — did the response cover all expected key claims?
- Input: `(output, expected_key_claims)`
- LLM checks how many claims from the golden dataset appear in the response
- Returns score + list of missing claims
- Example: expected 3 claims, response only covers 1 → low score + 2 missing claims listed

**Faithfulness** — is each claim actually supported by the retrieved chunks?
- Input: `(claim, retrieved_chunks)`
- LLM checks whether the chunks back up the claim or contradict it
- 0 = contradicted, 5 = fully supported
- Example: claim says "RAG was developed at Google Brain", chunks say "Facebook AI Research" → score 0

Note: `run_judge()` which combines both is currently a stub (`NotImplementedError`).

#### Why completeness scores low (2.24/5)
Naive retrieval does one query → top 5 chunks by cosine similarity. One query vector points in one direction in vector space. If the golden dataset expects 5 specific claims, those claims live in 5 slightly different regions of vector space — the chunks for claims 3, 4, 5 may be just far enough away to miss the top 5 cutoff even though they're all topically related.

Example: query *"how does contextual retrieval improve results?"* pulls chunks about prefixes, chunking, embedding strategies — all topically close. But the specific chunk with *"67% failure rate reduction"* sits in a slightly different direction and gets bumped out by more similar chunks.

This is a retrieval coverage gap, not a generation problem — the model can't write what it never saw.

The agent fixes this by breaking the question into sub-queries and retrieving separately for each angle, giving each specific claim a better chance of surfacing.

---

### Agent (`agent/`)

#### Overview
LangGraph pipeline where each node reads from and writes to a shared `LecturnState` dict. Nodes contain the logic, graph.py contains the wiring.

#### `state.py` — shared notepad
`LecturnState` is a TypedDict that starts mostly empty and gets filled stage by stage:
```
query                ← caller provides this
mode                 ← parse_query fills this
plan                 ← plan_sections fills this
retrieved_chunks     ← retrieve fills this
draft                ← draft fills this
low_confidence_claims ← verify_citations fills this
revision_count       ← revise increments this
final_output         ← format_output fills this
```

#### `graph.py` — the wiring
```
parse_query → plan_sections → retrieve → draft → verify_citations
                                                        ↓
                                            (low confidence claims?)
                                           yes ↓              no ↓
                                           revise            format
                                              ↓
                                      verify_citations (max 2 loops)
```
Conditional routing: if `low_confidence_claims` exist and `revision_count < 2` → revise, else → format.

**Import time vs invoke time:**
- `lecturn_graph = build_graph()` runs once when `graph.py` is imported — wires nodes and edges, compiles the graph. No LLM calls, no data, just structure.
- `lecturn_graph.invoke(initial_state)` is when data actually flows — nodes execute in order, LLM calls happen, ChromaDB is queried, state gets filled in stage by stage.
- Entry point is set explicitly via `graph.set_entry_point("parse_query")` — so `invoke` always starts at `parse_query`.

#### `nodes.py` — the logic

**parse_query** — classifies query into mode (`lit-review` / `comparison` / `structured-notes`). Skips entirely if mode already set.

**plan_sections** — sends query + mode to LLM → gets back a list of section headers that structure the answer. Falls back to `["Overview", "Key Claims", "Limitations"]` on parse failure.
- `lit-review` → thematic sections across papers
- `comparison` → similarities, differences, verdict
- `structured-notes` → key points, methodology, findings
- Purpose: tells the drafter "here's the outline, now fill it in"

**retrieve** — calls `contextual_retrieve(query, k=10)`, converts docs to dicts with `text`, `title`, `source_url`.

**draft** — sends 10 chunks + section plan to LLM → writes structured response with `[source: X]` citations per section. Resets `citations_verified=False`, `low_confidence_claims=[]`, `revision_count=0`.

**verify_citations** — extracts every sentence containing `[source: ...]` from the draft, calls `judge_faithfulness(claim, chunks)` on each. Flags any with score ≤ 2 as low confidence.

**revise** — sends original draft + low confidence claims (with scores and reasoning) to LLM → rewrites to soften or drop unsupported claims. Increments `revision_count`, resets `low_confidence_claims=[]`.

**format_output** — assembles final output with query as heading. Also runs `validate_citations` to catch hallucinated source names (cited but not in retrieved chunks). Appends warning blocks for both low confidence claims and hallucinated citations.

#### Full example: *"how does RAG reduce hallucinations?"*
1. `parse_query` → mode = `"lit-review"`
2. `plan_sections` → `["What is RAG", "How it reduces hallucinations", "Limitations"]`
3. `retrieve` → 10 chunks from ChromaDB
4. `draft` → structured response with `[source: Lewis 2020]` etc.
5. `verify_citations` → finds `"RAG eliminates hallucinations entirely"` scores 1/5 → low confidence
6. routing → revision_count=0 < 2, problems exist → go to `revise`
7. `revise` → rewrites to `"RAG significantly reduces hallucinations"`, revision_count=1
8. `verify_citations` again → all claims score > 2 → no problems
9. routing → no problems → go to `format`
10. `format_output` → assembles final answer, checks for hallucinated citations, appends warnings if needed

#### Agent Limitations (from `interview_artifacts/03_agent_design.md`)

**Single-Collection Retrieval**
`retrieve` makes one call with the full query and fetches 10 chunks. For multi-faceted queries like *"compare RAG and fine-tuning across latency, cost, and accuracy"*, the single query vector points in one direction and may surface 8 chunks about RAG and 2 about fine-tuning — the cost and accuracy angles never make the top 10.

Fix would be retrieving once per section from the plan:
```
retrieve("RAG vs fine-tuning latency")   → 10 chunks
retrieve("RAG vs fine-tuning cost")      → 10 chunks
retrieve("RAG vs fine-tuning accuracy")  → 10 chunks
```
Each targeted call has a better chance of surfacing the right chunks per facet. Tradeoff: N retrieval calls instead of 1 (one per section).

**Mode Detection Variability**
`parse_query` uses the LLM at `temperature=0` to classify the query into one of 3 modes. Misclassification is possible and silently propagates — if *"structured notes on Self-RAG"* gets classified as `lit-review`, the plan becomes a thematic survey across multiple papers instead of focused notes on one paper. The draft follows that wrong plan. No validation checks that the detected mode matches user intent.

**Plan Before Retrieve Drift**
`plan_sections` runs before `retrieve` — the LLM plans sections based only on the query and mode, with no knowledge of what the corpus actually contains. If the corpus can't support a planned section, the drafter writes "Insufficient source coverage for this section." The fix would be to retrieve first (broad k=20-30), pass chunks to the planner so sections are grounded in what's available, then retrieve again per section for targeted coverage.

**Bugs Fixed**
- `nodes.py` `draft` node: chunks were labelled `[Chunk N: title]` in the user message, causing the model to cite `[Chunk N]` instead of `[source: title]`. `verify_citations` looks for `[source:` — so `claims_checked=0` and the faithfulness loop never fired. Fixed by labelling chunks as `[Source: title]`.
- `scripts/run_evals.py` `generate_answer`: naive RAG model wrapped JSON output in ` ```json ``` ` fences despite prompt instructions, causing `json_valid: false`. Fixed by stripping fences from the raw response before eval checks run.
- `evals/deterministic.py` `_extract_content_strings`: `query` field value and source title strings in the `sources` array were being treated as content-bearing claims requiring citations (false positives). Fixed by skipping keys in `_METADATA_KEYS = {"query", "mode", "sources"}`.

---

### Production Layer (`production/`)

#### `cache.py` — LLM response caching
Disk cache for all LLM calls. Key is SHA-256 of `(model, messages, temperature, max_tokens)` — stored as one JSON file per unique request under `cache/llm/`. Every node's LLM call goes through `_llm()` in `nodes.py`, which checks cache before hitting the API. No expiry — entries persist until `clear_cache()` is called. Judges in `evals/judge.py` bypass this cache (call API directly).

#### `observability.py` — structured logging + Langfuse
Two parallel outputs:
- **Local JSONL** (`logs/lecturn.jsonl`) — always on, no external deps. Every `log_event()` call appends one JSON line with `ts`, `run_id`, and event data.
- **Langfuse** — cloud trace UI, active only if `LANGFUSE_SECRET_KEY` is set. The entire agent run is wrapped in `@observe("lecturn-agent")` in `app.py` / `run_agent.py`. `end_run()` flushes spans to Langfuse before exit.

`timed_node(name)` is a context manager used in every node — logs `name.start` before the block, `name.end` with `duration_s` + whatever stats were written into `meta` after.

#### `guardrails.py` — input/output safety
Two checks, no LLM needed:
- **`check_query(query)`** — regex scan for prompt injection patterns before the graph runs. Also blocks queries over 1000 chars. Returns `{"safe": bool, "reason": ...}`. Called first in `app.py` and `run_agent.py` — graph never runs on a blocked query.
- **`validate_citations(draft, chunks)`** — after drafting, checks every `[source: X]` name against retrieved chunk titles (loose substring match both ways). Returns `valid`, `invalid`, and `pass` flag. Called inside `format_output` — hallucinated citations get appended as a warning block.

### Ingestion (`ingest.py`)
Walk `corpus/papers/` → load PDFs with PyPDF (one `Document` per page). Walk `corpus/posts/` → read `.md` files (one `Document` per file). Attach metadata (`title`, `source_url`, `type`) from `sources.yaml` to each document. Returns a flat list of `Document` objects ready for chunking — does not chunk or embed.

### App (`app.py`)
Streamlit UI. On submit: runs `check_query` → builds `initial_state` → calls `new_run()` → invokes `lecturn_graph`. If Langfuse keys are set, wraps the graph call in `@observe`. After run: calls `end_run()`, renders final markdown output, sidebar shows mode/plan/sources/cache stats, expander shows any low-confidence claims.

Mode can be set explicitly via dropdown ("Auto" lets `parse_query` detect it).

### Scripts (`scripts/`)
- **`run_query.py`** — CLI wrapper: pass `--method baseline|contextual` and a query string, prints top 5 chunks with titles and source URLs. No agent, no evals.
- **`run_agent.py`** — CLI wrapper for a full agent run. Hardcode `QUERY` and `MODE` at the top. Runs guardrail check, invokes graph, prints `final_output` + full state summary. Same Langfuse wrapping as `app.py`.
- **`run_evals.py`** — runs both naive RAG and agent pipelines against the golden dataset and prints a side-by-side comparison scorecard. Naive RAG outputs JSON → all 4 deterministic checks + faithfulness + completeness. Agent outputs markdown → citation format check + completeness only (faithfulness already ran internally). Use `--pipeline naive|agent|both`.

---

## To Cover

Nothing remaining — full codebase covered.
