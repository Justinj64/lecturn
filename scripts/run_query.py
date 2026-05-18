"""
Takes a query string, prints top 5 chunks with sources.

Usage:
    python scripts/run_query.py "what is contextual retrieval"
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.baseline import baseline_retrieve

query = sys.argv[1] if len(sys.argv) > 1 else "what is contextual retrieval"

results = baseline_retrieve(query, k=5)

print(f"Query: {query}\n")
for i, doc in enumerate(results, 1):
    print(f"--- Result {i} ---")
    print(f"Title: {doc.metadata.get('title', 'N/A')}")
    print(f"Source: {doc.metadata.get('source_url', doc.metadata.get('source', 'N/A'))}")
    print(f"Text: {doc.page_content[:200]}...")
    print()
