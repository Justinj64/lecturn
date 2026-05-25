"""
Cross-encoder reranker: takes a query + candidate chunks from a retrieval
method, and reranks them using a cross-encoder model for higher precision.

WHY RERANK?
    ChromaDB retrieval uses a bi-encoder: query and chunks are embedded
    SEPARATELY, then compared via cosine similarity. This is fast (you
    pre-compute chunk embeddings once), but the query and chunk never
    "see" each other — the model can't attend across both texts.

    A cross-encoder takes (query, chunk) AS A PAIR and processes them
    through a single transformer. The model sees both texts together,
    so it can do things like:
      - Match "how does X work" to a passage that explains X without
        using the word "work"
      - Understand negation: "methods that DON'T use fine-tuning"
      - Resolve pronoun references across query and chunk

    The tradeoff: cross-encoders are ~100x slower than bi-encoders
    because you can't pre-compute anything. Every (query, chunk) pair
    requires a full forward pass. That's why we use it as a RERANKER
    (score 20 candidates) rather than a retriever (score 300+ chunks).

THE PATTERN:
    1. Retrieve top-N candidates cheaply (bi-encoder via ChromaDB)
    2. Score each candidate with the cross-encoder
    3. Sort by cross-encoder score
    4. Return top-K

    This is called "retrieve-then-rerank" — cheap recall first,
    expensive precision second. It's the standard production pattern
    used by search engines, and Anthropic recommends it in their
    contextual retrieval post.

MODEL:
    We use `cross-encoder/ms-marco-MiniLM-L-6-v2` — a small (22M params)
    model trained on MS MARCO (a web search relevance dataset). It runs
    locally on CPU in ~1 second for 20 candidates. No API key needed.
"""
from sentence_transformers import CrossEncoder
from langchain_core.documents import Document
from retrieval.baseline import baseline_retrieve
from retrieval.contextual import contextual_retrieve

# Load the model once at import time. It's small (~80MB) and stays in memory.
# Subsequent calls reuse the same model — no reload cost.
_reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


def rerank(query: str, documents: list[Document], k: int = 5) -> list[Document]:
    """
    Rerank a list of candidate documents using the cross-encoder.

    The cross-encoder scores each (query, document) pair independently.
    Higher score = more relevant. We sort by score descending and
    return the top-k.

    Args:
        query: the user's search query
        documents: candidate chunks from a bi-encoder retrieval step
        k: how many to return after reranking

    Returns:
        top-k documents sorted by cross-encoder relevance score
    """
    if not documents:
        return []

    # Build (query, chunk_text) pairs for the cross-encoder
    pairs = [(query, doc.page_content) for doc in documents]

    # Score all pairs in one batch (faster than scoring individually)
    scores = _reranker.predict(pairs)

    # Attach scores and sort descending
    scored = sorted(zip(scores, documents), key=lambda x: x[0], reverse=True)

    return [doc for _, doc in scored[:k]]


def reranked_baseline_retrieve(query: str, k: int = 5, candidates: int = 20) -> list[Document]:
    """
    Baseline retrieval + cross-encoder reranking.

    Fetches `candidates` chunks from ChromaDB (cheap, fast), then
    reranks them with the cross-encoder to pick the best `k`.

    Why candidates=20? It's a sweet spot:
    - Too few (e.g., 5): reranker can't improve much, just reshuffles
    - Too many (e.g., 100): reranker gets slow, diminishing returns
    - 20 gives the reranker enough variety while staying under 1 second
    """
    candidates_docs = baseline_retrieve(query, k=candidates)
    return rerank(query, candidates_docs, k=k)


def reranked_contextual_retrieve(query: str, k: int = 5, candidates: int = 20) -> list[Document]:
    """
    Contextual retrieval + cross-encoder reranking.

    Same pattern: fetch candidates from the contextual collection,
    then rerank. This combines both improvements:
    - Contextual embeddings for better recall (finding the right chunks)
    - Cross-encoder for better precision (ranking them correctly)
    """
    candidates_docs = contextual_retrieve(query, k=candidates)
    return rerank(query, candidates_docs, k=k)
