from app.core.schemas import LoanApplication
from app.plugins.emi_calculator import EMICalculatorPlugin


def test_emi_calculation_standard_case():
    plugin = EMICalculatorPlugin()
    application = LoanApplication(requested_amount=100000, tenure_months=12)

    result = plugin.run(application, annual_rate=12.0)

    assert result.success
    # Known value for ₹100,000 at 12% p.a. over 12 months ≈ ₹8,884.88
    assert 8800 < result.data["emi"] < 8950


def test_emi_missing_principal_fails_gracefully():
    plugin = EMICalculatorPlugin()
    application = LoanApplication(tenure_months=12)

    result = plugin.run(application)

    assert not result.success
    assert "principal" in result.error.lower() or "tenure" in result.error.lower()


def test_emi_zero_interest_rate():
    plugin = EMICalculatorPlugin()
    application = LoanApplication(requested_amount=120000, tenure_months=12)

    result = plugin.run(application, annual_rate=0.0)

    assert result.success
    assert result.data["emi"] == 10000.0
