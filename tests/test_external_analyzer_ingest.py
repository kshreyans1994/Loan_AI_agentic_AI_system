from app.core.schemas import LoanApplication
from app.plugins.external_analyzer_ingest import (
    ExternalAnalyzerIngestPlugin,
    _map_bank_statement_payload,
    _map_financial_statement_payload,
    _source_rank,
)


def test_bank_statement_payload_mapping_basic_keys():
    raw = {
        "avg_monthly_credit": 60000,
        "avg_monthly_debit": 20000,
        "period_months": 6,
        "bounced_count": 1,
    }
    analysis = _map_bank_statement_payload(raw)
    assert analysis.average_monthly_credit == 60000
    assert analysis.net_monthly_cash_flow == 40000
    assert analysis.bounced_transactions_count == 1


def test_financial_statement_payload_derives_monthly_from_net_profit():
    raw = {"annual_revenue": 1200000, "net_profit": 600000, "fiscal_year": "2025-26"}
    analysis = _map_financial_statement_payload(raw)
    assert analysis.derived_monthly_income == 50000.0


def test_first_income_signal_is_applied_when_none_exists():
    plugin = ExternalAnalyzerIngestPlugin()
    application = LoanApplication()  # no income_signal_source yet

    result = plugin.run(
        application,
        analyzer_type="bank_statement",
        payload={"avg_monthly_credit": 50000, "avg_monthly_debit": 10000, "period_months": 6},
    )

    assert result.success
    assert result.data["income_updated"] is True
    assert result.data["application_updates"]["monthly_income"] == 40000


def test_financial_statement_outranks_bank_statement():
    plugin = ExternalAnalyzerIngestPlugin()
    application = LoanApplication(monthly_income=40000, income_signal_source="bank_statement_analyzer")

    result = plugin.run(
        application,
        analyzer_type="financial_statement",
        payload={"net_profit": 720000},  # -> 60000/month
    )

    assert result.data["income_updated"] is True
    assert result.data["application_updates"]["monthly_income"] == 60000.0


def test_bank_statement_does_not_override_financial_statement():
    plugin = ExternalAnalyzerIngestPlugin()
    application = LoanApplication(
        monthly_income=60000, income_signal_source="financial_statement_analyzer"
    )

    result = plugin.run(
        application,
        analyzer_type="bank_statement",
        payload={"avg_monthly_credit": 50000, "avg_monthly_debit": 10000},
    )

    assert result.data["income_updated"] is False
    assert "application_updates" in result.data
    assert "monthly_income" not in result.data["application_updates"]


def test_missing_payload_fails_gracefully():
    plugin = ExternalAnalyzerIngestPlugin()
    result = plugin.run(LoanApplication(), analyzer_type="bank_statement", payload=None)
    assert not result.success


def test_invalid_analyzer_type_fails_gracefully():
    plugin = ExternalAnalyzerIngestPlugin()
    result = plugin.run(LoanApplication(), analyzer_type="something_else", payload={})
    assert not result.success


def test_source_rank_unknown_source_ranks_last():
    assert _source_rank("some_unrecognized_source") > _source_rank("salary_slip_ocr")
