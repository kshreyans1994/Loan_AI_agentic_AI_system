"""
Intent agent — picks the specific plugin(s) within whatever categories
app/agents/supervisor.py selected.

Only asks the question that's actually still open at this point:
"given we know this needs tool_query and/or document_query, which
EXACT plugin(s)?" It never runs if supervisor selected only
policy_query (nothing to pick — that's RAG's job, no plugin needed),
which keeps this LLM call from firing on pure policy questions.

Same fail-safe pattern as the rest of the pipeline: invalid intents in
the LLM's output are dropped, not crashed on, and document/analyzer
intents can never survive without a genuinely attached payload this
turn — regardless of what the LLM outputs.
"""
from __future__ import annotations

import json

from langchain_groq import ChatGroq

from app.core.config import get_settings
from app.core.schemas import AgentState, Intent, QueryCategory

INTENT_AGENT_SYSTEM_PROMPT = """You are the intent agent for a loan \
application assistant. Given the user's message and what's already \
known about their application, decide:

1. detected_intent — the single PRIMARY intent, one of: apply_loan, \
check_eligibility, calculate_emi, calculate_foir, check_credit_score, \
check_repo_rate, check_interest_rate, upload_document, \
submit_bank_statement_analysis, submit_financial_statement_analysis, \
ask_question, small_talk

2. selected_plugins — the list of intents (from the same set) whose \
plugin should actually run THIS turn. Usually [detected_intent], but \
include more than one if the message clearly asks for multiple \
things at once (e.g. eligibility AND FOIR in the same message). Use \
an empty list for ask_question/small_talk/apply_loan.

Only select upload_document, submit_bank_statement_analysis, or \
submit_financial_statement_analysis if the message explicitly \
references an attachment/upload/submission that was just made.

Respond ONLY with JSON: {"detected_intent": "<intent>", \
"selected_plugins": ["<intent>", ...], "reasoning": "<one sentence>"}"""

_VALID_INTENTS = {i.value for i in Intent}
_DOCUMENT_LIKE_INTENTS = {
    Intent.UPLOAD_DOCUMENT.value,
    Intent.SUBMIT_BANK_STATEMENT_ANALYSIS.value,
    Intent.SUBMIT_FINANCIAL_STATEMENT_ANALYSIS.value,
}


def _application_summary(state: AgentState) -> str:
    app = state.application
    known = {
        k: v
        for k, v in {
            "monthly_income": app.monthly_income,
            "requested_amount": app.requested_amount,
            "credit_score": app.credit_score,
            "eligibility_status": app.eligibility_status,
        }.items()
        if v is not None
    }
    return json.dumps(known) if known else "nothing known yet"


def intent_agent(state: AgentState) -> dict:
    # Nothing to pick if the supervisor didn't route into tool_query or
    # document_query — a pure policy_query turn needs no plugin at all.
    if not (
        QueryCategory.TOOL_QUERY in state.selected_categories
        or QueryCategory.DOCUMENT_QUERY in state.selected_categories
    ):
        return {
            "detected_intent": Intent.ASK_QUESTION,
            "selected_plugins": [],
            "intent_reasoning": "Supervisor selected only policy_query — no plugin needed.",
        }

    last_user_message = next(
        (m.content for m in reversed(state.messages) if m.role == "user"), ""
    )
    if not last_user_message:
        return {
            "detected_intent": Intent.UNKNOWN,
            "selected_plugins": [],
            "intent_reasoning": "No user message to classify.",
        }

    settings = get_settings()
    llm = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0)

    user_prompt = (
        f"User message: {last_user_message}\n"
        f"Known application data so far: {_application_summary(state)}\n"
        f"Document/analyzer payload attached this turn: {bool(state.pending_action)}"
    )

    try:
        response = llm.invoke(
            [
                {"role": "system", "content": INTENT_AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
        parsed = json.loads(response.content)
        raw_intent = str(parsed.get("detected_intent", ""))
        raw_selected = parsed.get("selected_plugins", [])
        reasoning = str(parsed.get("reasoning", "")) or None
    except (json.JSONDecodeError, ValueError, KeyError, AttributeError):
        raw_intent, raw_selected, reasoning = "", [], None

    detected_intent = Intent(raw_intent) if raw_intent in _VALID_INTENTS else Intent.ASK_QUESTION

    selected = [i for i in raw_selected if i in _VALID_INTENTS]
    if not state.pending_action:
        selected = [i for i in selected if i not in _DOCUMENT_LIKE_INTENTS]
    selected_plugins = [Intent(i) for i in dict.fromkeys(selected)]

    return {
        "detected_intent": detected_intent,
        "selected_plugins": selected_plugins,
        "intent_reasoning": reasoning,
    }
