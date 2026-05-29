"""
Run the Lecturn agent end-to-end on a single query.

Usage:
    python scripts/run_agent.py

Edit QUERY and MODE below to change what the agent runs on.

Observability:
  - Structured logs are always written to logs/lecturn.jsonl
  - If LANGFUSE_* env vars are set, the full run appears as a single
    trace in Langfuse with one generation per LLM call
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.graph import lecturn_graph
from production.observability import new_run, end_run
from production.guardrails import check_query

# ---------------------------------------------------------------------------
# Configure your query here
# ---------------------------------------------------------------------------
QUERY = "structured notes on contextual retrieval"
MODE  = ""  # leave empty to let parse_query detect it automatically
            # or set to: "structured-notes" | "comparison" | "lit-review"

# ---------------------------------------------------------------------------
# Build initial state
# ---------------------------------------------------------------------------
initial_state = {
    "query": QUERY,
    "mode": MODE,
    "plan": None,
    "retrieved_chunks": None,
    "draft": None,
    "citations_verified": False,
    "low_confidence_claims": [],
    "revision_count": 0,
    "final_output": None,
}


# ---------------------------------------------------------------------------
# Run — wrapped with @observe when Langfuse keys are present so all LLM
# calls in this run appear as child generations under one trace in the UI
# ---------------------------------------------------------------------------
def _run_graph() -> dict:
    return lecturn_graph.invoke(initial_state)


def _run_graph_with_langfuse() -> dict:
    """Wraps _run_graph with @observe at call time to avoid import errors."""
    from langfuse.decorators import observe, langfuse_context

    @observe(name="lecturn-agent")
    def _observed():
        langfuse_context.update_current_trace(
            name="lecturn-agent",
            input={"query": QUERY, "mode": MODE or "auto"},
            tags=["agent"],
        )
        return lecturn_graph.invoke(initial_state)

    return _observed()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print(f"Query: {QUERY}")
if MODE:
    print(f"Mode (explicit): {MODE}")
print(f"{'='*60}\n")

run_id = new_run(QUERY)

# --- injection guard ---
safety = check_query(QUERY)
if not safety["safe"]:
    print(f"[BLOCKED] Query rejected: {safety['reason']}")
    raise SystemExit(1)

if os.environ.get("LANGFUSE_SECRET_KEY"):
    try:
        final_state = _run_graph_with_langfuse()
    except ImportError:
        final_state = _run_graph()
else:
    final_state = _run_graph()

end_run(final_state.get("final_output"))

# ---------------------------------------------------------------------------
# Print results
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print("FINAL OUTPUT")
print(f"{'='*60}\n")
print(final_state["final_output"])

print(f"\n{'='*60}")
print("STATE SUMMARY")
print(f"{'='*60}")
print(f"  run_id:            {run_id}")
print(f"  mode:              {final_state['mode']}")
print(f"  plan:              {final_state['plan']}")
print(f"  chunks retrieved:  {len(final_state.get('retrieved_chunks') or [])}")
print(f"  draft length:      {len(final_state.get('draft') or '')} chars")
print(f"  citations_verified:{final_state['citations_verified']}")
print(f"  low_conf_claims:   {len(final_state.get('low_confidence_claims') or [])}")
print(f"  revision_count:    {final_state['revision_count']}")
print(f"  log:               logs/lecturn.jsonl")
