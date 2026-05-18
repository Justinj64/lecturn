"""
Script that runs ingestion:
1. Loads all PDFs and markdown files from corpus/
2. Splits them into chunks
3. Stores chunks in ChromaDB for retrieval
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.store import VectorStore
from ingest import load_corpus, CORPUS_DIR
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Verify API key is available
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    print("ERROR: OPENAI_API_KEY not set in environment!")
    sys.exit(1)
print(f"API key found: {api_key[:8]}...{api_key[-4:]}")



# Step 1: Load documents from corpus/
print("Loading corpus...")
docs = load_corpus()
num_files = sum(1 for f in CORPUS_DIR.rglob("*") if f.suffix in (".pdf", ".md"))
print(f"Loaded {len(docs)} documents from {num_files} files")

# Step 2: Split into chunks
print("Splitting into chunks...")
text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
all_splits = text_splitter.split_documents(docs)
print(f"Split into {len(all_splits)} chunks")

# Step 3: Store in ChromaDB (embeds automatically via OpenAI)
print("Storing in ChromaDB (embedding via OpenAI)...")
store = VectorStore()
store.reset()  # start fresh each time we re-ingest

batch_size = 50
for i in range(0, len(all_splits), batch_size):
    batch = all_splits[i:i + batch_size]
    store.add_documents(batch)
    print(f"  Stored {min(i + batch_size, len(all_splits))}/{len(all_splits)} chunks")

print(f"\nDone! {num_files} files, {len(docs)} pages/documents, {len(all_splits)} chunks")
print(f"Total in ChromaDB: {store.count()} chunks")