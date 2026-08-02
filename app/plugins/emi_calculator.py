"""EMI calculation using the standard reducing-balance formula."""
from __future__ import annotations

from app.core.schemas import LoanApplication, PluginResult
from app.plugins.base import Plugin

DEFAULT_ANNUAL_INTEREST_RATE = 10.5  # percent, illustrative demo rate


class EMICalculatorPlugin(Plugin):
    name = "emi_calculator"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        principal = kwargs.get("principal") or application.requested_amount
        tenure_months = kwargs.get("tenure_months") or application.tenure_months
        annual_rate = kwargs.get("annual_rate", DEFAULT_ANNUAL_INTEREST_RATE)

        if not principal or not tenure_months:
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="Missing principal amount or tenure to calculate EMI",
            )

        monthly_rate = annual_rate / 12 / 100
        if monthly_rate == 0:
            emi = principal / tenure_months
        else:
            emi = (
                principal
                * monthly_rate
                * (1 + monthly_rate) ** tenure_months
                / ((1 + monthly_rate) ** tenure_months - 1)
            )

        total_payment = emi * tenure_months
        total_interest = total_payment - principal

        return PluginResult(
            plugin_name=self.name,
            success=True,
            data={
                "principal": principal,
                "annual_rate": annual_rate,
                "tenure_months": tenure_months,
                "emi": round(emi, 2),
                "total_payment": round(total_payment, 2),
                "total_interest": round(total_interest, 2),
            },
        )
