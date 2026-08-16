"""
Long-term memory nodes: recall (start of turn) and save (end of turn).

Recall pulls durable facts + recent session summaries so the agent can
say "welcome back" and skip re-asking for things it already knows.
Save extracts anything worth remembering from THIS turn and persists it,
AND writes a one-line summary of the turn to session_summaries — the
"bridge" between short-term (full, unfiltered) and long-term (durable
facts only) memory described in docs/ARCHITECTURE.md.

Both no-op cleanly when `user_id` isn't set (e.g. anonymous/guest chat) —
long-term memory is an enhancement for identified users, not a hard
dependency for the graph to function.
"""
from __future__ import annotations

import json
import logging

import psycopg
from langchain_groq import ChatGroq

from app.core.config import get_settings
from app.core.memory_long_term import get_long_term_memory_store
from app.core.schemas import AgentState, LongTermMemoryFact

logger = logging.getLogger(__name__)

# One LLM call does both jobs — facts (durable, per-fact) and a summary
# (one line, per-turn) — rather than two separate calls per turn. They're
# different shapes of the same "what happened this turn" question, so
# there's no accuracy cost to asking for both at once, and it halves the
# LLM cost/latency this node adds versus calling it twice.
FACT_EXTRACTION_PROMPT = """Given this conversation turn, do two things:

1. Extract any durable facts worth remembering about the user for \
FUTURE sessions — things like stated income, loan preferences, past \
application outcomes, or explicit corrections ("actually my income \
is..."). Do NOT extract one-off calculation requests or small talk.

2. Write a ONE-SENTENCE summary of what happened in this turn (e.g. \
"User asked about EMI on a 2 lakh loan and was quoted ~9,270/month").

Respond ONLY with JSON: {"facts": [{"fact": "<short fact>", \
"category": "profile|application_history|preference"}], "summary": \
"<one sentence>"} (empty facts list if nothing worth remembering; \
summary is always required, even for small talk)"""


def recall_long_term_memory(state: AgentState) -> dict:
    if not state.user_id:
        return {}

    store = get_long_term_memory_store()
    facts = store.get_facts(state.user_id)

    return {"long_term_memory": facts}


def save_long_term_memory(state: AgentState) -> dict:
    if not state.user_id:
        return {}

    last_user_message = next(
        (m.content for m in reversed(state.messages) if m.role == "user"), ""
    )
    if not last_user_message or not state.final_response:
        return {}

    settings = get_settings()
    llm = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0)

    response = llm.invoke(
        [
            {"role": "system", "content": FACT_EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": f"User: {last_user_message}\nAssistant: {state.final_response}",
            },
        ]
    )

    try:
        parsed = json.loads(response.content)
        new_facts = [LongTermMemoryFact(**f) for f in parsed.get("facts", [])]
        summary = parsed.get("summary") or None
    except (json.JSONDecodeError, ValueError, TypeError):
        new_facts = []
        summary = None

    if not new_facts and not summary:
        return {}

    try:
        store = get_long_term_memory_store()
        for fact in new_facts:
            store.save_fact(state.user_id, fact)
        if summary:
            store.save_summary(state.user_id, state.session_id, summary)
    except psycopg.Error as exc:
        logger.warning(
            "Long-term memory save skipped for user=%s: Postgres unavailable. Response continues without memory persistence. Error=%s",
            state.user_id,
            exc,
        )
        return {}

    return {"long_term_memory": state.long_term_memory + new_facts}