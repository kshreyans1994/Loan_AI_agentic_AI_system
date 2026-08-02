"""
Plugin registry.

Maps Intent -> Plugin so the graph's plugin-execution node can dispatch
without an if/elif chain. Adding a new plugin means registering it here
plus adding the intent to core.schemas.Intent — no changes to the graph.
"""
from __future__ import annotations

from app.core.schemas import Intent
from app.plugins.base import Plugin
from app.plugins.credit_score import CreditScorePlugin
from app.plugins.document_verifier import DocumentVerifierPlugin
from app.plugins.eligibility_check import EligibilityCheckPlugin
from app.plugins.emi_calculator import EMICalculatorPlugin
from app.plugins.external_analyzer_ingest import ExternalAnalyzerIngestPlugin
from app.plugins.foir_calculator import FOIRCalculatorPlugin
from app.plugins.interest_rate_service import InterestRateServicePlugin
from app.plugins.offer_recommendation import OfferRecommendationPlugin
from app.plugins.repo_rate_service import RepoRateServicePlugin

_external_analyzer_plugin = ExternalAnalyzerIngestPlugin()

PLUGIN_REGISTRY: dict[Intent, Plugin] = {
    Intent.CHECK_ELIGIBILITY: EligibilityCheckPlugin(),
    Intent.CALCULATE_EMI: EMICalculatorPlugin(),
    Intent.CALCULATE_FOIR: FOIRCalculatorPlugin(),
    Intent.CHECK_REPO_RATE: RepoRateServicePlugin(),
    Intent.CHECK_INTEREST_RATE: InterestRateServicePlugin(),
    Intent.CHECK_CREDIT_SCORE: CreditScorePlugin(),
    Intent.UPLOAD_DOCUMENT: DocumentVerifierPlugin(),
    Intent.SUBMIT_BANK_STATEMENT_ANALYSIS: _external_analyzer_plugin,
    Intent.SUBMIT_FINANCIAL_STATEMENT_ANALYSIS: _external_analyzer_plugin,
}

# Not intent-triggered directly — invoked explicitly once eligibility passes
OFFER_PLUGIN = OfferRecommendationPlugin()


def get_plugin_for_intent(intent: Intent) -> Plugin | None:
    return PLUGIN_REGISTRY.get(intent)
