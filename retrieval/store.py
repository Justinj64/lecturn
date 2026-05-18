"""
Thin wrapper around ChromaDB for embedding + storing + querying.

ChromaDB is a vector database — it stores text as numeric vectors (embeddings)
and lets you find similar text using cosine similarity.

Usage:
    store = VectorStore()
    store.add_documents(chunks)
    results = store.query("what is contextual retrieval", k=5)
"""
import chromadb
from langchain_core.documents import Document
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction


class VectorStore:
    def __init__(self, collection_name: str = "lecturn", persist_dir: str = "./chroma_db"):
        # PersistentClient saves data to disk so we don't re-embed on every run.
        # Data lives in ./chroma_db/ directory.
        self._client = chromadb.PersistentClient(path=persist_dir)

        # This function converts text → 1536-dimensional vector using OpenAI's API.
        # It reads OPENAI_API_KEY from the environment automatically.
        self._embedding_fn = OpenAIEmbeddingFunction(
            model_name="text-embedding-3-small",
        )

        # A collection is like a "table" — all our chunks live here.
        # get_or_create means: reuse existing data if it's already stored.
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embedding_fn,
        )

    def add_documents(self, documents: list[Document]) -> None:
        """
        Add a list of langchain Documents to the collection.

        ChromaDB automatically embeds the text when we call .add().
        We don't need to call the embedding function ourselves.
        """
        # Each document needs a unique ID for ChromaDB to track it
        ids = [f"doc_{i}" for i in range(len(documents))]
        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        # ChromaDB has a per-request size limit, so we batch in groups of 500
        batch_size = 500
        for i in range(0, len(documents), batch_size):
            self._collection.add(
                ids=ids[i:i + batch_size],
                documents=texts[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size],
            )

    def query(self, query_text: str, k: int = 5) -> list[Document]:
        """
        Query the collection and return top-k results as Documents.

        How it works:
        1. Embeds the query text using the same model
        2. Finds the k closest chunks by cosine similarity
        3. Returns them as Document objects with text + metadata
        """
        results = self._collection.query(query_texts=[query_text], n_results=k)

        # results["documents"][0] is the list of texts for our single query
        # results["metadatas"][0] is the matching metadata for each result
        documents = []
        for text, metadata in zip(results["documents"][0], results["metadatas"][0]):
            documents.append(Document(page_content=text, metadata=metadata))
        return documents

    def count(self) -> int:
        """Return the number of documents in the collection."""
        return self._collection.count()

    def reset(self) -> None:
        """Delete and recreate the collection. Useful during development."""
        self._client.delete_collection(self._collection.name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection.name,
            embedding_function=self._embedding_fn,
        )