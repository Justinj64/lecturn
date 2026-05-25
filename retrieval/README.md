# Retrieval Module

Three retrieval strategies, building on each other:

## Strategies

### 1. Baseline (`baseline.py`)
Embed raw chunks with ChromaDB's default model (all-MiniLM-L6-v2), query by cosine similarity. Simplest approach — no LLM calls, no external models beyond the embedding.

### 2. Contextual (`contextual.py`)
Before embedding, prepend an LLM-generated context prefix to each chunk. The prefix situates the chunk in its source document (e.g., "This chunk is from Anthropic's 2024 paper on contextual retrieval and describes..."). Embeds the combined text. Stored in a separate ChromaDB collection (`lecturn_contextual`).

**Tradeoff:** One LLM call per chunk at ingestion time (~300 calls for our corpus). Cached to `.context_cache/` so it's a one-time cost.

### 3. Reranked (`reranker.py`)
Takes top-20 candidates from either baseline or contextual retrieval, then rescores each (query, chunk) pair with a cross-encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2`). Returns top-5 by cross-encoder score.

**Why:** Bi-encoders (ChromaDB) embed query and chunk separately — fast but approximate. Cross-encoders process them together — slow but precise. Retrieve-then-rerank gets the best of both.

**Tradeoff:** Adds ~1 second latency per query (CPU inference on 20 candidates). No API cost — model runs locally.

## Shared infrastructure

- `store.py` — Thin wrapper around ChromaDB (PersistentClient). Handles batched inserts, queries, and collection management.

## How to compare

```bash
python scripts/compare_retrieval.py        # 4-way comparison on hand-crafted queries
python scripts/compare_retrieval.py --k 3  # use top-3 instead of top-5
```
