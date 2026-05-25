# Lecturn Retrieval Architecture

## 1. Corpus, Ingestion, and Chunking

### Corpus

19 documents covering LLM engineering, retrieval, agents, and evaluation:

- **10 papers** (PDF): foundational and recent — Vaswani 2017 (Attention), Lewis 2020 (RAG), Wei 2022 (Chain-of-Thought), Yao 2022 (ReAct), Asai 2023 (Self-RAG), Liu 2023 (Lost in the Middle), Gao 2023 (RAG Survey), Trivedi 2023 (IRCoT), Rafailov 2023 (DPO), Zhou 2024 (Self-Discover)
- **9 blog posts** (Markdown): Weng (agents, hallucinations), Yan (LLM patterns, evals), Husain (evals), Huyen (LLM production), Willison (LLMs overview), Anthropic (agents, contextual retrieval)

Metadata (title, authors, year, source URL) is stored in `corpus/sources.yaml` and attached to each chunk during ingestion.

### Ingestion pipeline

1. **Load**: `ingest.py` walks `corpus/`, loads PDFs via `pypdf` (one Document per page) and Markdown files (one Document per file). Each Document gets metadata from `sources.yaml`.
2. **Chunk**: `RecursiveCharacterTextSplitter` with `chunk_size=500, chunk_overlap=100` (characters, not tokens). Produces ~300 chunks from the full corpus.
3. **Embed + store**: ChromaDB's default embedding model (`all-MiniLM-L6-v2`, 384 dimensions) runs locally. No API key needed for embedding. Chunks are batched in groups of 50.

### Why these choices

- **500-char chunks with 100-char overlap**: small enough that each chunk is topically focused, large enough to carry meaning. Overlap prevents splitting mid-sentence from losing context at boundaries.
- **Character-based splitting over token-based**: simpler, and the difference is marginal at this corpus size. For production, token-based splitting aligned to sentence boundaries would be better.
- **Local embeddings over OpenAI**: eliminates API cost and latency during development. The tradeoff is lower embedding quality — `all-MiniLM-L6-v2` (22M params) vs `text-embedding-3-small` (unknown, but larger). Acceptable for a 300-chunk corpus.

---

## 2. Retrieval Strategies: What Improved, By How Much

We implemented four retrieval strategies and compared them on 10 hand-crafted queries with known expected sources.

### The four methods

| Method | How it works | Query-time cost |
|--------|-------------|-----------------|
| **Baseline** | Embed raw chunks → cosine similarity | ~10ms |
| **Contextual** | Prepend LLM-generated context to each chunk before embedding | ~10ms |
| **Reranked baseline** | Baseline top-20 → cross-encoder rescoring → top-5 | ~1s |
| **Reranked contextual** | Contextual top-20 → cross-encoder rescoring → top-5 | ~1s |

### Results (10 queries, checking top-3 for expected sources)

| Method | MRR | Source diversity (avg unique in top-5) | Wins |
|--------|-----|---------------------------------------|------|
| Baseline | 0.785 | 1.7 | 0 |
| Contextual | 0.825 | 1.4 | 0 |
| Reranked baseline | **0.863** | 1.6 | **1** |
| Reranked contextual | 0.850 | 1.4 | 0 |

**MRR (Mean Reciprocal Rank)**: how early the expected source appears in results. 1.0 = always first, 0.5 = always second. Higher is better.

### What the numbers mean

- **Reranked baseline is the best overall.** The cross-encoder improved MRR by +0.078 over baseline — a larger gain than contextual's +0.040. It also maintained near-baseline diversity (1.6 vs 1.7).
- **Contextual hurts diversity.** Context prefixes make all chunks from one document more semantically similar, so top-5 results cluster around a single source (1.4 vs 1.7). This matters for use cases that need breadth (e.g., literature review).
- **Stacking both doesn't help.** Reranked contextual (0.850) is *worse* than reranked baseline (0.863). The cross-encoder already fixes the ranking issues contextual was solving, and contextual's diversity penalty drags it down.

### Query-level observations

- **Easy queries tie**: "how does chain of thought prompting work" → all methods find the right paper immediately. The query maps cleanly to the document title.
- **Cross-cutting queries show differences**: "what types of extrinsic hallucinations do LLMs produce" — needs to surface Weng's hallucination post *and* Yan's eval post. Reranking helped surface the most relevant chunks from multiple sources.
- **Wrong initial expectations**: Query 2 ("RAG vs fine-tuning") — I expected the blog posts to dominate, but the RAG survey paper had a dedicated comparison section. This is why you write queries after reading the corpus.

---

## 3. Tradeoffs

### Contextual retrieval
- **Ingestion cost**: One LLM call per chunk (~300 calls). Using Gemini Flash Lite, this costs pennies and takes a few minutes. Cached to `.context_cache/` so re-runs are free.
- **When it helps**: Chunks that are meaningless without context — "this approach improved results by 15%" needs the prefix to specify *which* approach in *which* paper.
- **When it doesn't**: Small corpus where the right chunks are already in the candidate pool. The problem is ranking, not recall.

