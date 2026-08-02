"""
Node-level tracing, applied once in app/graph/pipeline.py rather than
inside every individual agent file.

Why centralized instead of a log line inside each node function: every
node already follows the same `AgentState -> dict` shape, so wrapping
once here gives every node identical entry/exit/duration/error logging
for free, and guarantees no node can be added later that silently
skips tracing because someone forgot to add the log call. Node-specific
files stay focused on their actual logic; this file is the only place
that knows about logging shape.

What gets logged per node call, at DEBUG:
  - node name, session_id, that it started
At INFO:
  - node name, session_id, duration_ms, and a small set of
    "highlight" fields specific to that node (e.g. decision_agent logs
    risk_score + requires_human_review, not its whole state diff) —
    full state is NOT logged by default, both because most of it is
    inputs unchanged from the previous node (noise) and because some
    of it (income, credit score) is applicant PII a developer debugging
    routing/graph-shape issues doesn't need in a log line.
On exception:
  - node name, session_id, duration_ms so far, full traceback, at
    ERROR — then the exception is RE-RAISED. This wrapper observes,
    it never swallows; a node failing should still fail the graph run,
    same as before tracing was added.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from langgraph.errors import GraphInterrupt

from app.core.logging_config import log_with_session
from app.core.schemas import AgentState

logger = logging.getLogger("app.graph.trace")

NodeFn = Callable[[AgentState], dict]

# Per-node function that pulls a few debug-worthy fields out of the
# dict a node returned — deliberately NOT the whole dict (see module
# docstring). Add an entry here when a new node's output has a field
# worth seeing at a glance in the trace log; nodes without an entry
# just log their returned keys instead (still useful — "did this node
# actually write anything" is itself a debugging signal).
_HIGHLIGHT_EXTRACTORS: dict[str, Callable[[dict], dict]] = {
    "guardrail_check": lambda r: {"guardrail_allowed": r.get("guardrail_allowed")},
    "supervisor_agent": lambda r: {
        "selected_categories": [c.value if hasattr(c, "value") else c for c in r.get("selected_categories", [])]
    },
    "intent_agent": lambda r: {
        "detected_intent": getattr(r.get("detected_intent"), "value", r.get("detected_intent")),
        "selected_plugins": [p.value if hasattr(p, "value") else p for p in r.get("selected_plugins", [])],
    },
    "execute_plugins": lambda r: {
        "plugins_run": [p.plugin_name for p in r.get("plugin_results", [])],
        "any_failed": any(not p.success for p in r.get("plugin_results", [])),
    },
    "decision_agent": lambda r: {
        "risk_score": r.get("risk_score"),
        "requires_human_review": r.get("requires_human_review"),
        "risk_factors": r.get("risk_factors"),
    },
    "human_review": lambda r: {"human_decision": r.get("human_decision")},
    "output_guardrail": lambda r: {
        "output_guardrail_allowed": r.get("output_guardrail_allowed"),
        "output_guardrail_reason": r.get("output_guardrail_reason"),
    },
    "retrieve_context": lambda r: {"chunks_retrieved": len(r.get("retrieved_context", []) or [])},
    "web_search_fallback": lambda r: {"results": len(r.get("web_search_results", []) or [])},
}


def traced(node_name: str, fn: NodeFn) -> NodeFn:
    def wrapped(state: AgentState) -> dict:
        session_id = state.session_id
        log_with_session(logger, logging.DEBUG, session_id, "node started", node=node_name)
        start = time.perf_counter()

        try:
            result = fn(state)
        except GraphInterrupt:
            # Expected control-flow, not a failure — human_review pausing
            # via interrupt() raises this internally to unwind the graph.
            # Log it as a normal pause and re-raise UNCHANGED; catching
            # this here only to log it, never to alter or swallow it.
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            log_with_session(
                logger, logging.INFO, session_id, "node paused (interrupt)", node=node_name, duration_ms=duration_ms
            )
            raise
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.error(
                "node raised an exception",
                extra={"session_id": session_id, "node": node_name, "duration_ms": duration_ms},
                exc_info=True,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        extractor = _HIGHLIGHT_EXTRACTORS.get(node_name)
        highlights = extractor(result) if extractor else {"returned_keys": list(result.keys())}
        log_with_session(
            logger,
            logging.INFO,
            session_id,
            f"node finished: {highlights}",
            node=node_name,
            duration_ms=duration_ms,
        )
        return result

    wrapped.__name__ = f"traced__{node_name}"
    return wrapped
