import json

from config import get_client, MODEL
from agent.prompts import FAITHFULNESS_SYSTEM, COMPLETENESS_SYSTEM


def _call_judge(system: str, user: str) -> str:
    """
        Single judge LLM call returning raw text.
    """
    response = get_client().chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=512,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return response.choices[0].message.content


def _parse_score_response(raw: str) -> dict:
    """
        Strip markdown fences and parse the judge's JSON response; returns score=-1 on failure.
    """
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return {"score": -1, "reasoning": f"Failed to parse model response: {raw[:200]}"}


def judge_faithfulness(claim: str, retrieved_chunks: list[str]) -> dict:
    """
        Score a single claim 0-5 against retrieved chunks; 0 = contradicted, 5 = fully supported.
    """
    chunks_block = "\n\n".join(
        f"[Chunk {i+1}]\n{chunk}" for i, chunk in enumerate(retrieved_chunks)
    )
    user_message = f"CLAIM: {claim}\n\nCHUNKS:\n{chunks_block}"
    raw = _call_judge(FAITHFULNESS_SYSTEM, user_message)
    return _parse_score_response(raw)


def judge_completeness(output: str, expected_key_claims: list[str]) -> dict:
    """
        Score how completely the output covers a list of expected key claims (0-5).
    """
    claims_block = "\n".join(f"  - {c}" for c in expected_key_claims)
    user_message = f"OUTPUT:\n{output}\n\nEXPECTED CLAIMS:\n{claims_block}"
    raw = _call_judge(COMPLETENESS_SYSTEM, user_message)
    result = _parse_score_response(raw)
    # Ensure missing_claims key is always present for callers
    result.setdefault("missing_claims", [])
    return result

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
