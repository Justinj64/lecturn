# Lecturn

A RAG (Retrieval-Augmented Generation) research assistant that answers questions about AI/ML papers and blog posts with **cited, traceable answers**. Built to explore retrieval quality, evaluation strategy, and agent architecture — with measured results at each layer.

---

## What It Does

Given a query like *"How does Self-RAG differ from standard RAG?"*, Lecturn:
1. Retrieves the most relevant chunks from a 19-document corpus (10 papers + 9 blog posts)
2. Generates a structured JSON answer grounded in those chunks
3. Cites every factual claim with `[source: title]`

Three output modes: `comparison`, `lit-review`, `notes`.

---

## Architecture

```
Query
  │
  ▼
Retrieval layer          retrieval/
  ├── Baseline           cosine similarity over raw chunk embeddings
  ├── Contextual         LLM-generated context prefix prepended before embedding
  └── Reranker           cross-encoder rescoring of top-20 candidates → top-5
  │
  ▼
Generation               naive RAG: chunks + query → LLM → structured JSON
  │
  ▼
Eval layer               evals/
  ├── Deterministic      JSON validity, required fields, citation format, source diversity
  ├── LLM-as-judge       faithfulness (per claim) + completeness (vs golden dataset)
  └── Golden dataset     17 hand-written examples with expected sources + key claims
```

### Baseline scorecard (naive RAG, no agent)

| Metric | Score |
|---|---|
| Deterministic pass rate | 0% (generation prompt doesn't enforce JSON mode — known fix) |
| Avg faithfulness | 4.03 / 5 |
| Avg completeness | 2.24 / 5 |

Faithfulness is strong — the retrieval layer is pulling relevant content and the model stays grounded. Completeness is low — a single top-5 retrieval pass misses key claims for multi-source questions. The agent layer (Week 3) addresses this with iterative retrieval planning.

---

## Corpus

19 documents covering LLM engineering, retrieval, agents, and evaluation:

**Papers:** Vaswani 2017 (Attention), Lewis 2020 (RAG), Wei 2022 (CoT), Yao 2022 (ReAct), Asai 2023 (Self-RAG), Liu 2023 (Lost in the Middle), Gao 2023 (RAG Survey), Trivedi 2023 (IRCoT), Rafailov 2023 (DPO), Zhou 2024 (Self-Discover)

**Posts:** Weng (agents, hallucinations), Yan (LLM patterns, evals), Husain (evals), Huyen (LLM production), Willison (LLMs), Anthropic (agents, contextual retrieval)

---

## Project Structure

```
corpus/             source documents (PDFs + markdown) and sources.yaml manifest
retrieval/          baseline, contextual, and reranker retrieval strategies
evals/              deterministic checks, LLM judges, golden dataset, eval runner
scripts/            ingest, query, compare retrieval, run evals
interview_artifacts/ architecture writeups and failure mode analysis
chroma_db/          persisted vector store (baseline + contextual collections)
```

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add GEMINI_API_KEY to .env
```

---

## Key Commands

```bash
# Query the corpus
python scripts/run_query.py "how does contextual retrieval work"
python scripts/run_query.py --method contextual "how does contextual retrieval work"

# Compare retrieval strategies
python scripts/compare_retrieval.py

# Run the full eval suite (makes LLM API calls — costs tokens)
python scripts/run_evals.py

# Run deterministic checks only (free, no API calls)
python -m evals.deterministic
```

---

## Design Writeups

- [Retrieval architecture](interview_artifacts/01_retrieval_architecture.md) — corpus, chunking decisions, baseline vs contextual results
- [Eval strategy](interview_artifacts/02_eval_strategy.md) — why faithfulness is hard, the 10 failure modes, scorecard analysis, production gaps
- [Failure modes](interview_artifacts/lecturn_failure_modes.md) — 10 failure modes grouped by what eval catches them
