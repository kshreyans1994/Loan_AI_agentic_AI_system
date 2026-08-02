"""
External analyzer ingestion plugin.

Adapts JSON output from your EXISTING, separately-built bank statement
analyzer and financial statement analyzer services into this project's
internal schema, then applies it to the LoanApplication as an income
signal.

This is intentionally a thin adapter, not a re-implementation of your
analyzers — the actual analysis (parsing bank statements, computing cash
flow) already happened in your other service. This plugin's only job is:
    1. Normalize whatever field names your service uses into our schema
    2. Decide precedence when multiple income signals exist
    3. Attach the result to state.application so eligibility_check can use it

WHY THIS SITS IN plugins/, NOT agents/:
It follows the same pattern as document_verifier.py — a plugin wraps an
external capability (there: OCR+VLM; here: your analyzer service output)
behind the same Plugin interface, so the graph's plugin-execution node
doesn't need special-casing for it.

ADAPTING TO YOUR ACTUAL JSON SHAPE:
The `_map_bank_statement_payload` / `_map_financial_statement_payload`
functions below are where you translate YOUR service's actual field
names into ours. Everything else in this file is shape-agnostic — you
should only need to edit those two functions to match your real output.
"""
from __future__ import annotations

from typing import Any

from app.core.schemas import (
    BankStatementAnalysis,
    ExternalAnalyzerSource,
    FinancialStatementAnalysis,
    LoanApplication,
    PluginResult,
)

# Precedence when multiple income signals are available for the same
# applicant, highest confidence first. A dedicated financial-statement
# analysis (audited-ish, multi-period) generally beats bank-statement
# cash-flow analysis, which in turn beats a single salary slip's OCR'd
# net_pay figure (one document, one month, OCR error risk).
INCOME_SOURCE_PRECEDENCE = [
    ExternalAnalyzerSource.FINANCIAL_STATEMENT_ANALYZER.value,
    ExternalAnalyzerSource.BANK_STATEMENT_ANALYZER.value,
    "salary_slip_ocr",
]


def _source_rank(source: str | None) -> int:
    """Lower index = higher precedence. Unknown sources rank last."""
    try:
        return INCOME_SOURCE_PRECEDENCE.index(source)
    except ValueError:
        return len(INCOME_SOURCE_PRECEDENCE)


def _map_bank_statement_payload(raw: dict[str, Any]) -> BankStatementAnalysis:
    """
    EDIT THIS to match your actual bank-statement-analyzer output keys.
    Shown below is a plausible guess at field names based on common
    bank-statement-analyzer conventions — adjust the .get() keys on the
    left to whatever your service actually emits.
    """
    return BankStatementAnalysis(
        average_monthly_credit=float(raw.get("avg_monthly_credit", raw.get("average_credit", 0))),
        average_monthly_debit=float(raw.get("avg_monthly_debit", raw.get("average_debit", 0))),
        average_monthly_balance=raw.get("avg_monthly_balance"),
        bounced_transactions_count=int(raw.get("bounced_count", raw.get("cheque_bounces", 0))),
        statement_period_months=int(raw.get("period_months", raw.get("months_analyzed", 6))),
        net_monthly_cash_flow=float(
            raw.get("net_monthly_cash_flow")
            or (
                float(raw.get("avg_monthly_credit", raw.get("average_credit", 0)))
                - float(raw.get("avg_monthly_debit", raw.get("average_debit", 0)))
            )
        ),
        raw=raw,
    )


def _map_financial_statement_payload(raw: dict[str, Any]) -> FinancialStatementAnalysis:
    """
    EDIT THIS to match your actual financial-statement-analyzer output
    keys. Same pattern as above — adjust .get() keys on the left.
    """
    annual_revenue = raw.get("annual_revenue") or raw.get("total_revenue")
    net_profit = raw.get("net_profit") or raw.get("profit_after_tax")

    derived_monthly = raw.get("derived_monthly_income")
    if derived_monthly is None and net_profit is not None:
        derived_monthly = float(net_profit) / 12

    return FinancialStatementAnalysis(
        annual_revenue=annual_revenue,
        net_profit=net_profit,
        debt_to_income_ratio=raw.get("debt_to_income_ratio"),
        fiscal_year=raw.get("fiscal_year") or raw.get("fy"),
        derived_monthly_income=float(derived_monthly or 0),
        raw=raw,
    )


class ExternalAnalyzerIngestPlugin:
    """
    Two entry points — bank statement and financial statement — kept as
    one plugin since they share the same precedence/attachment logic and
    are both "external analyzer ingestion", just different source types.
    """
    name = "external_analyzer_ingest"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        analyzer_type = kwargs.get("analyzer_type")  # "bank_statement" | "financial_statement"
        payload = kwargs.get("payload")

        if analyzer_type not in ("bank_statement", "financial_statement"):
            return PluginResult(
                plugin_name=self.name,
                success=False,
                error="analyzer_type must be 'bank_statement' or 'financial_statement'",
            )
        if not payload or not isinstance(payload, dict):
            return PluginResult(
                plugin_name=self.name, success=False, error="Missing or invalid payload JSON"
            )

        if analyzer_type == "bank_statement":
            analysis = _map_bank_statement_payload(payload)
            candidate_income = analysis.net_monthly_cash_flow
            source = analysis.source.value
            attach = {"bank_statement_analysis": analysis}
        else:
            analysis = _map_financial_statement_payload(payload)
            candidate_income = analysis.derived_monthly_income
            source = analysis.source.value
            attach = {"financial_statement_analysis": analysis}

        # Precedence check: only overwrite monthly_income if this source
        # outranks whatever is currently set (or nothing is set yet).
        current_rank = _source_rank(application.income_signal_source)
        candidate_rank = _source_rank(source)

        income_updated = False
        if candidate_income and candidate_rank <= current_rank:
            attach["monthly_income"] = candidate_income
            attach["income_signal_source"] = source
            income_updated = True

        return PluginResult(
            plugin_name=self.name,
            success=True,
            data={
                "analyzer_type": analyzer_type,
                "candidate_monthly_income": candidate_income,
                "income_updated": income_updated,
                "reason": (
                    f"Applied as new income signal (source={source})"
                    if income_updated
                    else f"Not applied — existing signal '{application.income_signal_source}' "
                    f"has equal or higher precedence"
                ),
                "application_updates": attach,  # consumed by plugin_executor to patch state.application
            },
        )
