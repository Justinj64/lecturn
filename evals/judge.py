"""
LLM-as-judge evaluation — uses an LLM to score output quality.

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

import json
import os

from openai import OpenAI

# Reuse the same Gemini-via-OpenAI setup used in contextual retrieval.
# This keeps us on one API key and one client pattern across the project.
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_JUDGE_MODEL = "gemini-2.5-flash-lite"


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["GEMINI_API_KEY"],
        base_url=_GEMINI_BASE_URL,
    )


def _call_judge(system: str, user: str) -> str:
    """
    Make a single LLM call and return the raw text response.

    All judge functions share this helper so the model and client
    configuration are in one place.
    """
    client = _get_client()
    response = client.chat.completions.create(
        model=_JUDGE_MODEL,
        temperature=0,          # zero temperature: we want deterministic scoring
        max_tokens=512,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return response.choices[0].message.content


def _parse_score_response(raw: str) -> dict:
    """
    Parse the model's JSON response into {"score": int, "reasoning": str}.

    Falls back gracefully if the model returns malformed JSON — sets score
    to -1 so the caller knows parsing failed rather than silently giving a
    wrong score.
    """
    try:
        # Strip markdown code fences if the model wraps the JSON in ```json
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return {"score": -1, "reasoning": f"Failed to parse model response: {raw[:200]}"}


# ---------------------------------------------------------------------------
# Public judge functions
# ---------------------------------------------------------------------------

_FAITHFULNESS_SYSTEM = """\
You are an evaluation assistant. Your job is to check whether a claim is
supported by a set of retrieved text chunks.

You will be given:
  - CLAIM: a single factual statement from an AI system's output
  - CHUNKS: the source passages that were retrieved to answer the query

Score the claim on this scale:
  5 = claim is directly and explicitly stated in the chunks
  4 = claim is strongly implied — a careful reader would draw this conclusion
  3 = claim is partially supported — some parts are backed, others need inference
  2 = claim is weakly related — the chunks touch the topic but don't support this claim
  1 = claim has minimal connection — only a loose thematic link
  0 = claim contradicts the chunks OR makes a statement the chunks have no basis for

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{"score": <integer 0-5>, "reasoning": "<one or two sentences explaining your score>"}

