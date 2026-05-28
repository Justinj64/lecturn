import chromadb
from langchain_core.documents import Document


class VectorStore:
    def __init__(self, collection_name: str = "lecturn", persist_dir: str = "./chroma_db"):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(name=collection_name)

    def add_documents(self, documents: list[Document]) -> None:
        """
            Embed and store documents in the collection, batching in groups of 500.
        """
        offset = self._collection.count()
        ids = [f"doc_{offset + i}" for i in range(len(documents))]
        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        batch_size = 500
        for i in range(0, len(documents), batch_size):
            self._collection.add(
                ids=ids[i:i + batch_size],
                documents=texts[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size],
            )

    def query(self, query_text: str, k: int = 5) -> list[Document]:
        """
            Return the top-k most similar documents to query_text.
        """
        results = self._collection.query(query_texts=[query_text], n_results=k)
        documents = []
        for text, metadata in zip(results["documents"][0], results["metadatas"][0]):
            documents.append(Document(page_content=text, metadata=metadata))
        return documents

    def count(self) -> int:
        """
            Return the number of documents in the collection.
        """
        return self._collection.count()

    def reset(self) -> None:
        """
            Delete and recreate the collection. Useful during development.
        """
        self._client.delete_collection(self._collection.name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection.name,
        )