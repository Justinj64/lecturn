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


def is_valid_json(output: str) -> bool:
    """
    Check if the output is valid JSON.

    Why: Lecturn produces structured output. If the JSON is broken,
    nothing downstream can parse it — the response is useless regardless
    of how good the content is.
    """
    raise NotImplementedError("Day 10: implement JSON validation check")


def has_required_fields(output: dict, schema: dict) -> tuple[bool, list[str]]:
    """
    Check if the output dict contains all required fields from the schema.

    Returns (passed, missing_fields).

    Why: Each output mode (comparison, lit-review, notes) has required
    sections. If a section is missing, the output is incomplete even if
    the content that IS there is correct.
    """
    raise NotImplementedError("Day 10: implement required fields check")


def citation_format_valid(output: str) -> tuple[bool, list[str]]:
    """
    Check that every claim has a citation in the expected format.

    Returns (passed, uncited_claims).

    Why: Lecturn's value proposition is cited, traceable answers. An
    uncited claim is a potential hallucination — the user can't verify it.
    This check ensures the FORMAT is right (e.g., [source: X]), not
    whether the citation is actually correct (that's the judge's job).
    """
    raise NotImplementedError("Day 10: implement citation format check")


def no_duplicate_sources(output: dict) -> tuple[bool, list[str]]:
    """
    Check that the output doesn't over-rely on a single source.

    Returns (passed, duplicated_sources).

    Why: If Lecturn cites the same source 10 times and ignores others,
    it's not doing retrieval — it's doing summarization of one document.
    This catches the diversity failure we saw in contextual retrieval
    (avg 1.4 unique sources vs baseline's 1.7).
    """
    raise NotImplementedError("Day 10: implement duplicate source check")


def run_deterministic_checks(output: str) -> dict:
    """
    Run all deterministic checks on the output and return a report.

    Returns a dict like:
        {
            "json_valid": True,
            "required_fields": {"passed": True, "missing": []},
            "citation_format": {"passed": False, "uncited": ["claim 3"]},
            "no_duplicates": {"passed": True, "duplicated": []},
            "all_passed": False
        }
    """
    raise NotImplementedError("Day 10: implement deterministic check runner")
