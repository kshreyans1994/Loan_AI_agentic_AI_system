"""
LangGraph pipeline assembly — mirrors the reference "Overall System
Flow" diagram (see docs/ARCHITECTURE.md §2 for the full picture and
the reasoning behind each addition):

  guardrail_check ──(blocked)──▶ guardrail_blocked_response ──▶ END
        │ (allowed)
        ▼
  recall_long_term_memory
        │
        ▼
  supervisor_agent      (LLM: which categories — tool_query /
        │                 policy_query / document_query — does this
        │                 turn need?)
        ▼
  intent_agent           (LLM: which SPECIFIC plugin(s) within those
        │                 categories?)
        ▼
  execute_plugins ─▶ retrieve_context ─▶ web_search_fallback
        │
        ▼
  decision_agent         (deterministic: aggregates plugin outputs into
        │                 risk_score, decides requires_human_review)
        │
        ├──(risk_score >= threshold)──▶ human_review (interrupt) ──▶┐
        │                                                            │
        └──(below threshold)────────────────────────────▶ generate_response
                                                                 │
                                                        output_guardrail
                                                                 │
                                                        write_audit_log
                                                                 │
                                                     save_long_term_memory
                                                                 │
                                                                END

Three things changed from the version of this pipeline before this
revision, all per an explicit request to match this exact diagram:

  1. Supervisor and intent classification are now two separate LLM
     nodes (coarse category -> specific plugin) instead of one merged
     node.
  2. Human review is CONDITIONAL again (risk_score-gated, via
     decision_agent) rather than running on every turn.
  3. An output guardrail and an audit-log write were added after
     response generation.

See docs/ARCHITECTURE.md §7-11 for the full trade-off discussion of
each of these choices, including why decision_agent stays deterministic
even though the routing agents upstream of it are LLM-driven.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.decision_agent import decision_agent, route_after_decision
from app.agents.guardrail import guardrail_blocked_response, guardrail_check
from app.agents.human_review import human_review
from app.agents.intent_agent import intent_agent
from app.agents.long_term_memory import recall_long_term_memory, save_long_term_memory
from app.agents.output_guardrail import output_guardrail
from app.agents.plugin_executor import execute_plugins
from app.agents.rag_retrieval import retrieve_context
from app.agents.response_generator import generate_response
from app.agents.supervisor import supervisor_agent
from app.agents.web_search import web_search_fallback
from app.core.schemas import AgentState
from app.db.audit_log import write_audit_log
from app.graph.node_tracing import traced


def _route_after_guardrail(state: AgentState) -> str:
    return "recall_long_term_memory" if state.guardrail_allowed else "guardrail_blocked_response"


def build_graph():
    graph = StateGraph(AgentState)

    # Every node is wrapped with traced() here, at the ONE place all
    # nodes get registered — see app/graph/node_tracing.py for why this
    # is centralized rather than a log call inside each agent file.
    graph.add_node("guardrail_check", traced("guardrail_check", guardrail_check))
    graph.add_node("guardrail_blocked_response", traced("guardrail_blocked_response", guardrail_blocked_response))
    graph.add_node("recall_long_term_memory", traced("recall_long_term_memory", recall_long_term_memory))
    graph.add_node("supervisor_agent", traced("supervisor_agent", supervisor_agent))
    graph.add_node("intent_agent", traced("intent_agent", intent_agent))
    graph.add_node("execute_plugins", traced("execute_plugins", execute_plugins))
    graph.add_node("retrieve_context", traced("retrieve_context", retrieve_context))
    graph.add_node("web_search_fallback", traced("web_search_fallback", web_search_fallback))
    graph.add_node("decision_agent", traced("decision_agent", decision_agent))
    graph.add_node("human_review", traced("human_review", human_review))
    graph.add_node("generate_response", traced("generate_response", generate_response))
    graph.add_node("output_guardrail", traced("output_guardrail", output_guardrail))
    graph.add_node("write_audit_log", traced("write_audit_log", write_audit_log))
    graph.add_node("save_long_term_memory", traced("save_long_term_memory", save_long_term_memory))

    graph.set_entry_point("guardrail_check")
    graph.add_conditional_edges(
        "guardrail_check",
        _route_after_guardrail,
        {
            "recall_long_term_memory": "recall_long_term_memory",
            "guardrail_blocked_response": "guardrail_blocked_response",
        },
    )
    graph.add_edge("guardrail_blocked_response", END)

    graph.add_edge("recall_long_term_memory", "supervisor_agent")
    graph.add_edge("supervisor_agent", "intent_agent")
    graph.add_edge("intent_agent", "execute_plugins")
    graph.add_edge("execute_plugins", "retrieve_context")
    # Web search only fires if RAG came back empty/thin — see
    # web_search_fallback's own guard clause for the exact condition.
    graph.add_edge("retrieve_context", "web_search_fallback")
    graph.add_edge("web_search_fallback", "decision_agent")

    graph.add_conditional_edges(
        "decision_agent",
        route_after_decision,
        {"human_review": "human_review", "generate_response": "generate_response"},
    )
    graph.add_edge("human_review", "generate_response")

    graph.add_edge("generate_response", "output_guardrail")
    graph.add_edge("output_guardrail", "write_audit_log")
    graph.add_edge("write_audit_log", "save_long_term_memory")
    graph.add_edge("save_long_term_memory", END)

    # MemorySaver = in-process, thread-keyed checkpointer. Each session_id
    # becomes a LangGraph "thread", giving automatic short-term memory
    # (full message history + state) with zero extra infrastructure. It's
    # also what makes interrupt()/resume in human_review work at all —
    # the checkpointer is what persists state across the pause.
    # Swap for langgraph.checkpoint.postgres.PostgresSaver to persist
    # across process restarts without changing any node code.
    checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)


# Compiled once at import time; LangGraph graphs are stateless/reusable
# across requests, so a module-level singleton is the right lifecycle.
compiled_graph = build_graph()
