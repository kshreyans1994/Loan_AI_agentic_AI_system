"""FOIR (Fixed Obligation to Income Ratio) calculator.

FOIR = (existing EMIs + proposed EMI) / monthly income * 100. Standard
underwriting metric — most lenders cap FOIR around 40-50% for salaried
applicants. Deterministic, same reasoning as EMICalculatorPlugin: this
number ends up in a real lending decision, so it's arithmetic, not an
LLM guess.
"""
from __future__ import annotations

from app.core.schemas import LoanApplication, PluginResult
from app.plugins.base import Plugin
from app.plugins.emi_calculator import DEFAULT_ANNUAL_INTEREST_RATE

# Most lenders decline or flag above this — used to label the result,
# not to reject outright (that's still EligibilityCheckPlugin's job).
FOIR_CAUTION_THRESHOLD = 40.0
FOIR_HIGH_RISK_THRESHOLD = 55.0


class FOIRCalculatorPlugin(Plugin):
    name = "foir_calculator"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        monthly_income = kwargs.get("monthly_income") or application.monthly_income
        existing_emi = kwargs.get("existing_monthly_emi", application.existing_monthly_emi)
        principal = kwargs.get("principal") or application.requested_amount
        tenure_months = kwargs.get("tenure_months") or application.tenure_months
        annual_rate = kwargs.get("annual_rate", DEFAULT_ANNUAL_INTEREST_RATE)

        if not monthly_income:
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="Missing monthly income to calculate FOIR",
            )
        if not principal or not tenure_months:
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="Missing requested amount or tenure to calculate FOIR",
            )

        monthly_rate = annual_rate / 12 / 100
        if monthly_rate == 0:
            proposed_emi = principal / tenure_months
        else:
            proposed_emi = (
                principal
                * monthly_rate
                * (1 + monthly_rate) ** tenure_months
                / ((1 + monthly_rate) ** tenure_months - 1)
            )

        total_obligation = existing_emi + proposed_emi
        foir = (total_obligation / monthly_income) * 100

        if foir >= FOIR_HIGH_RISK_THRESHOLD:
            band = "high_risk"
        elif foir >= FOIR_CAUTION_THRESHOLD:
            band = "caution"
        else:
            band = "healthy"

        return PluginResult(
            plugin_name=self.name,
            success=True,
            data={
                "monthly_income": monthly_income,
                "existing_monthly_emi": existing_emi,
                "proposed_emi": round(proposed_emi, 2),
                "foir_percent": round(foir, 2),
                "band": band,
                "caution_threshold": FOIR_CAUTION_THRESHOLD,
                "high_risk_threshold": FOIR_HIGH_RISK_THRESHOLD,
            },
        )
