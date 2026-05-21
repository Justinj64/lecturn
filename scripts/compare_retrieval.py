"""
Compare baseline vs contextual retrieval on hand-crafted queries.

For each query in evals/queries.yaml:
  1. Run baseline retrieval (top-K)
  2. Run contextual retrieval (top-K)
  3. Check if expected sources appear in top-3
  4. Print side-by-side results and a summary scorecard

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
    print(f"Running {len(queries)} queries through baseline and contextual retrieval (top-{k})\n")
    print("=" * 80)

    baseline_wins = 0
    contextual_wins = 0
    ties = 0
    # Track per-query scores for summary
    all_baseline_ranks = []  # mean reciprocal rank per query
    all_contextual_ranks = []
    baseline_diversity_total = 0
    contextual_diversity_total = 0

    for qi, q in enumerate(queries, 1):
        query = q["query"]
        expected = q["expected_sources"]

        print(f"\n[Query {qi}/{len(queries)}] {query}")
        print(f"  Expected sources: {', '.join(expected)}")
        print("-" * 70)

        # Run both retrieval methods
        baseline_results = baseline_retrieve(query, k=k)
        contextual_results = contextual_retrieve(query, k=k)

        # Check hits in top-N (with rank info)
        baseline_hits = source_in_results(expected, baseline_results, TOP_N)
        contextual_hits = source_in_results(expected, contextual_results, TOP_N)

        baseline_hit_count = sum(1 for _, found, _ in baseline_hits if found)
        contextual_hit_count = sum(1 for _, found, _ in contextual_hits if found)

        # Compute mean reciprocal rank (MRR) for expected sources
        def mrr(hits):
            rr_sum = 0
            for _, _, rank in hits:
                if rank is not None:
                    rr_sum += 1.0 / rank
            return rr_sum / len(hits) if hits else 0

        baseline_mrr = mrr(baseline_hits)
        contextual_mrr = mrr(contextual_hits)
        all_baseline_ranks.append(baseline_mrr)
        all_contextual_ranks.append(contextual_mrr)

        # Source diversity
        baseline_div = count_unique_sources(baseline_results[:k])
        contextual_div = count_unique_sources(contextual_results[:k])
        baseline_diversity_total += baseline_div
        contextual_diversity_total += contextual_div

        # Print baseline results
        print(f"\n  BASELINE (top-{k}, {baseline_div} unique sources):")
        print_results("baseline", baseline_results, k)
        print(f"  → Hits in top-{TOP_N}: {baseline_hit_count}/{len(expected)}", end="")
        for src, found, rank in baseline_hits:
            rank_str = f"@{rank}" if rank else "miss"
            print(f"  {'✓' if found else '✗'} {src} ({rank_str})", end="")
        print(f"  MRR={baseline_mrr:.2f}")

        # Print contextual results
        print(f"\n  CONTEXTUAL (top-{k}, {contextual_div} unique sources):")
        print_results("contextual", contextual_results, k)
        print(f"  → Hits in top-{TOP_N}: {contextual_hit_count}/{len(expected)}", end="")
        for src, found, rank in contextual_hits:
            rank_str = f"@{rank}" if rank else "miss"
            print(f"  {'✓' if found else '✗'} {src} ({rank_str})", end="")
        print(f"  MRR={contextual_mrr:.2f}")

        # Determine winner: prefer higher hit count, break ties with MRR
        if contextual_hit_count > baseline_hit_count:
            contextual_wins += 1
            print(f"\n  >>> CONTEXTUAL WINS (more hits)")
        elif baseline_hit_count > contextual_hit_count:
            baseline_wins += 1
            print(f"\n  >>> BASELINE WINS (more hits)")
        elif contextual_mrr > baseline_mrr + 0.01:
            contextual_wins += 1
            print(f"\n  >>> CONTEXTUAL WINS (better rank)")
        elif baseline_mrr > contextual_mrr + 0.01:
            baseline_wins += 1
            print(f"\n  >>> BASELINE WINS (better rank)")
        else:
            ties += 1
            print(f"\n  >>> TIE")

        print("=" * 80)

    # Summary scorecard
    avg_baseline_mrr = sum(all_baseline_ranks) / len(all_baseline_ranks)
    avg_contextual_mrr = sum(all_contextual_ranks) / len(all_contextual_ranks)
    avg_baseline_div = baseline_diversity_total / len(queries)
    avg_contextual_div = contextual_diversity_total / len(queries)

    print(f"\n{'=' * 80}")
    print(f"SCORECARD ({len(queries)} queries, checking top-{TOP_N} for expected sources)")
    print(f"{'=' * 80}")
    print(f"  Contextual wins:  {contextual_wins}")
    print(f"  Baseline wins:    {baseline_wins}")
    print(f"  Ties:             {ties}")
    print()
    print(f"  Mean Reciprocal Rank (higher = expected source ranked earlier):")
    print(f"    Baseline MRR:    {avg_baseline_mrr:.3f}")
    print(f"    Contextual MRR:  {avg_contextual_mrr:.3f}")
    print()
    print(f"  Source diversity (avg unique sources in top-{k}):")
    print(f"    Baseline:        {avg_baseline_div:.1f}")
    print(f"    Contextual:      {avg_contextual_div:.1f}")
    print()

    if contextual_wins > baseline_wins:
        print(f"  → Contextual retrieval wins on {contextual_wins}/{len(queries)} queries.")
    elif baseline_wins > contextual_wins:
        print(f"  → Baseline retrieval wins on {baseline_wins}/{len(queries)} queries.")
    else:
        print(f"  → Both methods perform equally on hit count.")


if __name__ == "__main__":
    main()
