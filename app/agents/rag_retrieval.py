"""RAG retrieval node — the "RAG Agent" branch of the diagram. Only
fires when the supervisor selected policy_query for this turn; skipping
it for pure calculator/document turns avoids a wasted retrieval pass.

Delegates the actual hybrid retrieval (query rewrite -> metadata filter
-> vector + lexical search -> merge -> rerank -> compression) to
HybridRetriever — see app/rag/retriever.py for why those steps live
there rather than as separate graph nodes.
"""
from __future__ import annotations

from app.core.schemas import AgentState, QueryCategory
from app.rag.retriever import get_retriever


def retrieve_context(state: AgentState) -> dict:
    if QueryCategory.POLICY_QUERY not in state.selected_categories:
        return {}

    last_user_message = next(
        (m.content for m in reversed(state.messages) if m.role == "user"), ""
    )
    if not last_user_message:
        return {}

    retriever = get_retriever()
    chunks = retriever.retrieve_hybrid(last_user_message)

    return {"retrieved_context": chunks}
