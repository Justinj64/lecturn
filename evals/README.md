# Evals Module

Three-layer evaluation harness. Ordered cheapest-first — run deterministic checks before spending tokens on LLM judges.

## Layers

### 1. Deterministic (`deterministic.py`)
Fast structural checks with no LLM calls. Catches obvious failures in milliseconds:
- **JSON validity** — output parses without error
- **Required fields** — mode-specific schema (comparison/lit-review/notes)
- **Citation format** — every content sentence has a `[source: X]` tag
- **Source diversity** — no single source cited more than 3 times

Run standalone: `python -m evals.deterministic`

### 2. LLM-as-judge (`judge.py`)
Two scoring functions:
- `judge_faithfulness(claim, chunks)` — scores a single cited claim against retrieved chunks (0-5). Used by the agent's `verify_citations` node during generation.
- `judge_completeness(output, expected_claims)` — scores how well the output covers expected key claims from the golden dataset (0-5).

### 3. Golden dataset (`golden_dataset.yaml`, `golden.py`)
17 hand-crafted examples, each with a question, expected sources, and expected key claims. Ground truth for completeness scoring.

## Running evals

```bash
# Full comparison (naive RAG vs agent) — costs tokens
python scripts/run_evals.py --pipeline both

# Agent only
python scripts/run_evals.py --pipeline agent

# Deterministic checks only (free)
python -m evals.deterministic
```

## Baseline scorecard

| Metric | Naive RAG | Agent |
|---|---|---|
| Deterministic pass rate | 0% | 35% |
| Avg faithfulness | 4.03 / 5 | (internal loop) |
| Avg completeness | 2.24 / 5 | 2.65 / 5 |
