"""
Decision agent — aggregates this turn's plugin outputs into a single
risk_score (0.0-1.0) and decides whether human_review needs to fire.

Deliberately deterministic, not an LLM call, for the same reason
eligibility/EMI/FOIR are deterministic (see docs/ARCHITECTURE.md §7):
"why did this get escalated to a human" needs a reproducible answer.
The supervisor and intent agent are allowed to be LLM-driven because a
wrong ROUTING choice is low-consequence and self-correcting (ask
again); a wrong risk-scoring choice directly decides whether a human
ever sees a lending decision before it goes out, which is exactly the
kind of consequential, auditable call this project keeps out of the
LLM's hands.

Risk factors (weights are additive, then capped at 1.0 — see each
factor's comment for why it's weighted the way it is):

  - Any plugin call failed (success=False)         -> +0.50
    Something went wrong; never let a silent failure look like a
    clean decision.
  - FOIR band is "high_risk" (>=55%)                -> +0.45
  - FOIR band is "caution" (40-55%)                  -> +0.25
  - Eligibility check came back ineligible            -> +0.20
    (a clean rejection is lower-stakes than a borderline
    approval — the applicant isn't being extended credit)
  - Credit score within human_review_credit_score_margin
    of the eligibility cutoff, in EITHER direction       -> +0.30
    (borderline case, could easily have gone the other way)
  - Requested amount >= human_review_amount_threshold     -> +0.20

requires_human_review = risk_score >= settings.decision_risk_threshold
(0.85 by default) — see app/agents/human_review.py for what happens
next.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.schemas import AgentState, PluginResult

# Not exposed in Settings (unlike decision_risk_threshold) because these
# are risk-MODEL weights, not deployment config — changing them changes
# what "risk" means, not how strict the deployment is about it.
_PLUGIN_FAILURE_WEIGHT = 0.50
_FOIR_HIGH_RISK_WEIGHT = 0.45
_FOIR_CAUTION_WEIGHT = 0.25
_INELIGIBLE_WEIGHT = 0.20
_BORDERLINE_CREDIT_SCORE_WEIGHT = 0.30
_LARGE_AMOUNT_WEIGHT = 0.20
_BORDERLINE_CREDIT_SCORE_MARGIN = 15


def _latest(results: list[PluginResult], plugin_name: str) -> PluginResult | None:
    for result in reversed(results):
        if result.plugin_name == plugin_name:
            return result
    return None


def decision_agent(state: AgentState) -> dict:
    settings = get_settings()
    risk_score = 0.0
    risk_factors: list[str] = []

    if any(not r.success for r in state.plugin_results):
        risk_score += _PLUGIN_FAILURE_WEIGHT
        risk_factors.append("one or more plugin calls failed")

    foir_result = _latest(state.plugin_results, "foir_calculator")
    if foir_result and foir_result.success:
        band = foir_result.data.get("band")
        if band == "high_risk":
            risk_score += _FOIR_HIGH_RISK_WEIGHT
            risk_factors.append(f"FOIR {foir_result.data.get('foir_percent')}% is high-risk")
        elif band == "caution":
            risk_score += _FOIR_CAUTION_WEIGHT
            risk_factors.append(f"FOIR {foir_result.data.get('foir_percent')}% needs caution")

    eligibility_result = _latest(state.plugin_results, "eligibility_check")
    if eligibility_result and eligibility_result.success:
        eligible = eligibility_result.data.get("eligible")
        cutoff = eligibility_result.data.get("criteria_checked", {}).get("min_credit_score")
        credit_score = state.application.credit_score

        if eligible is False:
            risk_score += _INELIGIBLE_WEIGHT
            risk_factors.append("eligibility check came back ineligible")

        if credit_score is not None and cutoff is not None:
            margin = abs(credit_score - cutoff)
            if margin <= _BORDERLINE_CREDIT_SCORE_MARGIN:
                risk_score += _BORDERLINE_CREDIT_SCORE_WEIGHT
                risk_factors.append(
                    f"credit score {credit_score} is within {margin} points of the {cutoff} cutoff"
                )

    amount = state.application.requested_amount
    if amount and amount >= settings.human_review_amount_threshold:
        risk_score += _LARGE_AMOUNT_WEIGHT
        risk_factors.append(
            f"requested amount ₹{amount:,.0f} is at/above the ₹{settings.human_review_amount_threshold:,.0f} threshold"
        )

    risk_score = min(risk_score, 1.0)
    requires_human_review = risk_score >= settings.decision_risk_threshold

    return {
        "risk_score": round(risk_score, 3),
        "risk_factors": risk_factors,
        "requires_human_review": requires_human_review,
    }


def route_after_decision(state: AgentState) -> str:
    return "human_review" if state.requires_human_review else "generate_response"
