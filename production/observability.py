"""
Day 22 – Structured observability layer.

Two complementary outputs:
  1. Local JSONL  (logs/lecturn.jsonl)  — always-on, no external deps
  2. Langfuse     (cloud.langfuse.com)  — rich UI traces when env keys are set

Usage
-----
from production.observability import new_run, end_run, log_event, timed_node

run_id = new_run(query)          # call once before graph.invoke()
...                              # graph runs; nodes call log_event / timed_node
end_run(final_output)            # flushes Langfuse, closes JSONL entry
"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOGS_DIR / "lecturn.jsonl"

_run_id: str = ""


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

def new_run(query: str) -> str:
    """
    Start a new agent run.
    Creates a fresh run_id, writes a run.start entry, and returns the id.
    """
    global _run_id
    _run_id = uuid.uuid4().hex[:8]
    LOGS_DIR.mkdir(exist_ok=True)
    log_event("run.start", {"query": query})
    return _run_id


def end_run(final_output: str | None = None) -> None:
    """
    Close the run and flush Langfuse so all spans are shipped before exit.
    """
    log_event("run.end", {"output_chars": len(final_output or "")})
    try:
        if os.environ.get("LANGFUSE_SECRET_KEY"):
            from langfuse import Langfuse
            Langfuse().flush()
    except Exception:
        pass


def get_run_id() -> str:
    """
    Return the current run_id set by the most recent new_run() call.
    """
    return _run_id


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

def log_event(event: str, data: dict[str, Any] | None = None) -> None:
    """
    Emit one structured log entry to:
      - stdout              (human-readable key=value line)
      - logs/lecturn.jsonl  (newline-delimited JSON, one object per line)

    Every entry includes ts, run_id, and event automatically.
    """
    entry: dict[str, Any] = {
        "ts":     datetime.now(timezone.utc).isoformat(),
        "run_id": _run_id,
        "event":  event,
        **(data or {}),
    }
    kv = "  ".join(f"{k}={v}" for k, v in (data or {}).items())
    print(f"[{_run_id or '--------'}] {event}" + (f"  {kv}" if kv else ""))

    LOGS_DIR.mkdir(exist_ok=True)
    with LOG_FILE.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Node timing helper
# ---------------------------------------------------------------------------

@contextmanager
def timed_node(name: str):
    """
    Context manager that times a node and emits <name>.start / <name>.end events.

    Yields a mutable `meta` dict the caller can populate during execution;
    its contents are merged into the .end log entry:

        with timed_node("retrieve") as meta:
            chunks = do_work()
            meta["chunks"] = len(chunks)   # shows up in .end entry
    """
    log_event(f"{name}.start")
    t0 = time.perf_counter()
    meta: dict[str, Any] = {}
    try:
        yield meta
    finally:
        elapsed = round(time.perf_counter() - t0, 3)
        log_event(f"{name}.end", {"duration_s": elapsed, **meta})
