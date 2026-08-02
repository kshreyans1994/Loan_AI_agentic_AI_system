from app.agents.output_guardrail import output_guardrail
from app.core.schemas import AgentState, LoanApplication


def test_clean_response_passes():
    state = AgentState(
        session_id="s1",
        final_response="Your EMI would be approximately ₹9,270 per month.",
    )
    result = output_guardrail(state)
    assert result["output_guardrail_allowed"] is True


def test_foreign_pan_number_in_response_is_blocked():
    state = AgentState(
        session_id="s1",
        application=LoanApplication(pan_number="ABCDE1234F"),
        final_response="Note: applicant XYZAB5678C also applied last week.",
    )
    result = output_guardrail(state)
    assert result["output_guardrail_allowed"] is False
    assert "final_response" in result


def test_own_pan_number_in_response_is_not_blocked():
    state = AgentState(
        session_id="s1",
        application=LoanApplication(pan_number="ABCDE1234F"),
        final_response="Your PAN on file is ABCDE1234F.",
    )
    result = output_guardrail(state)
    assert result["output_guardrail_allowed"] is True


def test_approval_language_after_rejection_is_blocked():
    state = AgentState(
        session_id="s1",
        human_decision="rejected",
        final_response="Congratulations, you're approved for this loan!",
    )
    result = output_guardrail(state)
    assert result["output_guardrail_allowed"] is False


def test_approval_language_after_approval_is_fine():
    state = AgentState(
        session_id="s1",
        human_decision="approved",
        final_response="Congratulations, you're approved for this loan!",
    )
    result = output_guardrail(state)
    assert result["output_guardrail_allowed"] is True


def test_empty_response_passes_trivially():
    state = AgentState(session_id="s1", final_response=None)
    result = output_guardrail(state)
    assert result["output_guardrail_allowed"] is True
