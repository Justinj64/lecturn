"""
Deterministic eval checks — fast, no LLM calls.

These checks validate the STRUCTURE of Lecturn's output, not whether
it's semantically correct. They run in milliseconds and catch obvious
failures: broken JSON, missing fields, malformed citations, duplicate
sources.

Think of these as the "unit tests" of eval — they don't prove the output
is good, but they prove it's not obviously broken. Run these first,
before spending money on LLM-as-judge checks.
"""

import json
import re
from collections import Counter

# Citation format Lecturn is expected to use: [source: <name>]
_CITATION_RE = re.compile(r"\[source:\s*.+?\]", re.IGNORECASE)
_SOURCE_EXTRACT_RE = re.compile(r"\[source:\s*(.+?)\]", re.IGNORECASE)

# Per-mode schemas: required top-level keys for each output mode.
# Run has_required_fields against the parsed output dict using these.
MODE_SCHEMAS: dict[str, dict] = {
    "comparison":  {"query": None, "similarities": None, "differences": None, "sources": None},
    "lit-review":  {"query": None, "summary": None, "sources": None},
    "notes":       {"query": None, "key_points": None, "sources": None},
    "default":     {"query": None, "answer": None, "sources": None},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Minimum character length for a string value to be considered a
# content-bearing field (answer, summary, key_points, etc.) rather than
# metadata (mode, source names, query, etc.).
_CONTENT_MIN_LEN = 60

# Top-level keys that are metadata, not claims — skip citation checks on these.
_METADATA_KEYS = {"query", "mode", "sources"}


def _extract_content_strings(output: str) -> list[str]:
    """
    Extract string values from JSON output that are long enough to be
    content-bearing (i.e., contain actual claims that need citations).

    Short strings like "default", "Lewis 2020", or a field name are
    excluded. Only strings longer than _CONTENT_MIN_LEN are returned.
    Keys in _METADATA_KEYS (query, mode, sources) are skipped entirely
    — they are structural metadata, not claims.

    Falls back to [output] if the string is not valid JSON and is long
    enough to be a content string.
    """
    def _collect(value: object, parts: list[str], key: str | None = None) -> None:
        if key in _METADATA_KEYS:
            return
        if isinstance(value, str) and len(value) > _CONTENT_MIN_LEN:
            parts.append(value)
        elif isinstance(value, dict):
            for k, v in value.items():
                _collect(v, parts, key=k)
        elif isinstance(value, list):
            for item in value:
                _collect(item, parts, key=key)

    try:
        parsed = json.loads(output)
        parts: list[str] = []
        _collect(parsed, parts, key=None)
        return parts
    except (json.JSONDecodeError, TypeError):
        return [output] if len(output) > _CONTENT_MIN_LEN else []


# ---------------------------------------------------------------------------
# Public checks
# ---------------------------------------------------------------------------

def is_valid_json(output: str) -> bool:
    """
    Check if the output is valid JSON.

    Why: Lecturn produces structured output. If the JSON is broken,
    nothing downstream can parse it — the response is useless regardless
    of how good the content is.

    Examples:
    >>> assert is_valid_json('{"answer": "ok", "sources": []}') is True
    >>> assert is_valid_json('{"answer": "ok", "sources": [}') is False   # syntax error
    >>> assert is_valid_json("not json at all") is False
    """
    try:
        json.loads(output)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def has_required_fields(output: dict, schema: dict) -> tuple[bool, list[str]]:
    """
    Check if the output dict contains all required fields from the schema.

    Returns (passed, missing_fields).

    Why: Each output mode (comparison, lit-review, notes) has required
    sections. If a section is missing, the output is incomplete even if
    the content that IS there is correct.

    The schema dict acts as a contract — its keys are the required field
    names. Values are ignored (use None as a placeholder).

    Examples:
    >>> ok, missing = has_required_fields(
    ...     {"query": "q", "answer": "a", "sources": []},
    ...     {"query": None, "answer": None, "sources": None},
    ... )
    >>> assert ok is True and missing == []

    >>> ok, missing = has_required_fields(
    ...     {"query": "q", "sources": []},           # "answer" is absent
    ...     {"query": None, "answer": None, "sources": None},
    ... )
    >>> assert ok is False and missing == ["answer"]
    """
    missing = [field for field in schema if field not in output]
    return (len(missing) == 0, missing)


def citation_format_valid(output: str) -> tuple[bool, list[str]]:
    """
    Check that every claim has a citation in the expected format.

    Returns (passed, uncited_claims).

    Why: Lecturn's value proposition is cited, traceable answers. An
    uncited claim is a potential hallucination — the user can't verify it.
    This check ensures the FORMAT is right (e.g., [source: X]), not
    whether the citation is actually correct (that's the judge's job).

    Strategy: split each content string on citation markers. Citations
    follow the claim they support ("claim. [source: X]"), so only the
    tail (text after the last citation) can be an uncited claim. If there
    are NO citations at all in a long content string, the whole string is
    flagged.

    Examples:
    >>> passed, uncited = citation_format_valid(
    ...     '{"answer": "RAG reduces hallucinations in production systems. [source: Lewis 2020]"}'
    ... )
    >>> assert passed is True and uncited == []

    >>> passed, uncited = citation_format_valid(
    ...     '{"answer": "RAG reduces hallucinations in many production systems."}'
    ... )
    >>> assert passed is False and len(uncited) == 1
    """
    content_strings = _extract_content_strings(output)
    uncited: list[str] = []
    for content in content_strings:
        if not _CITATION_RE.search(content):
            # No citations at all — the whole content string is uncited.
            preview = content[:80] + ("..." if len(content) > 80 else "")
            uncited.append(preview)
        else:
            # Split on citation markers. Citations follow their claims, so
            # segments 0..n-2 each have a citation immediately after them.
            # Only the tail (segment n-1) might be uncited.
            segments = _CITATION_RE.split(content)
            tail = segments[-1].strip()
            if len(tail) > 40:
                preview = tail[:80] + ("..." if len(tail) > 80 else "")
                uncited.append(preview)
    return (len(uncited) == 0, uncited)


def no_duplicate_sources(output: dict) -> tuple[bool, list[str]]:
    """
    Check that the output doesn't over-rely on a single source.

    Returns (passed, duplicated_sources).

    Why: If Lecturn cites the same source 10 times and ignores others,
    it's not doing retrieval — it's doing summarization of one document.
    This catches the diversity failure we saw in contextual retrieval
    (avg 1.4 unique sources vs baseline's 1.7).

    A source is flagged as duplicated if it appears in more than 3
    citation markers across the entire output.

    Examples:
    >>> ok, dups = no_duplicate_sources({
    ...     "answer": (
    ...         "Claim one. [source: Weng 2023] "
    ...         "Claim two. [source: Anthropic 2024] "
    ...         "Claim three. [source: Weng 2023]"
    ...     )
    ... })
    >>> assert ok is True and dups == []   # each source cited <= 3 times

    >>> ok, dups = no_duplicate_sources({
    ...     "answer": (
    ...         "[source: Weng 2023] [source: Weng 2023] [source: Weng 2023] "
    ...         "[source: Weng 2023]"  # 4 times — over the threshold
    ...     )
    ... })
    >>> assert ok is False and "Weng 2023" in dups
    """
    output_str = json.dumps(output)
    sources = _SOURCE_EXTRACT_RE.findall(output_str)
    counts = Counter(sources)
    duplicated = [src for src, count in counts.items() if count > 3]
    return (len(duplicated) == 0, duplicated)


def run_deterministic_checks(output: str, schema: dict | None = None) -> dict:
    """
    Run all deterministic checks on the output and return a report.

    Checks are intentionally ordered cheapest-first:
      1. JSON validity (prerequisite for all others)
      2. Required fields (catches incomplete outputs)
      3. Citation format (catches uncited claims)
      4. No duplicate sources (catches source concentration)

    If `schema` is not provided, the mode field inside the output is used
    to select the appropriate schema from MODE_SCHEMAS. Falls back to the
    "default" schema if mode is absent or unrecognised.

    Returns a dict like:
        {
            "json_valid": True,
            "required_fields": {"passed": True, "missing": []},
            "citation_format": {"passed": False, "uncited": ["claim 3"]},
            "no_duplicates": {"passed": True, "duplicated": []},
            "all_passed": False
        }
    """
    report: dict = {}

    # --- 1. JSON validity ---
    json_valid = is_valid_json(output)
    report["json_valid"] = json_valid

    parsed: dict | None = None
    if json_valid:
        parsed = json.loads(output)
        if not isinstance(parsed, dict):
            parsed = None  # top-level must be an object

    # --- 2. Required fields ---
    if parsed is not None:
        effective_schema = schema or MODE_SCHEMAS.get(
            parsed.get("mode", ""), MODE_SCHEMAS["default"]
        )
        passed, missing = has_required_fields(parsed, effective_schema)
        report["required_fields"] = {"passed": passed, "missing": missing}
    else:
        report["required_fields"] = {
            "passed": False,
            "missing": ["(output is not a valid JSON object)"],
        }

    # --- 3. Citation format ---
    citation_passed, uncited = citation_format_valid(output)
    report["citation_format"] = {"passed": citation_passed, "uncited": uncited}

    # --- 4. No duplicate sources ---
    if parsed is not None:
        dup_passed, duplicated = no_duplicate_sources(parsed)
        report["no_duplicates"] = {"passed": dup_passed, "duplicated": duplicated}
    else:
        report["no_duplicates"] = {
            "passed": False,
            "duplicated": ["(output is not a valid JSON object)"],
        }

    report["all_passed"] = all([
        report["json_valid"],
        report["required_fields"]["passed"],
        report["citation_format"]["passed"],
        report["no_duplicates"]["passed"],
    ])

    return report


# ---------------------------------------------------------------------------
# Self-tests — run with: python -m evals.deterministic
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import textwrap

    GOOD_OUTPUT = json.dumps({
        "query": "How does RAG reduce hallucinations?",
        "mode": "default",
        "answer": (
            "RAG grounds generation in retrieved documents, reducing fabrication. "
            "[source: Lewis 2020] "
            "Contextual prefixes further improve chunk relevance at retrieval time. "
            "[source: Anthropic 2024]"
        ),
        "sources": ["Lewis 2020", "Anthropic 2024"],
    })

    BAD_JSON = '{"answer": "broken json", "sources": [}'

    MISSING_FIELD_OUTPUT = json.dumps({
        "query": "How does RAG reduce hallucinations?",
        "mode": "default",
        # "answer" is intentionally absent
        "sources": ["Lewis 2020"],
    })

    UNCITED_OUTPUT = json.dumps({
        "query": "How does RAG reduce hallucinations?",
        "mode": "default",
        "answer": (
            "RAG grounds generation in retrieved documents and reduces fabrication "
            "by grounding outputs in retrieved evidence rather than parametric memory."
        ),
        "sources": [],
    })

    DUPLICATE_SOURCE_OUTPUT = json.dumps({
        "query": "How does RAG reduce hallucinations?",
        "mode": "default",
        "answer": (
            "Claim A. [source: Weng 2023] "
            "Claim B. [source: Weng 2023] "
            "Claim C. [source: Weng 2023] "
            "Claim D. [source: Weng 2023]"  # 4th cite of same source
        ),
        "sources": ["Weng 2023"],
    })

    # is_valid_json
    assert is_valid_json(GOOD_OUTPUT) is True
    assert is_valid_json(BAD_JSON) is False
    assert is_valid_json("not json at all") is False

    # has_required_fields
    schema = {"query": None, "answer": None, "sources": None}
    ok, missing = has_required_fields(json.loads(GOOD_OUTPUT), schema)
    assert ok is True and missing == []
    ok, missing = has_required_fields(json.loads(MISSING_FIELD_OUTPUT), schema)
    assert ok is False and "answer" in missing

    # citation_format_valid
    passed, uncited = citation_format_valid(GOOD_OUTPUT)
    assert passed is True, f"Expected no uncited claims, got: {uncited}"
    passed, uncited = citation_format_valid(UNCITED_OUTPUT)
    assert passed is False and len(uncited) >= 1

    # no_duplicate_sources
    ok, dups = no_duplicate_sources(json.loads(GOOD_OUTPUT))
    assert ok is True and dups == []
    ok, dups = no_duplicate_sources(json.loads(DUPLICATE_SOURCE_OUTPUT))
    assert ok is False and "Weng 2023" in dups

    # run_deterministic_checks — all passing
    report = run_deterministic_checks(GOOD_OUTPUT)
    assert report["all_passed"] is True, f"Expected all_passed, got: {report}"

    # run_deterministic_checks — broken JSON short-circuits
    report = run_deterministic_checks(BAD_JSON)
    assert report["json_valid"] is False
    assert report["all_passed"] is False

    print("All deterministic checks passed.")
    print()
    print("Sample report (good output):")
    print(json.dumps(run_deterministic_checks(GOOD_OUTPUT), indent=2))
    print()
    print("Sample report (broken output):")
    broken = json.dumps({
        "query": "q",
        "mode": "default",
        "answer": "An uncited claim that is definitely long enough to be flagged here.",
        "sources": [],
    })
    print(json.dumps(run_deterministic_checks(broken), indent=2))
