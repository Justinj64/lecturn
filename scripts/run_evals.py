"""
End-to-end eval runner.

Runs every golden dataset example through the Lecturn pipeline:
  1. Retrieve top-5 chunks for the question (baseline retrieval)
  2. Generate a structured JSON answer from the chunks (naive RAG generation)
  3. Run deterministic checks on the output
  4. Run completeness judge against expected_key_claims from golden dataset
  5. Run faithfulness judge on each sentence in the answer

Prints a scorecard at the end:
  - Deterministic pass rate
  - Average faithfulness score
  - Average completeness score
  - Breakdown by mode (comparison / lit-review / notes)

No agent yet — that's Week 3. This is the baseline we'll beat.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from evals.deterministic import run_deterministic_checks
from evals.golden import GoldenExample, load_golden_dataset
from evals.judge import judge_completeness, judge_faithfulness
from retrieval.baseline import baseline_retrieve

# ---------------------------------------------------------------------------
# LLM client (same Gemini-via-OpenAI setup used elsewhere)
# ---------------------------------------------------------------------------

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_GENERATION_MODEL = "gemini-2.5-flash-lite"


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["GEMINI_API_KEY"],
        base_url=_GEMINI_BASE_URL,
    )


# ---------------------------------------------------------------------------
# Naive RAG generation
# ---------------------------------------------------------------------------
# No agent yet — we just: retrieve → stuff chunks into prompt → ask for JSON.
# This is intentionally simple so the evals measure the RETRIEVAL quality,
# not agent planning. The agent (Week 3) will replace this step.

_GENERATION_SYSTEM = """\
You are Lecturn, a research assistant that answers questions about AI/ML papers and blogs.

You will be given:
  - A QUESTION from the user
  - RETRIEVED PASSAGES from the corpus

Your job: answer the question using ONLY information from the retrieved passages.
Cite every factual claim with [source: <title>] immediately after the claim,
where <title> is the title of the source passage.

Respond ONLY with a valid JSON object. Do not include markdown or code fences.
Use this exact structure based on the mode:

For mode=comparison:
{
  "query": "<question>",
  "mode": "comparison",
  "similarities": "<paragraph>",
  "differences": "<paragraph>",
  "sources": ["<title 1>", "<title 2>"]
}

For mode=lit-review:
{
  "query": "<question>",
  "mode": "lit-review",
  "summary": "<multi-paragraph synthesis>",
  "sources": ["<title 1>", "<title 2>"]
}

For mode=notes:
{
  "query": "<question>",
  "mode": "notes",
  "key_points": "<bullet-style summary>",
  "sources": ["<title 1>"]
}
"""


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
    client = _get_client()
    response = client.chat.completions.create(
        model=_GENERATION_MODEL,
        temperature=0,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": _GENERATION_SYSTEM},
            {"role": "user",   "content": user_message},
        ],
    )
    return response.choices[0].message.content


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dataset = load_golden_dataset()
    print(f"Running evals on {len(dataset)} golden examples...\n")

    results = []
    for i, example in enumerate(dataset, 1):
        print(f"[{i}/{len(dataset)}]", end=" ")
        result = evaluate_example(example)
        results.append(result)

    print_scorecard(results)

    # Optionally save raw results to disk for Day 14 writeup
    output_path = Path(__file__).parent.parent / "evals" / "last_run_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nRaw results saved to {output_path.relative_to(Path(__file__).parent.parent)}")
