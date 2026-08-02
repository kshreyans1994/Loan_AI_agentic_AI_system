from app.core.schemas import LoanApplication
from app.plugins.eligibility_check import EligibilityCheckPlugin


def test_eligible_applicant():
    plugin = EligibilityCheckPlugin()
    application = LoanApplication(monthly_income=50000, credit_score=720, requested_amount=200000)

    result = plugin.run(application)

    assert result.success
    assert result.data["eligible"] is True


def test_ineligible_low_income():
    plugin = EligibilityCheckPlugin()
    application = LoanApplication(monthly_income=10000, credit_score=720)

    result = plugin.run(application)

    assert result.success
    assert result.data["eligible"] is False
    assert any("income" in r.lower() for r in result.data["reasons"])


def test_ineligible_low_credit_score():
    plugin = EligibilityCheckPlugin()
    application = LoanApplication(monthly_income=50000, credit_score=500)

    result = plugin.run(application)

    assert result.data["eligible"] is False
    assert any("credit score" in r.lower() for r in result.data["reasons"])


def test_missing_income_returns_error_not_false_eligibility():
    plugin = EligibilityCheckPlugin()
    application = LoanApplication(credit_score=700)

    result = plugin.run(application)

    assert not result.success
    assert result.error is not None


def test_requested_amount_exceeds_income_multiple():
    plugin = EligibilityCheckPlugin()
    application = LoanApplication(monthly_income=20000, credit_score=700, requested_amount=1000000)

    result = plugin.run(application)

    assert result.data["eligible"] is False
    assert any("exceeds" in r.lower() for r in result.data["reasons"])
