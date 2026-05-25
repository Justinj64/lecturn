"""
Compare retrieval methods on hand-crafted queries.

Runs each query through all available retrieval strategies and prints
a side-by-side comparison with hit rate, MRR, and source diversity.

Methods:
  - baseline:             raw chunk embeddings via ChromaDB
  - contextual:           context-prefixed chunk embeddings via ChromaDB
  - reranked_baseline:    baseline + cross-encoder reranking
  - reranked_contextual:  contextual + cross-encoder reranking

Usage:
    python scripts/compare_retrieval.py
    python scripts/compare_retrieval.py --k 3
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from retrieval.baseline import baseline_retrieve
from retrieval.contextual import contextual_retrieve
from retrieval.reranker import reranked_baseline_retrieve, reranked_contextual_retrieve

# Each method: (label, retrieve_function)
METHODS = [
    ("baseline", baseline_retrieve),
    ("contextual", contextual_retrieve),
    ("reranked_baseline", reranked_baseline_retrieve),
    ("reranked_contextual", reranked_contextual_retrieve),
]

K = 5  # top-K results to retrieve
TOP_N = 3  # check if expected source appears in top-N


def load_queries():
    queries_path = Path(__file__).resolve().parent.parent / "evals" / "queries.yaml"
    with open(queries_path) as f:
        data = yaml.safe_load(f)
    return data["queries"]


def find_source_rank(expected_source, results):
    """Return 1-based rank of first result matching expected source, or None."""
    expected_lower = expected_source.lower()
    for i, doc in enumerate(results):
        title = doc.metadata.get("title", "").lower()
        if expected_lower in title or title in expected_lower:
            return i + 1
    return None


def source_in_results(expected_sources, results, n):
    """Check if any expected source title appears (substring match) in top-n results."""
    hits = []
    for expected in expected_sources:
        rank = find_source_rank(expected, results)
        found = rank is not None and rank <= n
        hits.append((expected, found, rank))
    return hits


def count_unique_sources(results):
    """Count distinct source titles in the results."""
    titles = set()
    for doc in results:
        title = doc.metadata.get("title", "")
        if title:
            titles.add(title)
    return len(titles)


def print_results(label, results, k):
    """Print retrieval results in a compact format."""
    for i, doc in enumerate(results[:k], 1):
        title = doc.metadata.get("title", "N/A")
        source_url = doc.metadata.get("source_url", "")
        snippet = doc.page_content[:120].replace("\n", " ")
        print(f"  {i}. [{title}] {snippet}...")
        if source_url:
            print(f"     {source_url}")


def main():
    # Parse --k flag
    args = sys.argv[1:]
    k = K
    if "--k" in args:
        idx = args.index("--k")
        k = int(args[idx + 1])

    queries = load_queries()
    num_methods = len(METHODS)
    print(f"Running {len(queries)} queries × {num_methods} methods (top-{k})\n")
    print("=" * 80)

    # Per-method accumulators
    method_labels = [label for label, _ in METHODS]
    wins = {label: 0 for label in method_labels}
    all_mrrs = {label: [] for label in method_labels}
    diversity_totals = {label: 0 for label in method_labels}

    for qi, q in enumerate(queries, 1):
        query = q["query"]
        expected = q["expected_sources"]

        print(f"\n[Query {qi}/{len(queries)}] {query}")
        print(f"  Expected sources: {', '.join(expected)}")
        print("-" * 70)

        # Run all methods, collect results
        method_results = {}
        method_hits = {}
        method_mrrs_q = {}

        for label, retrieve_fn in METHODS:
            results = retrieve_fn(query, k=k)
            method_results[label] = results

            hits = source_in_results(expected, results, TOP_N)
            method_hits[label] = hits

            # Compute MRR for this method on this query
            def mrr(hits):
                rr_sum = 0
                for _, _, rank in hits:
                    if rank is not None:
                        rr_sum += 1.0 / rank
                return rr_sum / len(hits) if hits else 0

            m = mrr(hits)
            method_mrrs_q[label] = m
            all_mrrs[label].append(m)

            # Diversity
            div = count_unique_sources(results[:k])
            diversity_totals[label] += div

            # Print results for this method
            hit_count = sum(1 for _, found, _ in hits if found)
            print(f"\n  {label.upper()} (top-{k}, {div} unique sources):")
            print_results(label, results, k)
            print(f"  → Hits in top-{TOP_N}: {hit_count}/{len(expected)}", end="")
            for src, found, rank in hits:
                rank_str = f"@{rank}" if rank else "miss"
                print(f"  {'✓' if found else '✗'} {src} ({rank_str})", end="")
            print(f"  MRR={m:.2f}")

        # Determine winner: highest hit count, then highest MRR
        hit_counts = {
            label: sum(1 for _, found, _ in method_hits[label] if found)
            for label in method_labels
        }
        best_hits = max(hit_counts.values())
        best_labels = [l for l in method_labels if hit_counts[l] == best_hits]

        if len(best_labels) > 1:
            # Break tie with MRR
            best_mrr = max(method_mrrs_q[l] for l in best_labels)
            best_labels = [l for l in best_labels if method_mrrs_q[l] >= best_mrr - 0.01]

        if len(best_labels) == num_methods:
            print(f"\n  >>> TIE (all equal)")
        elif len(best_labels) == 1:
            winner = best_labels[0]
            wins[winner] += 1
            print(f"\n  >>> {winner.upper()} WINS")
        else:
            # Multiple winners but not all — count as tie
            print(f"\n  >>> TIE ({', '.join(l.upper() for l in best_labels)})")

        print("=" * 80)

    # Summary scorecard
    print(f"\n{'=' * 80}")
    print(f"SCORECARD ({len(queries)} queries, checking top-{TOP_N} for expected sources)")
    print(f"{'=' * 80}")

    print(f"\n  Wins:")
    for label in method_labels:
        print(f"    {label:25s} {wins[label]}")

    print(f"\n  Mean Reciprocal Rank (higher = expected source ranked earlier):")
    for label in method_labels:
        avg = sum(all_mrrs[label]) / len(all_mrrs[label])
        print(f"    {label:25s} {avg:.3f}")

    print(f"\n  Source diversity (avg unique sources in top-{k}):")
    for label in method_labels:
        avg = diversity_totals[label] / len(queries)
        print(f"    {label:25s} {avg:.1f}")

    print()


if __name__ == "__main__":
    main()
