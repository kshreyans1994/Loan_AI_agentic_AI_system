"""
Output guardrail — runs after generate_response, before the response
reaches the user. Checks the OUTPUT rather than the input (that's
app/agents/guardrail.py's job at the front of the graph).

Two deterministic checks, both pattern-based like the input guardrail's
first layer — no LLM call, since this runs on every single turn (the
input guardrail's LLM layer only fires on ambiguous input, but every
turn that reaches here already produced a response, so an LLM check
here would be a mandatory extra call on 100% of turns):

1. **PII leakage** — the drafted response shouldn't contain another
   applicant's ID number pattern (PAN/Aadhaar-shaped strings) that
   didn't come from THIS applicant's own application data. Catches the
   case where an LLM hallucinates or echoes an ID from retrieved
   context/memory that isn't the current user's.
2. **Decision/reviewer contradiction** — if a human reviewer rejected
   this response (see app/agents/human_review.py), the drafted text
   must not contain approval language ("approved", "congratulations",
   "you qualify"). This is a safety net for the case where
   generate_response's prompt instruction gets ignored — output-level
   enforcement of a rule that's supposed to already hold, not the only
   place it's enforced.

A failed check does NOT reach the user as-is: `final_response` is
replaced with a safe, generic fallback message rather than blocking
outright (unlike the input guardrail, there's no "just don't answer"
option here — the user already asked, so a fallback message closes
the loop rather than leaving the turn silently unanswered).
"""
from __future__ import annotations

import re

from app.core.schemas import AgentState

_ID_NUMBER_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b|\b\d{4}\s?\d{4}\s?\d{4}\b")  # PAN / Aadhaar shapes

_APPROVAL_LANGUAGE = re.compile(
    r"\b(approved|congratulations|you('re| are) (eligible|qualified)|you qualify)\b", re.I
)

_FALLBACK_MESSAGE = (
    "I've got the information for your request, but I need a moment to double-check "
    "it before sharing the final answer. Please try again shortly, or contact support "
    "if this persists."
)


def _known_ids_for_applicant(state: AgentState) -> set[str]:
    ids = set()
    if state.application.pan_number:
        ids.add(state.application.pan_number.upper())
    if state.application.aadhaar_number:
        ids.add(re.sub(r"\s", "", state.application.aadhaar_number))
    return ids


def _contains_foreign_id(response: str, known_ids: set[str]) -> bool:
    found = _ID_NUMBER_PATTERN.findall(response)
    for match in found:
        normalized = re.sub(r"\s", "", match).upper()
        if normalized not in known_ids:
            return True
    return False


def output_guardrail(state: AgentState) -> dict:
    response = state.final_response or ""
    if not response:
        return {"output_guardrail_allowed": True, "output_guardrail_reason": None}

    if _contains_foreign_id(response, _known_ids_for_applicant(state)):
        return {
            "output_guardrail_allowed": False,
            "output_guardrail_reason": "Response contained an ID number not belonging to this applicant.",
            "final_response": _FALLBACK_MESSAGE,
        }

    if state.human_decision == "rejected" and _APPROVAL_LANGUAGE.search(response):
        return {
            "output_guardrail_allowed": False,
            "output_guardrail_reason": "Response used approval language despite a reviewer rejection.",
            "final_response": _FALLBACK_MESSAGE,
        }

    return {"output_guardrail_allowed": True, "output_guardrail_reason": None}
