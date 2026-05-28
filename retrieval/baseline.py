from retrieval.store import VectorStore
from langchain_core.documents import Document


def baseline_retrieve(query: str, k: int = 5) -> list[Document]:
    """
        Retrieve top-k chunks from the baseline (non-contextual) ChromaDB collection.
    """
    return VectorStore().query(query, k=k)