Examples:
Input:
  CLAIM: RAG retrieves documents at inference time rather than encoding knowledge at training time.
  CHUNKS: ["RAG augments language models with non-parametric memory — a retrieval system over a
  document corpus. The model queries this corpus at inference time to ground its generation."]
Output:
{"score": 5, "reasoning": "The chunk directly states that RAG queries the corpus at inference time, which is exactly what the claim asserts."}

Input:
  CLAIM: RAG was invented at Google Brain in 2019.
  CHUNKS: ["We present RAG, a general-purpose fine-tuning recipe for NLP tasks that require
  knowledge access. — Lewis et al., Facebook AI Research, 2020."]
Output:
{"score": 0, "reasoning": "The chunk contradicts the claim: RAG was published by Facebook AI Research, not Google Brain, and in 2020 not 2019."}
"""

_COMPLETENESS_SYSTEM = """\
You are an evaluation assistant. Your job is to check whether an AI system's
output covers a set of expected key claims.

You will be given:
  - OUTPUT: the full text of the AI system's response
  - EXPECTED CLAIMS: a list of specific facts or points the output should cover

Score the coverage on this scale:
  5 = all expected claims are addressed clearly and thoroughly
  4 = most claims are covered, minor omissions or vague treatment of 1-2 points
  3 = roughly half the claims are covered; notable gaps
  2 = significant claims are missing; the output is incomplete
  1 = the output only tangentially relates to the expected claims
  0 = the output completely misses the expected content

Also list which specific expected claims are absent or insufficiently addressed.

Respond ONLY with a JSON object in this exact format (no markdown, no extra text):
{"score": <integer 0-5>, "reasoning": "<one or two sentences>", "missing_claims": [<list of missing claim strings>]}

Example:
Input:
  OUTPUT: "RAG grounds generation in retrieved documents, reducing hallucination. [source: Lewis 2020]"
  EXPECTED CLAIMS: ["RAG retrieves at inference time", "RAG reduces hallucination",
                    "fine-tuning encodes knowledge at training time"]
Output:
{"score": 3, "reasoning": "The output covers retrieval at inference time and hallucination reduction, but says nothing about fine-tuning.", "missing_claims": ["fine-tuning encodes knowledge at training time"]}
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
    chunks_block = "\n\n".join(
        f"[Chunk {i+1}]\n{chunk}" for i, chunk in enumerate(retrieved_chunks)
    )
    user_message = f"CLAIM: {claim}\n\nCHUNKS:\n{chunks_block}"
    raw = _call_judge(_FAITHFULNESS_SYSTEM, user_message)
    return _parse_score_response(raw)


def judge_completeness(
    output: str,
    expected_key_claims: list[str],
) -> dict:
    """
    Use an LLM to check if the output covers the expected key claims.

    Args:
        output: Lecturn's full output text (or JSON-serialised output)
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
    claims_block = "\n".join(f"  - {c}" for c in expected_key_claims)
    user_message = f"OUTPUT:\n{output}\n\nEXPECTED CLAIMS:\n{claims_block}"
    raw = _call_judge(_COMPLETENESS_SYSTEM, user_message)
    result = _parse_score_response(raw)
    # Ensure missing_claims key is always present for callers
    result.setdefault("missing_claims", [])
    return result


# ---------------------------------------------------------------------------
# Smoke test — run with: python -m evals.judge
# Makes real API calls, costs a few tokens. Requires GEMINI_API_KEY set.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Faithfulness judge ===\n")

    print("Test 1: well-supported claim")
    result = judge_faithfulness(
        claim="RAG retrieves documents from an external corpus at inference time.",
        retrieved_chunks=[
            "Retrieval-Augmented Generation (RAG) augments language models with a "
            "non-parametric memory component — a retrieval system over a document corpus. "
            "At inference time, the model queries this corpus and conditions generation "
            "on the retrieved passages. (Lewis et al., 2020)"
        ],
    )
    print(f"  score: {result['score']}/5")
    print(f"  reasoning: {result['reasoning']}\n")

    print("Test 2: hallucinated claim (wrong institution)")
    result = judge_faithfulness(
        claim="RAG was developed at Google Brain.",
        retrieved_chunks=[
            "We introduce RAG, a general-purpose recipe combining parametric and "
            "non-parametric memory for language generation. "
            "— Lewis et al., Facebook AI Research, 2020."
        ],
    )
    print(f"  score: {result['score']}/5")
    print(f"  reasoning: {result['reasoning']}\n")

    print("=== Completeness judge ===\n")

    print("Test 3: output covers all expected claims")
    result = judge_completeness(
        output=(
            "RAG retrieves relevant documents at inference time and conditions generation "
            "on them, which reduces hallucination. [source: Lewis 2020] "
            "Unlike fine-tuning, RAG does not modify model weights — knowledge is stored "
            "in the retrieval index instead. [source: Gao 2023]"
        ),
        expected_key_claims=[
            "RAG retrieves at inference time",
            "RAG reduces hallucination",
            "fine-tuning updates model weights while RAG does not",
        ],
    )
    print(f"  score: {result['score']}/5")
    print(f"  reasoning: {result['reasoning']}")
    print(f"  missing_claims: {result['missing_claims']}\n")

    print("Test 4: output misses a key claim")
    result = judge_completeness(
        output="RAG retrieves documents to ground generation. [source: Lewis 2020]",
        expected_key_claims=[
            "RAG retrieves at inference time",
            "RAG reduces hallucination",
            "fine-tuning updates model weights while RAG does not",
        ],
    )
    print(f"  score: {result['score']}/5")
    print(f"  reasoning: {result['reasoning']}")
    print(f"  missing_claims: {result['missing_claims']}")


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
