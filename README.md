# Lecturn

A RAG (Retrieval-Augmented Generation) research assistant that answers questions about AI/ML papers and blog posts with **cited, traceable answers**. Built to explore retrieval quality, evaluation strategy, agent architecture, and production readiness — with measured results at each layer.

---

## What It Does

Given a query like *"How does Self-RAG differ from standard RAG?"*, Lecturn:
1. Screens the query for prompt injection before anything else runs
2. Retrieves the most relevant chunks from a 19-document corpus (10 papers + 9 blog posts)
3. Plans a section outline tailored to the query intent
4. Drafts a structured cited answer, then verifies each citation with an LLM judge
5. Revises the draft if any claims score below the confidence threshold
6. Validates that every `[source: X]` citation maps to an actually-retrieved source

Three output modes: `comparison`, `lit-review`, `structured-notes`.

---

## Architecture

```
Query
  │
  ├── Guardrail: injection check (production/guardrails.py)
  │
  ▼
Retrieval layer          retrieval/
  ├── Baseline           cosine similarity over raw chunk embeddings
  ├── Contextual         LLM-generated context prefix prepended before embedding
  └── Reranker           cross-encoder rescoring of top-20 candidates → top-5
  │
  ▼
Agent layer              agent/
  ├── parse_query        classify mode (structured-notes / comparison / lit-review)
  ├── plan_sections      generate section outline for the mode
  ├── retrieve           fetch top-10 contextual chunks
  ├── draft              write a cited draft following the plan
  ├── verify_citations   score each cited claim with LLM-as-judge (faithfulness 0-5)
  ├── revise             rewrite low-confidence claims (loops back, max 2×)
  └── format_output      assemble final output + validate citation titles
  │
  ▼
Production layer         production/
  ├── observability      structured JSONL logs + Langfuse tracing
  ├── cache              disk cache for LLM calls (SHA-256 keyed JSON files)
  └── guardrails         injection guard + citation title validator
  │
  ▼
Eval layer               evals/
  ├── deterministic      JSON validity, required fields, citation format, source diversity
  ├── LLM-as-judge       faithfulness (per claim) + completeness (vs golden dataset)
  └── golden dataset     17 hand-written examples with expected sources + key claims
```

### Scorecard

| Metric | Naive RAG | Agent |
|---|---|---|
| Avg faithfulness (0-5) | 4.03 | — (internal verify→revise loop) |
| Avg completeness (0-5) | 2.24 | **2.65** (+0.41) |
| Citation format pass | 0% | 35% |
| Best retrieval MRR | 0.863 (reranked baseline) | — |

---

## Corpus

19 documents covering LLM engineering, retrieval, agents, and evaluation:

**Papers:** Vaswani 2017 (Attention), Lewis 2020 (RAG), Wei 2022 (CoT), Yao 2022 (ReAct), Asai 2023 (Self-RAG), Liu 2023 (Lost in the Middle), Gao 2023 (RAG Survey), Trivedi 2023 (IRCoT), Rafailov 2023 (DPO), Zhou 2024 (Self-Discover)

**Posts:** Weng (agents, hallucinations), Yan (LLM patterns, evals), Husain (evals), Huyen (LLM production), Willison (LLMs), Anthropic (agents, contextual retrieval)

---

## Project Structure

```
corpus/                source documents (PDFs + markdown) and sources.yaml manifest
retrieval/             baseline, contextual, and reranker retrieval strategies
agent/                 LangGraph state machine (nodes, graph, state, prompts)
evals/                 deterministic checks, LLM judges, golden dataset, eval runner
production/            observability, LLM cache, guardrails
scripts/               ingest, query, compare retrieval, run evals, run agent
interview_artifacts/   architecture writeups and interview synthesis
app.py                 Streamlit UI
logs/                  structured JSONL run logs (gitignored)
cache/                 disk-cached LLM responses (gitignored)
chroma_db/             persisted vector store (baseline + contextual collections)
```

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in GEMINI_API_KEY (required)
# Fill in LANGFUSE_* keys (optional — enables tracing UI)
```

---

## Key Commands

```bash
# Streamlit UI (recommended)
python3 -m streamlit run app.py

# Run the agent from the CLI
python scripts/run_agent.py

# Query the corpus directly (no agent)
python scripts/run_query.py "how does contextual retrieval work"
python scripts/run_query.py --method contextual "how does contextual retrieval work"

# Compare retrieval strategies
python scripts/compare_retrieval.py

# Run the full eval suite (makes LLM API calls — costs tokens)
python scripts/run_evals.py --pipeline both

# Deterministic checks only (free, no API calls)
python -m evals.deterministic

# Inspect the LLM cache
python -c "from production.cache import cache_stats; print(cache_stats())"

# Clear the LLM cache
python -c "from production.cache import clear_cache; print(clear_cache(), 'entries removed')"
```

---

## Design Writeups

- [Retrieval architecture](interview_artifacts/01_retrieval_architecture.md) — corpus, chunking decisions, four-method comparison, MRR results
- [Eval strategy](interview_artifacts/02_eval_strategy.md) — why faithfulness is hard, 10 failure modes, scorecard analysis
- [Agent design](interview_artifacts/03_agent_design.md) — LangGraph state machine, conditional verify→revise loop, agent vs naive RAG scorecard
- [Production maturity](interview_artifacts/04_production_maturity.md) — observability, caching, guardrails, UI, and what's still missing
- [Failure modes](interview_artifacts/lecturn_failure_modes.md) — 10 failure modes grouped by what eval layer catches them
- [Interview synthesis](interview_artifacts/interview_synthesis.md) — prepared answers for 8 common senior LLM engineer questions
