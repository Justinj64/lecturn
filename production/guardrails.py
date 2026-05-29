"""
Days 24-25 – Input and output guardrails.

Two independent checks:

  check_query(query)
      Scans the user's query for prompt injection patterns before the
      graph runs. Returns {"safe": bool, "reason": str | None}.

  validate_citations(draft, retrieved_chunks)
      After drafting, confirms every [source: X] citation maps to a
      title that was actually retrieved. Returns a report dict with
      valid/invalid lists and an overall pass flag.

Neither check requires an LLM or external dependencies.
"""

import re
from typing import Any

# ---------------------------------------------------------------------------
# Prompt injection guard
# ---------------------------------------------------------------------------

# Patterns that signal an attempt to override or hijack the system prompt.
# Kept deliberately narrow to avoid false positives on legitimate research
# queries (which naturally discuss LLMs, prompts, and instructions).
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+)?(previous|prior|above|system)\s+instructions?", "instruction override attempt"),
    (r"disregard\s+(all\s+)?(previous|prior|above|system)\s+instructions?", "instruction override attempt"),
    (r"forget\s+(everything|all|your)\s+(you\s+know|instructions?|previous)", "context wipe attempt"),
    (r"you\s+are\s+now\s+(?!a\s+research)", "role-switch attempt"),
    (r"act\s+as\s+(if\s+you\s+(are|were)|a\s+(?!research))", "role-switch attempt"),
    (r"pretend\s+(you\s+are|to\s+be)\s+(?!a\s+research)", "role-switch attempt"),
    (r"(print|reveal|show|repeat|output|return|display)\s+(your\s+)?(system\s+prompt|instructions?|prompt)", "prompt extraction attempt"),
    (r"\{\{.*?\}\}", "template injection"),
    (r"<\s*script", "script injection"),
]

_COMPILED = [(re.compile(pat, re.IGNORECASE), label) for pat, label in _INJECTION_PATTERNS]

# Queries longer than this are flagged — legitimate research questions
# rarely exceed this length; very long inputs often embed hidden instructions.
_MAX_QUERY_LEN = 1000


def check_query(query: str) -> dict[str, Any]:
    """
    Scan the user query for prompt injection patterns.

    Returns a dict:
        {"safe": True, "reason": None}              — query is clean
        {"safe": False, "reason": "<description>"}  — injection detected

    This is intentionally a fast, cheap pre-flight check. It runs before
    the graph so no tokens are spent on a malicious query.
    """
    if len(query) > _MAX_QUERY_LEN:
        return {
            "safe": False,
            "reason": f"query exceeds {_MAX_QUERY_LEN} characters (got {len(query)})",
        }

    for pattern, label in _COMPILED:
        if pattern.search(query):
            return {"safe": False, "reason": label}

    return {"safe": True, "reason": None}


# ---------------------------------------------------------------------------
# Citation validator
# ---------------------------------------------------------------------------

_CITATION_RE = re.compile(r"\[source:\s*(.+?)\]", re.IGNORECASE)


def _normalize(title: str) -> str:
    """
    Lowercase and strip whitespace for loose title matching.
    """
    return title.lower().strip()


def validate_citations(draft: str, retrieved_chunks: list[dict]) -> dict[str, Any]:
    """
    Check that every [source: X] citation in the draft refers to a title
    that was actually retrieved.

    Match strategy: a citation is considered valid if the cited name is a
    substring of any retrieved title, or any retrieved title is a substring
    of the cited name (after normalization). This handles cases where the
    model abbreviates a long title.

    Returns a dict:
        {
            "pass":    bool,
            "valid":   ["cited name", ...],   # names matched to a chunk
            "invalid": ["cited name", ...],   # names with no match
        }

    Wire this into format_output (or call it post-graph) to surface
    hallucinated citations before delivering the final answer.
    """
    cited_names = _CITATION_RE.findall(draft)
    if not cited_names:
        return {"pass": True, "valid": [], "invalid": []}

    normalized_titles = [_normalize(c["title"]) for c in retrieved_chunks]

    valid: list[str] = []
    invalid: list[str] = []

    for name in cited_names:
        norm_name = _normalize(name)
        matched = any(
            norm_name in title or title in norm_name
            for title in normalized_titles
        )
        (valid if matched else invalid).append(name)

    return {
        "pass":    len(invalid) == 0,
        "valid":   valid,
        "invalid": invalid,
    }
