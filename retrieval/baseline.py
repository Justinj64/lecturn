"""
Baseline retrieval: takes a query, returns top-K chunks from ChromaDB
ranked by cosine similarity against the query embedding.

This is the simplest retrieval strategy — embed the query,
find the closest chunks, return them.
"""
from retrieval.store import VectorStore
from langchain_core.documents import Document


def baseline_retrieve(query: str, k: int = 5) -> list[Document]:
    """
    Retrieve the top-k most similar chunks to the query.

    Uses the VectorStore (ChromaDB) which already has chunks
    embedded via scripts/ingest_corpus.py.
    """
    store = VectorStore()
    return store.query(query, k=k)
