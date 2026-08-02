from app.plugins.foir_calculator import FOIRCalculatorPlugin
from app.core.schemas import LoanApplication

plugin = FOIRCalculatorPlugin()


def test_healthy_foir_band():
    app = LoanApplication(monthly_income=100000, existing_monthly_emi=5000, requested_amount=200000, tenure_months=24)
    result = plugin.run(app)
    assert result.success is True
    assert result.data["band"] == "healthy"


def test_high_risk_foir_band():
    app = LoanApplication(monthly_income=30000, existing_monthly_emi=10000, requested_amount=500000, tenure_months=24)
    result = plugin.run(app)
    assert result.success is True
    assert result.data["band"] == "high_risk"


def test_missing_income_fails_cleanly():
    app = LoanApplication(monthly_income=None, requested_amount=200000, tenure_months=24)
    result = plugin.run(app)
    assert result.success is False
    assert "income" in result.error.lower()


def test_missing_amount_or_tenure_fails_cleanly():
    app = LoanApplication(monthly_income=50000, requested_amount=None, tenure_months=None)
    result = plugin.run(app)
    assert result.success is False


def test_default_existing_emi_is_zero_not_none():
    app = LoanApplication(monthly_income=100000, requested_amount=200000, tenure_months=24)
    result = plugin.run(app)
    assert result.success is True
    assert result.data["existing_monthly_emi"] == 0.0
