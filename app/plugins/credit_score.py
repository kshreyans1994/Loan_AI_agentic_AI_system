"""
Credit score plugin.

Real credit bureau APIs (CIBIL, Experian, Equifax) require commercial
agreements and signed consent flows that don't belong in a public demo
repo. This ships a clearly-labeled mock adapter behind the same
interface a real bureau client would implement — swapping in a real
provider means writing one class, not touching the plugin or the graph.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from app.core.schemas import LoanApplication, PluginResult


class CreditBureauClient(ABC):
    @abstractmethod
    def fetch_score(self, pan_number: str) -> int:
        ...


class MockCreditBureauClient(CreditBureauClient):
    """Deterministic pseudo-score derived from PAN hash — demo/testing only."""

    def fetch_score(self, pan_number: str) -> int:
        digest = hashlib.sha256(pan_number.encode()).hexdigest()
        # Map hash to a plausible 300-900 credit score range
        return 300 + (int(digest, 16) % 601)


class CreditScorePlugin:
    name = "credit_score"

    def __init__(self, bureau_client: CreditBureauClient | None = None) -> None:
        self.bureau_client = bureau_client or MockCreditBureauClient()

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        if not application.pan_number:
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="PAN number required to fetch credit score",
            )

        score = self.bureau_client.fetch_score(application.pan_number)
        band = self._score_band(score)

        return PluginResult(
            plugin_name=self.name,
            success=True,
            data={"credit_score": score, "band": band, "source": "mock_bureau"},
        )

    @staticmethod
    def _score_band(score: int) -> str:
        if score >= 750:
            return "excellent"
        if score >= 650:
            return "good"
        if score >= 550:
            return "fair"
        return "poor"