### Cross-encoder reranking
- **Query-time cost**: ~1 second per query on CPU (scoring 20 candidates). No API cost — `cross-encoder/ms-marco-MiniLM-L-6-v2` runs locally.
- **When it helps**: When the right chunks are in the top-20 but not the top-5. The cross-encoder sees query and chunk together, so it handles paraphrasing, negation, and indirect references better than cosine similarity.
- **When it doesn't**: When the right chunks aren't in the top-20 at all (recall failure). The reranker can only reorder what it's given.

### The fundamental tension
- **Contextual fixes recall** (right chunks enter the candidate pool)
- **Reranking fixes precision** (right chunks float to the top)
- At small scale, precision is the bottleneck → reranking wins
- At large scale, recall becomes the bottleneck → contextual becomes essential

---

## 4. What I'd Add for Production

### Already implemented
- ✅ Cross-encoder reranking (Day 6)

### Would add next

- **Hybrid search (BM25 + embeddings)**:
  Right now we only use semantic search — we turn text into vectors and find chunks whose vectors are close to the query vector. This is great for meaning ("how do agents plan" matches "autonomous planning in LLM systems") but terrible for exact terms. If a user asks for "Self-RAG" and the chunk contains exactly that phrase, semantic search might rank it below a chunk that talks about self-reflection in general.

  BM25 is the opposite: it's keyword matching with smart weighting. It counts how often query words appear in each chunk, adjusted for chunk length and word rarity. "Self-RAG" in the query, "Self-RAG" in the chunk = high score. Simple, fast, no embeddings needed.

  The fix is to run both, then merge results. Anthropic's contextual retrieval post shows this reduces retrieval failure by 67% vs embeddings alone. The two methods catch different things — semantic catches paraphrasing, BM25 catches exact terms. ChromaDB doesn't support BM25 natively, so you'd need to add Elasticsearch or a library like `rank-bm25` alongside it.

- **Query expansion**:
  Users don't always phrase queries the way the corpus phrases answers. Someone might ask "how to make LLMs less wrong" when the corpus says "hallucination mitigation strategies." Semantic search helps bridge this gap, but not always.

  Query expansion fixes this by using an LLM to generate 2-3 alternative phrasings before retrieving. For example:
    - Original: "how to make LLMs less wrong"
    - Expanded: "hallucination reduction techniques", "improving LLM factual accuracy", "methods to reduce LLM errors"

  You retrieve for all of them, merge the results, and deduplicate. This costs one LLM call per query (fast, cheap with a small model) and dramatically improves recall on poorly-phrased queries. The tradeoff is 3-4x more retrieval calls per query.

- **Token-aware chunking**:
  Our current chunking splits on character count (500 chars, 100 overlap) using `RecursiveCharacterTextSplitter`. This works but has two problems:

  1. **Cuts mid-sentence**: A chunk might end with "the results showed that" and the next chunk starts with "contextual retrieval improved performance by 35%." Neither chunk is useful alone.
  2. **Ignores document structure**: A section header like "## Evaluation Results" might get stuck at the end of one chunk instead of the beginning of the next, where it would help retrieval.

  Token-aware chunking fixes this by splitting on sentence boundaries (never mid-sentence), measuring length in tokens (what the model actually processes, not characters), and respecting structure (keep headers with their content). Libraries like `semantic-chunkers` do this automatically, or you can use `tiktoken` to count tokens and split on `\n\n` or `. ` boundaries.

- **Embedding model upgrade**:
  We use `all-MiniLM-L6-v2` — a small model (22M parameters, 384-dimension vectors) that runs locally and fast. It's designed for speed, not quality. It was trained on general web text, not specifically on academic or technical content.

  Larger models produce better embeddings because they can capture more nuance. Options:
    - `text-embedding-3-small` (OpenAI): better quality, 1536 dimensions, costs ~$0.02 per million tokens. Requires API calls.
    - `gte-large` or `bge-large` (local): 335M parameters, 1024 dimensions. Runs locally but slower. Much better at technical content.

  For our 300-chunk corpus, the quality difference is marginal. For a production corpus with thousands of chunks where similar-sounding chunks compete for top-K slots, the embedding quality becomes the bottleneck.

- **Retrieval evals at scale**:
  Our current eval set is 10 hand-crafted queries. This is enough to spot obvious problems but not enough for statistical confidence. If we change the chunking strategy and MRR goes from 0.863 to 0.840, is that a real regression or noise from a small sample?

  A production eval setup needs:
    - **50-100+ queries** with human-annotated relevance judgments (which chunks are actually relevant, rated 0-3)
    - **Automated regression tests** that run on every change to the retrieval pipeline (new embedding model, different chunk size, etc.) and flag any drop in MRR or recall@K
    - **Stratified queries** covering different difficulty levels: easy (query matches document title), medium (query paraphrases content), hard (query requires cross-document reasoning)
    - **Metrics beyond MRR**: NDCG (normalized discounted cumulative gain) which penalizes bad results more when they're ranked higher, and recall@K (what fraction of all relevant chunks appear in top-K)
