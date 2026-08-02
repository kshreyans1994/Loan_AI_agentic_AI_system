"""Repo rate service.

Returns the current RBI repo rate used as the base for interest-rate
calculations. Config-driven rather than a live RBI API call — same
"deterministic and clearly labeled" pattern as CreditScorePlugin's
mocked bureau lookup. Swap `CURRENT_REPO_RATE` for a real scheduled
fetch/webhook update in production; the plugin interface doesn't change.
"""
from __future__ import annotations

from datetime import date

from app.core.schemas import LoanApplication, PluginResult
from app.plugins.base import Plugin

# NOTE: illustrative value, not live. Update this constant (or wire it to
# a real RBI rate feed) rather than hardcoding a rate anywhere else in
# the codebase — this is the single source of truth for it.
CURRENT_REPO_RATE = 6.50
_LAST_REVISED = date(2025, 2, 7)


class RepoRateServicePlugin(Plugin):
    name = "repo_rate_service"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        return PluginResult(
            plugin_name=self.name,
            success=True,
            data={
                "repo_rate_percent": CURRENT_REPO_RATE,
                "last_revised": _LAST_REVISED.isoformat(),
                "source": "mocked — not a live RBI feed, see repo_rate_service.py",
            },
        )
