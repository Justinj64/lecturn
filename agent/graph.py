
from agent import nodes
from agent.state import LecturnState
from langgraph.graph import StateGraph, END

MAX_REVISIONS = 2  # max times the verify→revise loop can run before forcing output


def _route_after_verify(state: LecturnState) -> str:
    has_problems = len(state.get("low_confidence_claims", [])) > 0
    under_limit = state.get("revision_count", 0) < MAX_REVISIONS
    return "revise" if (has_problems and under_limit) else "format"


def build_graph() -> StateGraph:
    graph = StateGraph(LecturnState)

    graph.add_node("parse_query",      nodes.parse_query)
    graph.add_node("plan_sections",    nodes.plan_sections)
    graph.add_node("retrieve",         nodes.retrieve)
    graph.add_node("draft",            nodes.draft)
    graph.add_node("verify_citations", nodes.verify_citations)
    graph.add_node("revise",           nodes.revise)
    graph.add_node("format",           nodes.format_output)

    graph.set_entry_point("parse_query")
    graph.add_edge("parse_query",    "plan_sections")
    graph.add_edge("plan_sections",  "retrieve")
    graph.add_edge("retrieve",       "draft")
    graph.add_edge("draft",          "verify_citations")
    graph.add_conditional_edges("verify_citations", _route_after_verify,
                                {"revise": "revise", "format": "format"})
    graph.add_edge("revise", "verify_citations")
    graph.add_edge("format", END)

    return graph.compile()


lecturn_graph = build_graph()
