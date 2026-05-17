"""
script that runs ingestion and prints "X documents ,Y chunks ingested"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingest import load_corpus, CORPUS_DIR

docs = load_corpus()

num_files = sum(1 for f in CORPUS_DIR.rglob("*") if f.suffix in (".pdf", ".md"))

text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
all_splits = text_splitter.split_documents(docs)

print(f"{num_files} files, {len(docs)} pages/documents, {len(all_splits)} chunks")