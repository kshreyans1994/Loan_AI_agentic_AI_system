"""
Human-in-the-loop review node.

Only reached when app/agents/decision_agent.py sets
requires_human_review — i.e. risk_score >= settings.decision_risk_threshold.
Most turns (routine EMI/FOIR calculations, clean high-credit-score
approvals, policy questions) skip this node entirely and go straight to
generate_response. When reached, it calls LangGraph's interrupt(),
which pauses graph execution mid-run; nothing after this node executes
until someone resumes the thread via POST /loan/review (see
app/api/routes.py) with an approve/reject decision.

Do not wrap interrupt() in try/except — LangGraph raises a control-flow
exception internally to unwind the graph, and swallowing it breaks the
pause/resume mechanism.
"""
from __future__ import annotations

from langgraph.types import Command, interrupt

from app.core.schemas import AgentState


def human_review(state: AgentState) -> dict:
    decision = interrupt(
        {
            "type": "risk_review",
            "risk_score": state.risk_score,
            "risk_factors": state.risk_factors,
            "detected_intent": state.detected_intent.value if state.detected_intent else None,
            "plugin_results": [r.model_dump() for r in state.plugin_results],
            "application_summary": {
                "requested_amount": state.application.requested_amount,
                "monthly_income": state.application.monthly_income,
                "credit_score": state.application.credit_score,
            },
        }
    )

    # `decision` is whatever the caller passes into Command(resume=...)
    # when resuming — see /loan/review in app/api/routes.py.
    approved = bool(decision.get("approved", False))
    feedback = decision.get("feedback")

    return {
        "human_decision": "approved" if approved else "rejected",
        "human_feedback": feedback,
    }


__all__ = ["human_review", "Command"]
