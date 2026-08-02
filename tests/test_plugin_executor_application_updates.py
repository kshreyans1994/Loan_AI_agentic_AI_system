from app.agents.plugin_executor import _application_updates_from_document
from app.core.schemas import AgentState, DocumentType


def _state_with_income_source(source):
    return AgentState(
        session_id="s",
        application={"income_signal_source": source} if source else {},
    )


def test_salary_slip_net_pay_promotes_to_monthly_income():
    state = _state_with_income_source(None)
    result_data = {
        "doc_type": DocumentType.SALARY_SLIP.value,
        "fields": [{"name": "net_pay", "value": "45000", "confidence": 0.9}],
    }
    updates = _application_updates_from_document(state.application, result_data)
    assert updates["monthly_income"] == 45000.0
    assert updates["income_signal_source"] == "salary_slip_ocr"


def test_salary_slip_does_not_override_existing_higher_precedence_income():
    state = _state_with_income_source("financial_statement_analyzer")
    result_data = {
        "doc_type": DocumentType.SALARY_SLIP.value,
        "fields": [{"name": "net_pay", "value": "45000", "confidence": 0.9}],
    }
    updates = _application_updates_from_document(state.application, result_data)
    assert "monthly_income" not in updates


def test_pan_card_promotes_pan_number():
    state = _state_with_income_source(None)
    result_data = {
        "doc_type": DocumentType.PAN.value,
        "fields": [{"name": "pan_number", "value": "ABCDE1234F", "confidence": 0.95}],
    }
    updates = _application_updates_from_document(state.application, result_data)
    assert updates["pan_number"] == "ABCDE1234F"


def test_unrecognized_doc_type_returns_no_updates():
    state = _state_with_income_source(None)
    result_data = {"doc_type": "unknown", "fields": []}
    updates = _application_updates_from_document(state.application, result_data)
    assert updates == {}


def test_malformed_net_pay_value_is_skipped_not_crashed():
    state = _state_with_income_source(None)
    result_data = {
        "doc_type": DocumentType.SALARY_SLIP.value,
        "fields": [{"name": "net_pay", "value": "not-a-number", "confidence": 0.5}],
    }
    updates = _application_updates_from_document(state.application, result_data)
    assert "monthly_income" not in updates
