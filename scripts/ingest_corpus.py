"""
Script that runs ingestion:
1. Loads all PDFs and markdown files from corpus/
2. Splits them into chunks
3. Stores chunks in ChromaDB for retrieval
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.store import VectorStore
from ingest import load_corpus, CORPUS_DIR
from langchain_text_splitters import RecursiveCharacterTextSplitter



# Step 1: Load documents from corpus/
docs = load_corpus()
num_files = sum(1 for f in CORPUS_DIR.rglob("*") if f.suffix in (".pdf", ".md"))

# Step 2: Split into chunks
text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
all_splits = text_splitter.split_documents(docs)

# Step 3: Store in ChromaDB (embeds automatically via OpenAI)
store = VectorStore()
store.reset()  # start fresh each time we re-ingest
store.add_documents(all_splits)

print(f"{num_files} files, {len(docs)} pages/documents, {len(all_splits)} chunks")
print(f"Stored {store.count()} chunks in ChromaDB")