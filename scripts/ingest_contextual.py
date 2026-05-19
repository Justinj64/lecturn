"""
Ingest corpus with contextual retrieval: generates context prefixes
for each chunk using OpenAI, then stores contextualized chunks in
a separate ChromaDB collection.

This is the contextual counterpart to scripts/ingest_corpus.py.
The baseline script embeds raw chunks. This one embeds chunks with
context prefixes prepended, so the embeddings capture richer meaning.

Run this AFTER ingest_corpus.py (you need both collections to compare).

Usage:
    OPENAI_API_KEY=... python scripts/ingest_contextual.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.store import VectorStore
from ingest import load_corpus, CORPUS_DIR
from langchain_text_splitters import RecursiveCharacterTextSplitter
from retrieval.contextual import (
    build_full_documents,
    generate_context_prefixes,
    contextualize_chunks,
    CONTEXTUAL_COLLECTION,
)

# Verify API key
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("ERROR: GEMINI_API_KEY not set in environment!")
    print("Get one at https://aistudio.google.com/apikey")
    sys.exit(1)

# Step 1: Load documents from corpus/
print("Loading corpus...")
docs = load_corpus()
num_files = sum(1 for f in CORPUS_DIR.rglob("*") if f.suffix in (".pdf", ".md"))
print(f"Loaded {len(docs)} documents from {num_files} files")

# Step 2: Build full document text (needed for context generation)
# The LLM needs to see the WHOLE document to write a good context prefix.
# We reconstruct full docs by grouping the per-page Documents by source.
print("Building full document texts...")
full_documents = build_full_documents(docs)
print(f"Reconstructed {len(full_documents)} full documents")

# Step 3: Chunk (same params as baseline so comparison is fair)
print("Splitting into chunks...")
text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
chunks = text_splitter.split_documents(docs)
print(f"Split into {len(chunks)} chunks")

# Step 4: Generate context prefixes using OpenAI (cached to disk)
# This is the expensive step — one LLM call per chunk on first run.
# Subsequent runs load prefixes from .context_cache/ and skip the API calls.
print("Generating context prefixes...")
prefixes = generate_context_prefixes(chunks, full_documents)

# Step 5: Create contextualized chunks (prefix + original chunk)
print("Creating contextualized chunks...")
contextualized = contextualize_chunks(chunks, prefixes)

# Step 6: Store in a SEPARATE ChromaDB collection
# Using a separate collection ("lecturn_contextual" vs "lecturn") means
# baseline and contextual retrieval can coexist and be compared.
print(f"Storing in ChromaDB collection '{CONTEXTUAL_COLLECTION}'...")
store = VectorStore(collection_name=CONTEXTUAL_COLLECTION)
store.reset()  # start fresh

batch_size = 50
for i in range(0, len(contextualized), batch_size):
    batch = contextualized[i:i + batch_size]
    store.add_documents(batch)
    print(f"  Stored {min(i + batch_size, len(contextualized))}/{len(contextualized)} chunks")

print(f"\nDone! Contextual ingestion complete.")
print(f"  {num_files} files → {len(chunks)} chunks → {store.count()} contextualized embeddings")
print(f"  Context prefix cache: .context_cache/context_prefixes.json")
print(f"  ChromaDB collection: {CONTEXTUAL_COLLECTION}")
