"""
End-to-end eval runner.

Runs every golden dataset example through TWO pipelines and compares:

  NAIVE RAG (Week 2 baseline):
    retrieve (baseline) → one-shot generate → score

  AGENT (Week 3):
    LangGraph agent (parse → plan → retrieve → draft → verify → revise → format) → score

Scorecard shows both side-by-side so you can see what the agent buys you.

Key difference in what we can measure:
  - Naive RAG output is JSON   → we can run all deterministic checks
  - Agent output is plain text → we check citation format + completeness only
    (the agent already ran faithfulness internally via verify_citations)
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_client, MODEL
from evals.deterministic import run_deterministic_checks
from evals.golden import GoldenExample, load_golden_dataset
from evals.judge import judge_completeness, judge_faithfulness
from retrieval.baseline import baseline_retrieve
from agent.graph import lecturn_graph
from agent.prompts import GENERATION_SYSTEM

# ---------------------------------------------------------------------------
# Naive RAG generation
# ---------------------------------------------------------------------------
# No agent yet — we just: retrieve → stuff chunks into prompt → ask for JSON.
# This is intentionally simple so the evals measure the RETRIEVAL quality,
# not agent planning. The agent (Week 3) will replace this step.


def generate_answer(question: str, mode: str, chunks) -> str:
    """
        Naive RAG generation: stuff retrieved chunks into a prompt and ask for
        a structured JSON answer.

        Returns the raw JSON string from the model. Deterministic checks will
        validate whether it's actually valid JSON with the right fields.
    """
    passages = "\n\n".join(
        f"[Source: {c.metadata.get('title', 'Unknown')}]\n{c.page_content}"
        for c in chunks
    )
    user_message = (
        f"QUESTION: {question}\n"
        f"MODE: {mode}\n\n"
        f"RETRIEVED PASSAGES:\n{passages}"
    )
    client = get_client()
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": GENERATION_SYSTEM},
            {"role": "user",   "content": user_message},
        ],
    )
    raw = response.choices[0].message.content.strip()
    # Model sometimes wraps JSON in ```json fences despite instructions — strip them.
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------
# We run faithfulness per-claim, not per-output. We need to split the
# answer text into individual claims.
# Strategy: treat each sentence in the output's content fields as a claim.
# Short sentences and headings are skipped.

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MIN_CLAIM_LEN = 40     # characters; shorter strings are structural, not claims
_CITATION_STRIP_RE = re.compile(r"\[source:[^\]]+\]", re.IGNORECASE)


def extract_claims(output_str: str) -> list[str]:
    """
        Extract individual claim sentences from the generated output.

        Parses the JSON output, collects content-bearing string fields,
        splits on sentence boundaries, strips citation tags, and returns
        sentences long enough to be factual claims.
    """
    def _collect(value, parts):
        if isinstance(value, str) and len(value) > _MIN_CLAIM_LEN:
            parts.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                _collect(v, parts)
        elif isinstance(value, list):
            for item in value:
                _collect(item, parts)

    try:
        parsed = json.loads(output_str)
    except json.JSONDecodeError:
        # If JSON is broken, the deterministic check will catch it.
        # Return empty — no point running faithfulness on unparseable output.
        return []

    content_strings: list[str] = []
    _collect(parsed, content_strings)

    claims: list[str] = []
    for text in content_strings:
        for sentence in _SENTENCE_RE.split(text):
            bare = _CITATION_STRIP_RE.sub("", sentence).strip()
            if len(bare) >= _MIN_CLAIM_LEN:
                claims.append(bare)
    return claims


# ---------------------------------------------------------------------------
# Per-example evaluation
# ---------------------------------------------------------------------------

def evaluate_example(example: GoldenExample) -> dict:
    """
        Run the full eval pipeline on one golden example.

        Returns a result dict with all scores and intermediate data.
    """
    print(f"  [{example.mode}] {example.question[:70]}...")

    # 1. Retrieve
    chunks = baseline_retrieve(example.question, k=5)
    chunk_texts = [c.page_content for c in chunks]

    # 2. Generate
    output_str = generate_answer(example.question, example.mode, chunks)

    # 3. Deterministic checks
    det_report = run_deterministic_checks(output_str)

    # 4. Completeness (one judge call per example)
    completeness = judge_completeness(output_str, example.expected_key_claims)

    # 5. Faithfulness (one judge call per claim)
    claims = extract_claims(output_str)
    faithfulness_scores = []
    for claim in claims:
        result = judge_faithfulness(claim, chunk_texts)
        faithfulness_scores.append(result.get("score", -1))

    avg_faithfulness = (
        sum(faithfulness_scores) / len(faithfulness_scores)
        if faithfulness_scores else None
    )

    return {
        "question":          example.question,
        "mode":              example.mode,
        "output":            output_str,
        "deterministic":     det_report,
        "completeness":      completeness,
        "faithfulness_scores": faithfulness_scores,
        "avg_faithfulness":  avg_faithfulness,
        "n_claims":          len(claims),
    }


# ---------------------------------------------------------------------------
# Agent evaluation
# ---------------------------------------------------------------------------
# The agent outputs plain markdown, not JSON, so we can't run the JSON-based
# deterministic checks. We check:
#   - Citation format: does the output have [source: ...] on claims?
#   - Completeness: does it cover the expected key claims? (LLM judge)
#
# For faithfulness: the agent already ran verify_citations internally.
# We record revision_count as evidence — if it's > 0, the agent found and
# fixed problems. That's a quality signal naive RAG can never show.
# ---------------------------------------------------------------------------

import re as _re
_CITATION_RE_PLAIN = _re.compile(r"\[source:\s*.+?\]", _re.IGNORECASE)


def _citation_format_valid_plain(text: str) -> bool:
    """Check that the plain-text output contains at least some [source: ...] tags."""
    return bool(_CITATION_RE_PLAIN.search(text))


def evaluate_example_agent(example: GoldenExample) -> dict:
    """
        Run the agent pipeline on one golden example and score it.

        Uses lecturn_graph.invoke() — the full LangGraph state machine.
    """
    print(f"  [agent/{example.mode}] {example.question[:60]}...")

    initial_state = {
        "query":                example.question,
        "mode":                 "",   # let parse_query detect it
        "plan":                 None,
        "retrieved_chunks":     None,
        "draft":                None,
        "citations_verified":   False,
        "low_confidence_claims": [],
        "revision_count":       0,
        "final_output":         None,
    }

    final_state = lecturn_graph.invoke(initial_state)
    output_text = final_state.get("final_output", "")

    # Citation format check on plain text
    has_citations = _citation_format_valid_plain(output_text)

    # Completeness judge
    completeness = judge_completeness(output_text, example.expected_key_claims)

    return {
        "question":        example.question,
        "mode":            example.mode,
        "output":          output_text,
        "has_citations":   has_citations,
        "completeness":    completeness,
        "revision_count":  final_state.get("revision_count", 0),
        "low_conf_remaining": len(final_state.get("low_confidence_claims", [])),
    }


# ---------------------------------------------------------------------------
# Scorecard printer
# ---------------------------------------------------------------------------

def print_scorecard(results: list[dict]) -> None:
    total = len(results)

    # Deterministic pass rate
    det_passed = sum(1 for r in results if r["deterministic"]["all_passed"])
    det_rate = det_passed / total * 100

    # Average faithfulness (skip examples where no claims were extracted)
    faith_vals = [r["avg_faithfulness"] for r in results if r["avg_faithfulness"] is not None]
    avg_faith = sum(faith_vals) / len(faith_vals) if faith_vals else 0

    # Average completeness
    comp_vals = [r["completeness"]["score"] for r in results if r["completeness"]["score"] >= 0]
    avg_comp = sum(comp_vals) / len(comp_vals) if comp_vals else 0

    # Per-mode breakdown
    modes: dict[str, dict] = {}
    for r in results:
        m = r["mode"]
        if m not in modes:
            modes[m] = {"count": 0, "faith": [], "comp": []}
        modes[m]["count"] += 1
        if r["avg_faithfulness"] is not None:
            modes[m]["faith"].append(r["avg_faithfulness"])
        if r["completeness"]["score"] >= 0:
            modes[m]["comp"].append(r["completeness"]["score"])

    print()
    print("=" * 60)
    print("LECTURN EVAL SCORECARD")
    print("=" * 60)
    print(f"Examples evaluated :  {total}")
    print(f"Deterministic pass :  {det_passed}/{total}  ({det_rate:.0f}%)")
    print(f"Avg faithfulness   :  {avg_faith:.2f} / 5")
    print(f"Avg completeness   :  {avg_comp:.2f} / 5")
    print()
    print("By mode:")
    for mode, data in sorted(modes.items()):
        mf = sum(data["faith"]) / len(data["faith"]) if data["faith"] else 0
        mc = sum(data["comp"])  / len(data["comp"])  if data["comp"]  else 0
        print(f"  {mode:<12}  n={data['count']}  faith={mf:.2f}  comp={mc:.2f}")

    # Highlight failures
    failures = [r for r in results if not r["deterministic"]["all_passed"]]
    if failures:
        print()
        print(f"Deterministic failures ({len(failures)}):")
        for r in failures:
            det = r["deterministic"]
            issues = []
            if not det["json_valid"]:
                issues.append("invalid JSON")
            if not det["required_fields"]["passed"]:
                issues.append(f"missing fields: {det['required_fields']['missing']}")
            if not det["citation_format"]["passed"]:
                issues.append(f"{len(det['citation_format']['uncited'])} uncited claim(s)")
            if not det["no_duplicates"]["passed"]:
                issues.append(f"duplicate sources: {det['no_duplicates']['duplicated']}")
            print(f"  [{r['mode']}] {r['question'][:55]}...")
            print(f"    issues: {', '.join(issues)}")

    # Lowest completeness examples
    low_comp = sorted(
        [r for r in results if r["completeness"]["score"] >= 0],
        key=lambda r: r["completeness"]["score"]
    )[:3]
    if low_comp:
        print()
        print("Lowest completeness (top 3 to investigate):")
        for r in low_comp:
            c = r["completeness"]
            print(f"  [{r['mode']}] score={c['score']}/5  {r['question'][:55]}...")
            print(f"    reasoning: {c['reasoning'][:100]}")
            if c.get("missing_claims"):
                print(f"    missing:   {c['missing_claims'][0][:80]}")

    print("=" * 60)


def _print_agent_scorecard(results: list[dict]) -> None:
    total = len(results)
    citation_ok = sum(1 for r in results if r["has_citations"])
    comp_vals = [r["completeness"]["score"] for r in results if r["completeness"]["score"] >= 0]
    avg_comp = sum(comp_vals) / len(comp_vals) if comp_vals else 0
    revised = sum(1 for r in results if r["revision_count"] > 0)

    print()
    print("=" * 60)
    print("AGENT SCORECARD")
    print("=" * 60)
    print(f"Examples evaluated :  {total}")
    print(f"Citation format ok :  {citation_ok}/{total}  ({citation_ok/total*100:.0f}%)")
    print(f"Avg completeness   :  {avg_comp:.2f} / 5")
    print(f"Revision loop fired:  {revised}/{total} examples")
    print()
    print("By mode:")
    modes: dict = {}
    for r in results:
        m = r["mode"]
        if m not in modes:
            modes[m] = {"count": 0, "comp": [], "revised": 0}
        modes[m]["count"] += 1
        if r["completeness"]["score"] >= 0:
            modes[m]["comp"].append(r["completeness"]["score"])
        if r["revision_count"] > 0:
            modes[m]["revised"] += 1
    for mode, data in sorted(modes.items()):
        mc = sum(data["comp"]) / len(data["comp"]) if data["comp"] else 0
        print(f"  {mode:<12}  n={data['count']}  comp={mc:.2f}  revised={data['revised']}")
    print("=" * 60)


def _print_comparison(naive: list[dict], agent: list[dict]) -> None:
    """Print a side-by-side summary of the two pipelines."""
    def avg_comp(results, key="completeness"):
        vals = [r[key]["score"] for r in results if r[key]["score"] >= 0]
        return sum(vals) / len(vals) if vals else 0

    naive_comp  = avg_comp(naive)
    agent_comp  = avg_comp(agent)
    naive_faith = sum(r["avg_faithfulness"] for r in naive if r["avg_faithfulness"]) / max(1, sum(1 for r in naive if r["avg_faithfulness"]))
    naive_det   = sum(1 for r in naive if r["deterministic"]["all_passed"]) / len(naive) * 100
    agent_cit   = sum(1 for r in agent if r["has_citations"]) / len(agent) * 100

    print()
    print("=" * 60)
    print("COMPARISON: NAIVE RAG vs AGENT")
    print("=" * 60)
    print(f"{'Metric':<30} {'Naive RAG':>10} {'Agent':>10}")
    print("-" * 60)
    print(f"{'Avg completeness':<30} {naive_comp:>10.2f} {agent_comp:>10.2f}")
    print(f"{'Avg faithfulness':<30} {naive_faith:>10.2f} {'(internal)':>10}")
    print(f"{'Citation format ok':<30} {naive_det:>9.0f}% {agent_cit:>9.0f}%")
    revised = sum(1 for r in agent if r["revision_count"] > 0)
    print(f"{'Revision loop fired':<30} {'N/A':>10} {revised:>9}/{len(agent)}")
    delta = agent_comp - naive_comp
    print()
    print(f"Completeness delta: {delta:+.2f}  ({'agent better' if delta > 0 else 'naive better' if delta < 0 else 'same'})")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pipeline",
        choices=["naive", "agent", "both"],
        default="agent",
        help="Which pipeline to evaluate (default: both)",
    )
    args = parser.parse_args()

    dataset = load_golden_dataset()
    print(f"Loaded {len(dataset)} golden examples\n")

    naive_results = []
    agent_results = []

    # --- Naive RAG ---
    if args.pipeline in ("naive", "both"):
        print("=" * 60)
        print("PIPELINE 1: Naive RAG (baseline)")
        print("=" * 60)
        for i, example in enumerate(dataset, 1):
            print(f"[{i}/{len(dataset)}]", end=" ")
            naive_results.append(evaluate_example(example))
        print_scorecard(naive_results)

    # --- Agent ---
    if args.pipeline in ("agent", "both"):
        print("\n" + "=" * 60)
        print("PIPELINE 2: LangGraph Agent")
        print("=" * 60)
        for i, example in enumerate(dataset, 1):
            print(f"[{i}/{len(dataset)}]", end=" ")
            agent_results.append(evaluate_example_agent(example))
        _print_agent_scorecard(agent_results)

    # --- Side-by-side comparison ---
    if args.pipeline == "both":
        _print_comparison(naive_results, agent_results)

    # Save results
    output_path = Path(__file__).parent.parent / "evals" / "last_run_results.json"
    with open(output_path, "w") as f:
        json.dump(
            {"naive": naive_results, "agent": agent_results},
            f, indent=2, default=str,
        )
    print(f"\nRaw results saved → {output_path.relative_to(Path(__file__).parent.parent)}")
