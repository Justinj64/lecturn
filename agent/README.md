# Agent Module

LangGraph state machine that turns a query into a cited, verified answer.

## Graph shape

```
parse_query → plan_sections → retrieve → draft → verify_citations
                                                       │
                                     low_conf + count < 2 → revise ┐
                                                       │             └→ verify_citations
                                              otherwise → format_output → END
```

The conditional `verify_citations → revise` loop is what makes this an agent rather than a pipeline. It can route backwards to fix its own output before the user sees it (max 2 iterations).

## Files

- **`state.py`** — `LecturnState` TypedDict, the shared whiteboard passed between every node
- **`graph.py`** — graph definition + compiled `lecturn_graph` instance; import and call `lecturn_graph.invoke(initial_state)`
- **`nodes.py`** — all 7 node functions; each returns only the fields it changed (LangGraph merges into state)
- **`prompts.py`** — all LLM prompt strings; single source of truth, no prompts inline in node code

## Running

```bash
# Edit QUERY at the top, then:
python scripts/run_agent.py

# Or from code:
from agent.graph import lecturn_graph
result = lecturn_graph.invoke(initial_state)
```

## Key design rules

- Nodes return **patches**, not full state — keeps them unit-testable and independent
- `revision_count` is a hard cap at 2 — prevents infinite loops
- `citations_verified` resets to `False` after every revision — forces re-evaluation of the new draft
- All prompts live in `prompts.py` — change them there, not in the node functions
