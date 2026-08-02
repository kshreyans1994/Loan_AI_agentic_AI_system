"""
Eligibility check plugin.

Deliberately rule-based rather than LLM-based: loan eligibility is a
regulated decision that needs to be explainable and auditable, which is
exactly the kind of logic you want OUT of a non-deterministic model and
into code you can unit test and log.
"""
from __future__ import annotations

from app.core.schemas import LoanApplication, PluginResult

MIN_MONTHLY_INCOME = 20000.0
MIN_CREDIT_SCORE = 650
MAX_LOAN_TO_INCOME_MULTIPLIER = 20  # requested amount vs monthly income


class EligibilityCheckPlugin:
    name = "eligibility_check"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        reasons: list[str] = []
        is_eligible = True

        if application.monthly_income is None:
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="Monthly income not available — upload a salary slip first",
            )

        if application.monthly_income < MIN_MONTHLY_INCOME:
            is_eligible = False
            source_note = (
                f" (from {application.income_signal_source})"
                if application.income_signal_source
                else ""
            )
            reasons.append(
                f"Monthly income ₹{application.monthly_income:,.0f}{source_note} is below the "
                f"minimum requirement of ₹{MIN_MONTHLY_INCOME:,.0f}"
            )

        if application.credit_score is not None and application.credit_score < MIN_CREDIT_SCORE:
            is_eligible = False
            reasons.append(
                f"Credit score {application.credit_score} is below the minimum of {MIN_CREDIT_SCORE}"
            )

        if application.requested_amount and application.monthly_income:
            max_eligible = application.monthly_income * MAX_LOAN_TO_INCOME_MULTIPLIER
            if application.requested_amount > max_eligible:
                is_eligible = False
                reasons.append(
                    f"Requested amount ₹{application.requested_amount:,.0f} exceeds the "
                    f"maximum eligible amount of ₹{max_eligible:,.0f} for your income"
                )

        if is_eligible:
            reasons.append("Meets all eligibility criteria")

        return PluginResult(
            plugin_name=self.name,
            success=True,
            data={
                "eligible": is_eligible,
                "reasons": reasons,
                "criteria_checked": {
                    "min_monthly_income": MIN_MONTHLY_INCOME,
                    "min_credit_score": MIN_CREDIT_SCORE,
                    "max_loan_to_income_multiplier": MAX_LOAN_TO_INCOME_MULTIPLIER,
                },
            },
        )
