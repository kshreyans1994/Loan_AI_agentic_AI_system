"""Offer recommendation plugin — suggests loan products based on the
applicant's income, credit band, and requested amount. Rule-based tiers
for the same reason eligibility is rule-based: explainability."""
from __future__ import annotations

from app.core.schemas import LoanApplication, PluginResult

OFFER_TIERS = [
    {"min_credit_score": 750, "rate": 9.5, "label": "Prime"},
    {"min_credit_score": 650, "rate": 11.5, "label": "Standard"},
    {"min_credit_score": 550, "rate": 14.0, "label": "Subprime"},
]


class OfferRecommendationPlugin:
    name = "offer_recommendation"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        if application.credit_score is None:
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="Credit score required to recommend offers",
            )

        tier = next(
            (t for t in OFFER_TIERS if application.credit_score >= t["min_credit_score"]),
            None,
        )
        if tier is None:
            return PluginResult(
                plugin_name=self.name,
                success=True,
                data={"offers": [], "note": "No offers available at current credit score"},
            )

        max_amount = (application.monthly_income or 0) * 15
        offers = [
            {
                "tier": tier["label"],
                "interest_rate": tier["rate"],
                "max_amount": round(max_amount, 2),
                "max_tenure_months": 60,
            }
        ]

        return PluginResult(plugin_name=self.name, success=True, data={"offers": offers})
