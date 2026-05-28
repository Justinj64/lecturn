from typing import TypedDict, Optional


class LecturnState(TypedDict):
    query: str
    mode: str                        # "structured-notes" | "comparison" | "lit-review"
    plan: Optional[list[str]]
    retrieved_chunks: Optional[list[dict]]  # [{text, source_url, title}, ...]
    draft: Optional[str]
    citations_verified: bool
    low_confidence_claims: list[dict]       # [{claim, score, reasoning}, ...]
    revision_count: int                     # guards the verify→revise loop (max 2)
    final_output: Optional[str]
