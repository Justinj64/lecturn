# Lectern — Day-by-Day Build Roadmap

A focused Lectern-only view of the 28-day build. The `focus_month.html` tracker mixes daily reading, DSA, Lectern, and writing into each day. This doc strips that down to "what does Lectern look like at the end of each day."

Time budget per day: ~1-1.5 hours weekdays, 3 hours Saturday, 1 hour Sunday (Sunday is mostly writing).

Each day has: **what you build**, **acceptance criteria** (when the day is done), and **what to skip if you're behind**.

---

## Week 1 — Retrieval (Days 1–7)

**Goal by end of week:** baseline + contextual retrieval working end-to-end on a real corpus, with measured improvement on a small hand-written query set. One writeup published.

### ~~Day 1 — Skeleton~~

**Build:**
- Create `lectern/` repo on GitHub (private is fine)
- Folder structure per `lectern_scope.md`: `corpus/`, `lectern/retrieval/`, `lectern/evals/`, `lectern/agent/`, `lectern/production/`, `scripts/`, `interview_artifacts/`
- `requirements.txt` with: `anthropic`, `openai`, `chromadb` (or `faiss-cpu`), `tiktoken`, `pypdf`, `trafilatura`
- `README.md` with one-paragraph project brief + "how to run" placeholder
- `.gitignore` (Python defaults + `.env` + `corpus/papers/*.pdf`)
- `.env.example` for API keys
- `config.py` with `CHUNK_SIZE = 500`, `MODEL = "claude-sonnet-4-5"`, `EMBEDDING_MODEL = "text-embedding-3-small"`

**Acceptance:** repo exists, structure committed, `pip install -r requirements.txt` succeeds in a fresh venv.

**Skip if behind:** the `production/` folder (create it Day 22 when needed).

---

### ~~Day 2 — Corpus + naive chunking~~

**Build:**
- Run the corpus download prompt (`lectern_corpus_prompt.md`) via Claude Code → 10 papers + 9 blog posts in `corpus/`
- `lectern/ingest.py`: function that walks `corpus/`, loads PDFs (pypdf) and markdown files, returns list of `Document(text, source_url, title, metadata)` objects
- Simple chunking function: fixed-size chunks with overlap (500 tokens, 100 overlap)
- `scripts/ingest_corpus.py`: script that runs ingestion and prints "X documents, Y chunks"

**Acceptance:** running `python scripts/ingest_corpus.py` prints chunk counts and a sample chunk per document.

**Skip if behind:** blog posts; start with just the 10 papers.

---

### ~~Day 3 — Baseline retrieval~~

**Build:**
- `lectern/retrieval/store.py`: thin wrapper around ChromaDB (or FAISS) for embedding + storing + querying
- `lectern/retrieval/baseline.py`: function that takes a chunk list and a query, returns top-K chunks ranked by cosine similarity
- `scripts/run_query.py`: takes a query string, prints top 5 chunks with sources

**Acceptance:** `python scripts/run_query.py "what is contextual retrieval"` returns 5 chunks that are at least topically related, with source URLs printed.

**Skip if behind:** nothing — this is the foundational step.

---

### ~~Day 4 — Contextual retrieval~~

**Build:**
- `lectern/retrieval/contextual.py`: implements Anthropic's contextual retrieval pattern — for each chunk, generate a 50-100 token context prefix using Claude that situates the chunk within the document
- Cache the context prefixes (write to disk; this is expensive to regenerate)
- Embed `context + chunk` instead of raw chunk
- New function `contextual_retrieve(query, k)` parallel to baseline

**Acceptance:** Can run baseline and contextual retrieval on the same query and see the top-K results differ. Context prefixes are cached so re-runs are free.

**Skip if behind:** the caching layer (just regenerate prefixes; it costs ~₹100 per full pass).

---

### Day 5 — Comparison + hand-written queries

