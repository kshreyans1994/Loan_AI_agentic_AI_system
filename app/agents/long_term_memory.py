"""
Long-term memory nodes: recall (start of turn) and save (end of turn).

Recall pulls durable facts + recent session summaries so the agent can
say "welcome back" and skip re-asking for things it already knows.
Save extracts anything worth remembering from THIS turn and persists it.

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

FACT_EXTRACTION_PROMPT = """Given this conversation turn, extract any \
durable facts worth remembering about the user for FUTURE sessions — \
things like stated income, loan preferences, past application outcomes, \
or explicit corrections ("actually my income is..."). Do NOT extract \
one-off calculation requests or small talk.

Respond ONLY with JSON: {"facts": [{"fact": "<short fact>", \
"category": "profile|application_history|preference"}]} \
(empty list if nothing worth remembering)"""


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
    except (json.JSONDecodeError, ValueError, TypeError):
        new_facts = []

    if not new_facts:
        return {}

    try:
        store = get_long_term_memory_store()
        for fact in new_facts:
            store.save_fact(state.user_id, fact)
    except psycopg.Error as exc:
        logger.warning(
            "Long-term memory save skipped for user=%s: Postgres unavailable. Response continues without memory persistence. Error=%s",
            state.user_id,
            exc,
        )
        return {}

    return {"long_term_memory": state.long_term_memory + new_facts}
