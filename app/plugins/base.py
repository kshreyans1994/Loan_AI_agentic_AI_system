"""
Plugin base interface.

Plugins are self-contained, independently testable units of business
logic (EMI math, eligibility rules, credit score lookup) that the
orchestration graph invokes based on detected intent. This mirrors the
diagram's "Plugin Execution" step and keeps business rules out of the
LLM prompt — the LLM decides *what* to call, deterministic code decides
*how* the calculation is done.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.schemas import LoanApplication, PluginResult


class Plugin(ABC):
    name: str

    @abstractmethod
    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        ...
