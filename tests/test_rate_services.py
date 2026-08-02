from app.plugins.repo_rate_service import RepoRateServicePlugin, CURRENT_REPO_RATE
from app.plugins.interest_rate_service import InterestRateServicePlugin
from app.core.schemas import LoanApplication


def test_repo_rate_service_returns_current_rate():
    result = RepoRateServicePlugin().run(LoanApplication())
    assert result.success is True
    assert result.data["repo_rate_percent"] == CURRENT_REPO_RATE


def test_interest_rate_lower_spread_for_high_credit_score():
    result = InterestRateServicePlugin().run(LoanApplication(credit_score=780))
    assert result.success is True
    assert result.data["spread_percent"] == 2.00


def test_interest_rate_higher_spread_for_low_credit_score():
    result = InterestRateServicePlugin().run(LoanApplication(credit_score=300))
    assert result.success is True
    assert result.data["spread_percent"] == 5.50


def test_interest_rate_missing_credit_score_fails_cleanly():
    result = InterestRateServicePlugin().run(LoanApplication(credit_score=None))
    assert result.success is False
