"""
Web search fallback node.

Fires only when RAG retrieval came back empty or low-confidence — the
static knowledge base covers policy/FAQ/rate-tier content that doesn't
change often, but things like "what's the current RBI repo rate" or
"any recent changes to loan regulations" are genuinely time-sensitive
and outside what a seeded pgvector table can answer. Gating on RAG
thinness (rather than always searching) keeps latency and cost down for
the common case where the knowledge base already has the answer.
"""
from __future__ import annotations

from app.core.schemas import AgentState, QueryCategory

# Below this mean top-result score, RAG context is treated as "didn't
# really answer the question" rather than "answered it, just imperfectly."
RAG_CONFIDENCE_FLOOR = 0.45


def _rag_context_is_thin(state: AgentState) -> bool:
    if not state.retrieved_context:
        return True
    top_score = max(c.score for c in state.retrieved_context)
    return top_score < RAG_CONFIDENCE_FLOOR


def web_search_fallback(state: AgentState) -> dict:
    if QueryCategory.POLICY_QUERY not in state.selected_categories:
        return {}
    if not _rag_context_is_thin(state):
        return {}

    last_user_message = next(
        (m.content for m in reversed(state.messages) if m.role == "user"), ""
    )
    if not last_user_message:
        return {}

    from app.rag.web_search_client import get_web_search_client

    client = get_web_search_client()
    results = client.search(last_user_message, max_results=3)

    return {"web_search_results": results}
