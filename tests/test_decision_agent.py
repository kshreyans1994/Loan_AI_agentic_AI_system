from app.agents.decision_agent import decision_agent
from app.core.schemas import AgentState, LoanApplication, PluginResult


def _eligibility_result(eligible: bool, cutoff: int = 650, success: bool = True) -> PluginResult:
    return PluginResult(
        plugin_name="eligibility_check",
        success=success,
        data={"eligible": eligible, "criteria_checked": {"min_credit_score": cutoff}},
    )


def _foir_result(band: str, foir_percent: float = 30.0) -> PluginResult:
    return PluginResult(
        plugin_name="foir_calculator",
        success=True,
        data={"band": band, "foir_percent": foir_percent},
    )


def test_clean_low_risk_turn_scores_low_and_does_not_escalate():
    state = AgentState(
        session_id="s1",
        application=LoanApplication(monthly_income=80000, credit_score=800, requested_amount=100000),
        plugin_results=[_eligibility_result(eligible=True, cutoff=650), _foir_result("healthy")],
    )
    result = decision_agent(state)
    assert result["requires_human_review"] is False
    assert result["risk_score"] < 0.85


def test_plugin_failure_alone_pushes_risk_up_but_not_necessarily_over_threshold():
    state = AgentState(
        session_id="s1",
        application=LoanApplication(monthly_income=80000, credit_score=800, requested_amount=100000),
        plugin_results=[_eligibility_result(eligible=True, success=True), _foir_result("healthy")]
        + [PluginResult(plugin_name="calculate_emi", success=False, error="boom")],
    )
    result = decision_agent(state)
    assert "one or more plugin calls failed" in result["risk_factors"]
    assert result["risk_score"] >= 0.5


def test_high_risk_foir_plus_borderline_credit_score_triggers_review():
    state = AgentState(
        session_id="s1",
        application=LoanApplication(monthly_income=50000, credit_score=645, requested_amount=800000),
        plugin_results=[_eligibility_result(eligible=False, cutoff=650), _foir_result("high_risk", 60.0)],
    )
    result = decision_agent(state)
    assert result["requires_human_review"] is True
    assert result["risk_score"] >= 0.85


def test_risk_score_is_capped_at_one():
    state = AgentState(
        session_id="s1",
        application=LoanApplication(monthly_income=50000, credit_score=640, requested_amount=900000),
        plugin_results=[
            _eligibility_result(eligible=False, cutoff=650),
            _foir_result("high_risk", 90.0),
            PluginResult(plugin_name="calculate_emi", success=False, error="boom"),
        ],
    )
    result = decision_agent(state)
    assert result["risk_score"] <= 1.0


def test_no_plugin_results_scores_zero():
    state = AgentState(session_id="s1")
    result = decision_agent(state)
    assert result["risk_score"] == 0.0
    assert result["requires_human_review"] is False
