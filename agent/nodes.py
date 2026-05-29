import json
import re

from agent.state import LecturnState
from agent.prompts import PARSE_SYSTEM, PLAN_SYSTEM, DRAFT_SYSTEM, REVISE_SYSTEM
from config import get_client, MODEL
from retrieval.contextual import contextual_retrieve
from evals.judge import judge_faithfulness
from production.observability import log_event, timed_node
from production.cache import get_cached, set_cached
from production.guardrails import validate_citations

_LOW_CONFIDENCE_THRESHOLD = 2  # claims scoring <= this go to the revise loop


def _llm(system: str, user: str, max_tokens: int = 1024) -> str:
    """
    Single LLM call returning raw text.

    Checks the disk cache first — on a hit the model is not called at all.
    On a miss the response is cached before returning.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    cached = get_cached(MODEL, messages, temperature=0, max_tokens=max_tokens)
    if cached is not None:
        log_event("llm.cache_hit")
        return cached

    response = get_client().chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=max_tokens,
        messages=messages,
    )
    text = response.choices[0].message.content
    set_cached(MODEL, messages, temperature=0, max_tokens=max_tokens, response=text)
    log_event("llm.cache_miss")
    return text


def _parse_json(raw: str, fallback):
    """
    Strip markdown fences from model output and parse JSON,
    returning fallback on failure.
    """
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError):
        return fallback


def parse_query(state: LecturnState) -> dict:
    """
    Classify the query into a mode (structured-notes / comparison / lit-review).
    """
    if state.get("mode"):
        return {}
    with timed_node("parse_query") as meta:
        raw = _llm(PARSE_SYSTEM, f"Query: {state['query']}", max_tokens=256)
        parsed = _parse_json(raw, {})
        mode = parsed.get("mode", "structured-notes")
        meta["mode"] = mode
    return {"mode": mode}


def plan_sections(state: LecturnState) -> dict:
    """
    Generate a section outline appropriate for the detected mode.
    """
    with timed_node("plan_sections") as meta:
        raw = _llm(PLAN_SYSTEM, f"Query: {state['query']}\nMode: {state['mode']}", max_tokens=256)
        plan = _parse_json(raw, ["Overview", "Key Claims", "Limitations"])
        if not isinstance(plan, list):
            plan = ["Overview", "Key Claims", "Limitations"]
        meta["sections"] = len(plan)
    return {"plan": plan}


def retrieve(state: LecturnState) -> dict:
    """
    Fetch top-10 contextual chunks from ChromaDB for the query.
    """
    with timed_node("retrieve") as meta:
        docs = contextual_retrieve(state["query"], k=10)
        chunks = [
            {
                "text":       doc.page_content,
                "source_url": doc.metadata.get("source_url", ""),
                "title":      doc.metadata.get("title", "Unknown"),
            }
            for doc in docs
        ]
        meta["chunks"] = len(chunks)
        meta["unique_sources"] = len({c["title"] for c in chunks})
    return {"retrieved_chunks": chunks}


def draft(state: LecturnState) -> dict:
    """
    Write a structured, cited draft following the section plan.
    """
    with timed_node("draft") as meta:
        chunks_block = "\n\n".join(
            f"[Chunk {i+1}: {c['title']}]\n{c['text']}"
            for i, c in enumerate(state["retrieved_chunks"])
        )
        sections_str = "\n".join(f"- {s}" for s in state["plan"])
        user_msg = (
            f"Query: {state['query']}\n\n"
            f"Section plan:\n{sections_str}\n\n"
            f"Retrieved chunks:\n{chunks_block}"
        )
        response = _llm(DRAFT_SYSTEM, user_msg, max_tokens=2048)
        meta["draft_chars"] = len(response)
    return {
        "draft": response,
        "citations_verified": False,
        "low_confidence_claims": [],
        "revision_count": 0,
    }


def _extract_cited_claims(draft: str) -> list[str]:
    """
    Return sentences from the draft that contain a [source: ...] citation.
    """
    sentences = []
    for line in draft.split("\n"):
        line = line.strip()
        if line:
            sentences.extend(re.split(r"(?<=[.!?])\s+", line))
    return [s for s in sentences if "[source:" in s.lower() and len(s) > 20]


def verify_citations(state: LecturnState) -> dict:
    """
    Score each cited claim against retrieved chunks and flag low-confidence ones.
    """
    with timed_node("verify_citations") as meta:
        chunk_texts = [c["text"] for c in state.get("retrieved_chunks", [])]
        claims = _extract_cited_claims(state.get("draft", ""))
        meta["claims_checked"] = len(claims)

        low_confidence = []
        for claim in claims:
            result = judge_faithfulness(claim, chunk_texts)
            score = result.get("score", -1)
            if score <= _LOW_CONFIDENCE_THRESHOLD:
                low_confidence.append({
                    "claim":     claim,
                    "score":     score,
                    "reasoning": result.get("reasoning", ""),
                })
                log_event("verify_citations.low_confidence", {
                    "score": score,
                    "claim_preview": claim[:80],
                })

        meta["low_confidence"] = len(low_confidence)
    return {"citations_verified": True, "low_confidence_claims": low_confidence}


def revise(state: LecturnState) -> dict:
    """
    Rewrite the draft to drop or soften claims that aren't well-supported.
    """
    low_conf = state.get("low_confidence_claims", [])
    if not low_conf:
        return {"revision_count": state.get("revision_count", 0) + 1}

    with timed_node("revise") as meta:
        problems = "\n\n".join(
            f"Claim: {c['claim']}\nScore: {c['score']}/5\nReason: {c['reasoning']}"
            for c in low_conf
        )
        user_msg = f"ORIGINAL DRAFT:\n{state.get('draft', '')}\n\nLOW-CONFIDENCE CLAIMS TO FIX:\n{problems}"
        revised = _llm(REVISE_SYSTEM, user_msg, max_tokens=2048)
        new_count = state.get("revision_count", 0) + 1
        meta["revision"] = new_count
        meta["draft_chars"] = len(revised)

    return {
        "draft": revised,
        "revision_count": new_count,
        "low_confidence_claims": [],
        "citations_verified": False,
    }


def format_output(state: LecturnState) -> dict:
    """
    Assemble the final output, appending warning blocks for any remaining
    low-confidence claims and any citations that didn't match a retrieved source.
    """
    with timed_node("format_output") as meta:
        draft = state.get("draft", "")
        low_conf = state.get("low_confidence_claims", [])
        chunks = state.get("retrieved_chunks", [])

        # Citation validation — flag names not found in retrieved titles
        citation_report = validate_citations(draft, chunks)
        meta["citations_valid"] = citation_report["pass"]
        meta["invalid_citations"] = len(citation_report["invalid"])
        if not citation_report["pass"]:
            log_event("format_output.invalid_citations", {
                "invalid": citation_report["invalid"],
            })

        # Low-confidence warning block
        warning = ""
        if low_conf:
            claim_list = "\n".join(f"  - {c['claim']}" for c in low_conf)
            warning += f"\n\n---\n⚠️  The following claims could not be fully verified:\n{claim_list}\n"

        # Hallucinated-citation warning block
        if citation_report["invalid"]:
            names = "\n".join(f"  - {n}" for n in citation_report["invalid"])
            warning += f"\n\n---\n⚠️  The following cited sources were not in the retrieved set:\n{names}\n"

        final = f"# {state['query']}\n\n{draft}{warning}"
        meta["output_chars"] = len(final)
        meta["unverified_claims"] = len(low_conf)
    return {"final_output": final}
