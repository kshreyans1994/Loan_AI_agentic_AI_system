"""
Supervisor agent — the graph's top-level router.

Decides which of the three coarse categories a turn needs:
  - tool_query: a calculation/lookup (EMI, FOIR, eligibility, credit
    score, repo rate, interest rate)
  - policy_query: a question RAG/policy-document grounding can answer
  - document_query: processing an attached document/analyzer payload

A turn can select more than one category — "am I eligible and what
does the policy say about prepayment?" is tool_query + policy_query
together. This is deliberately coarser than intent classification:
app/agents/intent_agent.py does the fine-grained "which specific
plugin within tool_query" decision downstream, so this node's job is
just picking the right *branch(es)* of the diagram.

Same LLM-error handling as the guardrail: malformed output falls back
to a safe default (policy_query only — routes to a grounded
conversational answer) rather than crashing or silently doing nothing.
"""
from __future__ import annotations

import json

from langchain_groq import ChatGroq

from app.core.config import get_settings
from app.core.schemas import AgentState, QueryCategory

SUPERVISOR_SYSTEM_PROMPT = """You are the supervisor for a loan \
application assistant. Given the user's message, decide which of \
these categories this turn needs — a turn can need more than one:

- tool_query: the user wants a calculation or lookup (EMI, FOIR, \
eligibility, credit score, current repo rate, or applicable interest \
rate)
- policy_query: the user is asking a question that loan policy \
documents, FAQs, or general product info would answer
- document_query: the user just attached/uploaded a document, bank \
statement, or financial statement for processing

Small talk or a message with none of the above gets an empty list.

Respond ONLY with JSON: {"selected_categories": ["<category>", ...], \
"reasoning": "<one sentence>"}"""

_VALID_CATEGORIES = {c.value for c in QueryCategory}


def supervisor_agent(state: AgentState) -> dict:
    last_user_message = next(
        (m.content for m in reversed(state.messages) if m.role == "user"), ""
    )
    if not last_user_message:
        return {"selected_categories": [], "supervisor_reasoning": "No user message to route."}

    settings = get_settings()
    llm = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0)

    user_prompt = (
        f"User message: {last_user_message}\n"
        f"Document/analyzer payload attached this turn: {bool(state.pending_action)}"
    )

    try:
        response = llm.invoke(
            [
                {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        parsed = json.loads(response.content)
        raw_categories = parsed.get("selected_categories", [])
        reasoning = str(parsed.get("reasoning", "")) or None
    except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
        raw_categories, reasoning = [QueryCategory.POLICY_QUERY.value], None

    categories = [c for c in raw_categories if c in _VALID_CATEGORIES]
    # Never let the LLM route to document_query on a turn that didn't
    # actually attach anything.
    if not state.pending_action and QueryCategory.DOCUMENT_QUERY.value in categories:
        categories.remove(QueryCategory.DOCUMENT_QUERY.value)

    selected_categories = [QueryCategory(c) for c in dict.fromkeys(categories)]

    return {"selected_categories": selected_categories, "supervisor_reasoning": reasoning}