**Build:**
- Write 5-10 hand-crafted queries that you know the right answer to (because you've read the corpus). Examples: "what's the difference between RAG and fine-tuning per Eugene Yan", "how does contextual retrieval work per Anthropic"
- `scripts/compare_retrieval.py`: runs each query through baseline and contextual, prints top-K for each, prints which retrieval method got the "right" chunk in top-3

**Acceptance:** you can eyeball that contextual is better on some queries, comparable on others. Maybe 5-7 out of 10 queries show contextual winning. Numbers matter for the writeup.

**Skip if behind:** drop to 5 queries instead of 10.

---

### ~~Day 6 — Polish + (optional) reranking~~

**Build:**
- Clean up `lectern/retrieval/` — add docstrings, README in the folder explaining the two strategies
- If time: add a cross-encoder reranker (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2` via sentence-transformers) that takes top-20 from retrieval and reranks to top-5
- If reranking is added, extend `compare_retrieval.py` to a 3-way comparison

**Acceptance:** retrieval module is documented enough that you could hand it to another developer and they could use it.

**Skip if behind:** reranking entirely. Polish is enough.

---

### ~~Day 7 — Writeup: `lectern_retrieval_architecture.md`~~

**Build:**
- Document in `interview_artifacts/01_retrieval_architecture.md`:
  - Section 1: corpus, ingestion, chunking decisions (what you chose, why)
  - Section 2: baseline vs contextual — what improved, by how much, on which queries (cite specific numbers)
  - Section 3: tradeoffs you noticed (cost of contextual, when baseline is enough)
  - Section 4: what you'd add for production (reranking, query expansion, hybrid search)
- Record a 3-minute Loom walking through the design out loud. Don't edit. Watch it back.

**Acceptance:** writeup is published to repo. Loom is in `interview_artifacts/looms/`. You can talk about retrieval for 5 minutes without notes.

**Skip if behind:** the Loom (do it Day 8 morning). Don't skip the writeup.

---

## Week 2 — Evals (Days 8–14)

**Goal by end of week:** working eval harness on a golden dataset of 15-20 examples, scoring faithfulness + completeness + format validity. This is the *senior signal* layer of Lectern.

### Day 8 — Evals module scaffolding

**Build:**
- `lectern/evals/` module structure: `golden.py`, `deterministic.py`, `judge.py`, `golden_dataset.yaml`
- Empty function stubs for: `run_deterministic_checks(output)`, `run_judge(output, query, retrieved_chunks)`, `load_golden_dataset()`

**Acceptance:** module imports cleanly. Stubs raise NotImplementedError.

---

### Day 9 — Failure modes inventory

**Build:**
- Brainstorm 10 ways Lectern can fail. Examples: hallucinated citations, citations pointing to wrong passage, missed key source, format breaks (invalid JSON), confidence not calibrated, repeats same source, missing required sections, contradicts itself between sections, fabricated quote, wrong attribution between similar papers
- Write these to `interview_artifacts/lectern_failure_modes.md` (this becomes part of the Week 2 writeup)
- Group failure modes by "what eval catches this"

**Acceptance:** 10 failure modes written down with eval coverage notes.

---

### Day 10 — Deterministic checks

**Build:**
- `lectern/evals/deterministic.py` implements:
  - `is_valid_json(output)` — structured output check
  - `has_required_fields(output, schema)` — completeness on output shape
  - `citation_format_valid(output)` — every claim ends with `[source: X]` or similar
  - `no_duplicate_sources(output)` — diversity check
- These should all run in milliseconds, no LLM calls

**Acceptance:** each check has 2-3 unit-test-style examples (inline in the file) showing it passes correct outputs and fails broken ones.

---

### Day 11 — Golden dataset

**Build:**
- Write 15-20 entries in `golden_dataset.yaml`. Each entry: `{question, expected_sources, expected_key_claims, mode}` where mode is one of comparison/lit-review/notes
- These are based on questions you can answer from the corpus (the curated 19 documents from Day 2)
- `golden.py`: loader that returns the dataset as Python objects

**Acceptance:** 15-20 examples ready. Loader returns them. Each has at least 2 expected_sources and 2 expected_key_claims.

---

### Day 12 — LLM-as-judge for faithfulness

**Build:**
- `lectern/evals/judge.py` implements:
  - `judge_faithfulness(claim, retrieved_chunks)` — uses Claude to check if claim is supported by the chunks
  - `judge_completeness(output, expected_key_claims)` — uses Claude to check coverage
- Each judge function returns `{score: 0-5, reasoning: str}`
- Use a tight prompt with examples in the prompt

**Acceptance:** can run `judge_faithfulness("RAG reduces hallucinations", [chunk1, chunk2])` and get a sensible score with reasoning.

---

### Day 13 — Run evals end-to-end

**Build:**
- `scripts/run_evals.py`: runs every golden example through the current Lectern pipeline (retrieval + a basic generation step), produces a scorecard
- Generate basic comparison output (you don't have an agent yet, so this can be a simple "retrieve top-K, ask Claude to answer from chunks" function)
- Print: deterministic pass rate, average faithfulness score, average completeness score, breakdown by mode

**Acceptance:** running the evals produces a clean scorecard. Some scores will be poor — that's good, it means the evals are catching things.

---

### Day 14 — Writeup: `lectern_eval_strategy.md`

**Build:**
- Document in `interview_artifacts/02_eval_strategy.md`:
  - Section 1: why citation faithfulness is Lectern's hardest eval (and why LLM-as-judge for faithfulness is itself unreliable)
  - Section 2: the 10 failure modes (from Day 9)
  - Section 3: what evals catch which failure
  - Section 4: scorecard from Day 13 with discussion of what's working and what's not
  - Section 5: what you'd add for production (human eval, regression testing, eval drift)
- Loom: 3 minutes walking through eval strategy

**Acceptance:** writeup published. Loom recorded. You can talk about evals for 5 minutes without notes.

**This is the day Lectern earns its place on the resume.** Update the Projects section. **Start applying.**

---

## Week 3 — Agent (Days 15–21)

**Goal by end of week:** LangGraph state machine running end-to-end with at least one conditional edge. Lectern produces structured output via the agent, not via a one-shot generation.

### Day 15 — LangGraph setup + state schema

**Build:**
- `lectern/agent/state.py`: define `LectionState` as a TypedDict or Pydantic model. Fields: query, mode, plan, retrieved_chunks, draft, citations_verified, low_confidence_claims, final_output
- `lectern/agent/graph.py`: skeleton LangGraph definition with empty node functions

**Acceptance:** state schema is clear. Graph compiles (no execution yet).

---

### Day 16 — Core nodes

**Build:**
- `lectern/agent/nodes.py` implements:
  - `parse_query(state)` — extracts query type, key entities
  - `plan_sections(state)` — generates section outline based on mode
  - `retrieve(state)` — uses Day 4 contextual retrieval, populates retrieved_chunks
  - `draft(state)` — generates structured output using Claude
- Each node updates state and returns the modified state

**Acceptance:** can run the four nodes in sequence manually (without the graph) and produce a draft output.

---

### Day 17 — Wire up the graph, pick first mode

**Build:**
- In `graph.py`, connect parse → plan → retrieve → draft as a linear chain in LangGraph
- Pick ONE mode to focus on (suggest: structured-notes mode — simplest)
- `scripts/run_agent.py`: runs the agent end-to-end on a single query

**Acceptance:** `python scripts/run_agent.py "structured notes on contextual retrieval"` produces a structured output.

---

### Day 18 — verify_citations + revise nodes

**Build:**
- `verify_citations(state)` — for each claim in the draft, calls `judge_faithfulness` (from Day 12) against the cited chunks. Marks low-confidence claims.
- `revise(state)` — if low-confidence claims exist, re-retrieves with refined queries or asks Claude to drop unsupported claims

**Acceptance:** nodes are written and can be called manually.

---

### Day 19 — Conditional edges

**Build:**
- Add conditional edge: after `verify_citations`, if `low_confidence_claims` is non-empty, route to `revise`. Otherwise route to `format` (final node).
- After `revise`, loop back to `verify_citations` (with a max-iteration guard to prevent infinite loops)
- This is the heart of "agent" vs "pipeline" — the conditional routing

**Acceptance:** `scripts/run_agent.py` now traces a path that includes `verify → revise → verify` on at least some queries. Print the path for debugging.

---

### Day 20 — Run agent against golden dataset

**Build:**
- Modify `scripts/run_evals.py` to use the agent (instead of the basic generation from Day 13)
- Compare scorecards: agent vs basic generation
- Note where the agent helps (faithfulness should improve) and where it doesn't (latency goes up, cost goes up)

**Acceptance:** clean scorecard comparison. At least one quantifiable improvement.

---

### Day 21 — Writeup: `lectern_agent_design.md`

**Build:**
- Document in `interview_artifacts/03_agent_design.md`:
  - Section 1: what Lectern does (2-paragraph description)
  - Section 2: state machine design — diagram (Excalidraw or Mermaid) + walkthrough of each node and edge
  - Section 3: the conditional re-retrieval pattern, with example of when it fired
  - Section 4: agent vs pipeline — what changed in the scorecards
  - Section 5: limits + what's brittle
- Loom: 3 minutes walking through state graph

**Acceptance:** writeup published. Loom recorded. Apply to 5 more companies — you have a full demoable system now.

---

## Week 4 — Production (Days 22–28)

**Goal by end of week:** observability, caching, guardrails. A clean repo + 4 writeups in `interview_artifacts/`. The "polish" week.

### Day 22 — Observability

**Build:**
- `lectern/production/observability.py`: structured logging via stdlib `logging` + JSON formatter. Every node logs entry/exit, latency, token counts.
- Optional upgrade: integrate Langfuse if signup is quick (10 minutes)
- Add log statements to every node

**Acceptance:** running the agent produces a clean log trace showing the path taken and timing per node.

---

### Day 23 — Caching

**Build:**
- `lectern/production/cache.py`: simple disk-based cache for embeddings and LLM calls
- Cache key: hash of (model, prompt, query)
- Cache value: response
- Wire into retrieval (embedding cache) and generation (response cache for deterministic prompts)

**Acceptance:** running the same query twice — second run is meaningfully faster and cheaper.

---

### Day 24 — Citation validator (guardrail)

**Build:**
- `lectern/production/guardrails.py`: implements `validate_citations(output)` — for each citation in the output, verify the cited passage actually exists in the corpus and contains the claim. This is stricter than the LLM-as-judge.
- Wire into the agent as a post-processing step

**Acceptance:** can catch fabricated citations that the LLM-as-judge missed.

---

### Day 25 — Prompt injection check

**Build:**
- In `guardrails.py`: add `check_prompt_injection(doc_text)` — uses Claude to detect if document content contains instructions trying to override system prompts
- Run as a preprocessing step on ingested documents
- This is more about demonstrating awareness than catching real attacks — but write the check

**Acceptance:** function exists, has 2-3 test examples (injection vs benign).

---

### Day 26 — Streamlit UI

**Build:**
- `app.py` at repo root: Streamlit page with a textarea, mode selector (comparison/lit-review/notes), submit button, output display
- Calls into the agent module
- This is the demo surface for interviews — record-screen quality, not production quality

**Acceptance:** `streamlit run app.py` opens a working interface. You can demo Lectern in a screenshare.

---

### Day 27 — Polish + interview_artifacts/

**Build:**
- Clean READMEs in `lectern/retrieval/`, `lectern/evals/`, `lectern/agent/`, `lectern/production/` — each ~10-15 lines explaining what's there
- Top-level repo README: project brief, how to run, architecture diagram, link to each writeup
- `interview_artifacts/` should now have: 01_retrieval, 02_evals, 03_agent (and 04 coming tomorrow). Plus the Loom links collected.

**Acceptance:** if you handed the repo to a senior engineer cold, they could understand what Lectern is and run it within 10 minutes.

---

### Day 28 — Writeup: `lectern_production_maturity.md` + final synthesis

**Build:**
- `interview_artifacts/04_production_maturity.md`:
  - Section 1: observability — what's logged, how to find failures
  - Section 2: caching — what's cached, hit rates
  - Section 3: guardrails — citation validator, prompt injection check
  - Section 4: cost — back-of-envelope per query
  - Section 5: what's missing for real production (rate limiting, retry, A/B testing, regression evals on every PR)
- `interview_artifacts/interview_synthesis.md`: prepared answers for 8 common senior LLM interview questions (how do you eval, how do you handle hallucinations, why this agent design, etc.)

**Acceptance:** Lectern is feature-complete and interview-ready. You can pitch the whole system in 3 minutes and go deep on any layer for 15 minutes.

---

## Catch-up rules

If you're behind on Lectern (likely — life happens):

- **Skip first:** reranking (Day 6), Streamlit UI polish (Day 26), prompt injection check (Day 25)
- **Don't skip:** Day 7 writeup, Day 14 writeup, Day 21 writeup, Day 28 writeup. The writeups are the artifacts.
- **Compress weeks if needed:** Week 1 can collapse to 5 days if you push retrieval hard. Week 4 can collapse to 4 days. The middle weeks (Evals, Agent) are the senior signal — protect them.

## What "done" looks like

By Day 28, Lectern is a repo with:
- Working retrieval (baseline + contextual)
- Working evals (deterministic + LLM-as-judge on golden dataset)
- Working LangGraph agent with conditional re-retrieval
- Production layer (observability, caching, citation validator)
- 4 writeups + 4 Looms in `interview_artifacts/`
- Streamlit demo

Total time invested: ~50-60 hours over 28 days. That's the build.