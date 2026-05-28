"""
Run the Lecturn agent end-to-end on a single query.

Usage:
    python scripts/run_agent.py

Edit QUERY and MODE below to change what the agent runs on.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.graph import lecturn_graph

# ---------------------------------------------------------------------------
# Configure your query here
# ---------------------------------------------------------------------------
QUERY = "structured notes on contextual retrieval"
MODE  = ""  # leave empty to let parse_query detect it automatically
            # or set to: "structured-notes" | "comparison" | "lit-review"

# ---------------------------------------------------------------------------
# Build initial state
# ---------------------------------------------------------------------------
# Only set the fields we know at the start. Everything else starts as None/empty
# and gets filled in by the nodes as the graph runs.
initial_state = {
    "query": QUERY,
    "mode": MODE,                # empty string → parse_query will detect it
    "plan": None,
    "retrieved_chunks": None,
    "draft": None,
    "citations_verified": False,
    "low_confidence_claims": [],
    "revision_count": 0,
    "final_output": None,
}

# ---------------------------------------------------------------------------
# Run the graph
# ---------------------------------------------------------------------------
print(f"\n{'='*60}")
print(f"Query: {QUERY}")
if MODE:
    print(f"Mode (explicit): {MODE}")
print(f"{'='*60}\n")

final_state = lecturn_graph.invoke(initial_state)

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
print(f"  mode:              {final_state['mode']}")
print(f"  plan:              {final_state['plan']}")
print(f"  chunks retrieved:  {len(final_state.get('retrieved_chunks') or [])}")
print(f"  draft length:      {len(final_state.get('draft') or '')} chars")
print(f"  citations_verified:{final_state['citations_verified']}")
print(f"  low_conf_claims:   {len(final_state.get('low_confidence_claims') or [])}")
print(f"  revision_count:    {final_state['revision_count']}")
