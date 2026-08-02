"""Interest rate service.

Computes the applicant's rate as repo_rate + a credit-score-tiered
spread — the standard external-benchmark-linked-rate structure Indian
lenders use post-2019 RBI mandate. Deterministic: the spread table
below is the only thing that decides the number, same reasoning as
every other plugin here that touches a number that ends up in front of
an applicant.
"""
from __future__ import annotations

from app.core.schemas import LoanApplication, PluginResult
from app.plugins.base import Plugin
from app.plugins.repo_rate_service import CURRENT_REPO_RATE

# (min_credit_score, spread_percent) — first matching band wins, checked
# highest score first. Illustrative, not a real rate card.
_SPREAD_BANDS = [
    (750, 2.00),
    (700, 2.75),
    (650, 3.75),
    (0, 5.50),  # below the eligibility cutoff, but still quotable if asked
]


def _spread_for_score(credit_score: int) -> float:
    for min_score, spread in _SPREAD_BANDS:
        if credit_score >= min_score:
            return spread
    return _SPREAD_BANDS[-1][1]


class InterestRateServicePlugin(Plugin):
    name = "interest_rate_service"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        credit_score = kwargs.get("credit_score") or application.credit_score
        if credit_score is None:
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="Missing credit score to determine interest rate spread",
            )

        spread = _spread_for_score(credit_score)
        applicable_rate = round(CURRENT_REPO_RATE + spread, 2)

        return PluginResult(
            plugin_name=self.name,
            success=True,
            data={
                "repo_rate_percent": CURRENT_REPO_RATE,
                "credit_score": credit_score,
                "spread_percent": spread,
                "applicable_rate_percent": applicable_rate,
            },
        )
