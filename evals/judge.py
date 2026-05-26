"""
LLM-as-judge evaluation — uses Claude to score output quality.

These checks are SEMANTIC — they evaluate whether the content is correct,
not just whether the format is right. They cost money (one LLM call each)
and take seconds, so run them after deterministic checks pass.

Two judges:
  - Faithfulness: "Is this claim actually supported by the retrieved chunks?"
  - Completeness: "Does the output cover the key claims we expected?"

Each returns a score (0-5) and reasoning. The reasoning is critical —
it tells you WHY a score is low, which helps you debug the retrieval
or generation pipeline.

IMPORTANT CAVEAT: LLM-as-judge is itself unreliable. The judge can
miss hallucinations or flag correct claims. That's why we pair it with
deterministic checks and a golden dataset. No single eval is sufficient.
"""


def judge_faithfulness(
    claim: str,
    retrieved_chunks: list[str],
) -> dict:
    """
    Use an LLM to check if a claim is supported by the retrieved chunks.

    Args:
        claim: a single claim from Lecturn's output
        retrieved_chunks: the chunks that were retrieved for this query

    Returns:
        {"score": 0-5, "reasoning": str}

        Score guide:
          5 = claim is directly stated in the chunks
          4 = claim is strongly implied by the chunks
          3 = claim is partially supported, some inference needed
          2 = claim is weakly related to chunk content
          1 = claim has minimal connection to chunks
          0 = claim contradicts chunks or has no support at all

    Why this matters: this is Lecturn's hardest eval. A hallucinated
    claim that SOUNDS right but isn't in the sources is the worst
    failure mode — it erodes trust in the entire system.
    """
    raise NotImplementedError("Day 12: implement faithfulness judge")


def judge_completeness(
    output: str,
    expected_key_claims: list[str],
) -> dict:
    """
    Use an LLM to check if the output covers the expected key claims.

    Args:
        output: Lecturn's full output text
        expected_key_claims: claims we expect to see (from golden dataset)

    Returns:
        {"score": 0-5, "reasoning": str, "missing_claims": list[str]}

        Score guide:
          5 = all expected claims are covered thoroughly
          4 = most claims covered, minor omissions
          3 = about half the claims covered
          2 = significant claims missing
          1 = only tangentially related to expected claims
          0 = completely misses the expected content

    Why this matters: faithfulness checks that claims are TRUE,
    completeness checks that the RIGHT claims are PRESENT. An output
    can be perfectly faithful (everything it says is correct) but
    incomplete (it missed the most important points).
    """
    raise NotImplementedError("Day 12: implement completeness judge")


def run_judge(
    output: str,
    query: str,
    retrieved_chunks: list[str],
    expected_key_claims: list[str] | None = None,
) -> dict:
    """
    Run all LLM-as-judge checks on the output.

    Returns:
        {
            "faithfulness": {"score": 0-5, "reasoning": str},
            "completeness": {"score": 0-5, "reasoning": str, "missing_claims": [...]},
        }
    """
    raise NotImplementedError("Day 12: implement judge runner")
