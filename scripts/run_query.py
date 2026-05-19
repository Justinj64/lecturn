"""
Takes a query string, prints top 5 chunks with sources.

Usage:
    python scripts/run_query.py "what is contextual retrieval"
    python scripts/run_query.py --method contextual "what is contextual retrieval"
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.baseline import baseline_retrieve
from retrieval.contextual import contextual_retrieve

# Parse --method flag (default: baseline)
method = "baseline"
args = sys.argv[1:]
if "--method" in args:
    idx = args.index("--method")
    method = args[idx + 1]
    args = args[:idx] + args[idx + 2:]

query = args[0] if args else "what is contextual retrieval"

retrieve_fn = contextual_retrieve if method == "contextual" else baseline_retrieve
results = retrieve_fn(query, k=5)

print(f"Query: {query}")
print(f"Method: {method}\n")
for i, doc in enumerate(results, 1):
    print(f"--- Result {i} ---")
    print(f"Title: {doc.metadata.get('title', 'N/A')}")
    print(f"Source: {doc.metadata.get('source_url', doc.metadata.get('source', 'N/A'))}")
    print(f"Text: {doc.page_content[:200]}...")
    print()
