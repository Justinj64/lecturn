"""
Day 26 – Streamlit UI for the Lecturn agent.

Run with:
    streamlit run app.py

The UI exposes:
  - A query input with optional mode override
  - Real-time status updates as the agent graph progresses
  - The final markdown output
  - A sidebar with run metadata (mode, plan, sources, cache stats, run_id)
  - Inline warnings for low-confidence claims and invalid citations
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.graph import lecturn_graph
from production.cache import cache_stats
from production.guardrails import check_query
from production.observability import new_run, end_run

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Lecturn",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Lecturn")
st.caption("Cited answers from AI/ML research papers and blog posts.")

# ---------------------------------------------------------------------------
# Sidebar — cache stats and Langfuse link
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("System")

    cache_entries = st.empty()
    cache_size = st.empty()

    def _render_cache_stats():
        stats = cache_stats()
        cache_entries.metric("Cache entries", stats["entries"])
        cache_size.metric("Cache size", f"{stats['size_kb']} KB")

    _render_cache_stats()

    if os.environ.get("LANGFUSE_SECRET_KEY"):
        st.success("Langfuse tracing active")
    else:
        st.info("Langfuse not configured")

    st.divider()
    st.header("Run details")
    run_meta = st.empty()   # filled in after a run completes

# ---------------------------------------------------------------------------
# Query form
# ---------------------------------------------------------------------------

with st.form("query_form"):
    query = st.text_input(
        "Query",
        placeholder="e.g. compare RAG and fine-tuning for knowledge-intensive tasks",
    )
    mode = st.selectbox(
        "Mode (leave on Auto to let the agent decide)",
        options=["Auto", "structured-notes", "comparison", "lit-review"],
    )
    submitted = st.form_submit_button("Run", type="primary")

# ---------------------------------------------------------------------------
# Agent run
# ---------------------------------------------------------------------------

if submitted and query.strip():

    # --- injection guard ---
    safety = check_query(query)
    if not safety["safe"]:
        st.error(f"Query blocked: {safety['reason']}")
        st.stop()

    explicit_mode = "" if mode == "Auto" else mode

    initial_state = {
        "query":                 query,
        "mode":                  explicit_mode,
        "plan":                  None,
        "retrieved_chunks":      None,
        "draft":                 None,
        "citations_verified":    False,
        "low_confidence_claims": [],
        "revision_count":        0,
        "final_output":          None,
    }

    run_id = new_run(query)

    # Progress placeholder shown while graph is running
    status = st.status("Running agent…", expanded=True)

    with status:
        st.write("🔍 Classifying query and planning sections…")

        # Run the full graph (blocking — Streamlit reruns on completion)
        if os.environ.get("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse.decorators import observe, langfuse_context

                @observe(name="lecturn-agent")
                def _run():
                    langfuse_context.update_current_trace(
                        name="lecturn-agent",
                        input={"query": query, "mode": explicit_mode or "auto"},
                        tags=["agent", "streamlit"],
                    )
                    return lecturn_graph.invoke(initial_state)

                final_state = _run()
            except ImportError:
                final_state = lecturn_graph.invoke(initial_state)
        else:
            final_state = lecturn_graph.invoke(initial_state)

        st.write("✅ Done.")
        status.update(label="Agent complete", state="complete", expanded=False)

    end_run(final_state.get("final_output"))
    _render_cache_stats()

    # --- sidebar metadata ---
    with run_meta.container():
        st.markdown(f"**run_id** `{run_id}`")
        st.markdown(f"**mode** `{final_state['mode']}`")
        st.markdown(f"**revisions** {final_state['revision_count']}")
        chunks = final_state.get("retrieved_chunks") or []
        st.markdown(f"**chunks retrieved** {len(chunks)}")
        unique_sources = list({c["title"] for c in chunks})
        if unique_sources:
            st.markdown("**sources retrieved**")
            for src in unique_sources:
                st.markdown(f"- {src}")
        if final_state.get("plan"):
            st.markdown("**sections planned**")
            for section in final_state["plan"]:
                st.markdown(f"- {section}")

    # --- warnings ---
    low_conf = final_state.get("low_confidence_claims") or []
    if low_conf:
        with st.expander(f"⚠️ {len(low_conf)} low-confidence claim(s)", expanded=False):
            for item in low_conf:
                st.markdown(f"**Score {item['score']}/5** — {item['claim']}")
                st.caption(item["reasoning"])

    # --- main output ---
    st.divider()
    st.markdown(final_state["final_output"])

elif submitted and not query.strip():
    st.warning("Please enter a query.")
