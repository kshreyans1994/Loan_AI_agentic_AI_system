import json
from unittest.mock import MagicMock, patch

from app.agents.intent_agent import intent_agent
from app.core.schemas import AgentState, ChatMessage, Intent, QueryCategory


def _state(message: str, categories: list[QueryCategory], pending_action=None) -> AgentState:
    return AgentState(
        session_id="s1",
        messages=[ChatMessage(role="user", content=message)],
        selected_categories=categories,
        pending_action=pending_action,
    )


def _mock_llm(content: dict):
    msg = MagicMock()
    msg.content = json.dumps(content)
    llm = MagicMock()
    llm.invoke.return_value = msg
    return llm


def test_policy_only_category_skips_llm_and_selects_no_plugins():
    state = _state("what's your prepayment policy?", [QueryCategory.POLICY_QUERY])
    result = intent_agent(state)
    assert result["selected_plugins"] == []
    assert result["detected_intent"] == Intent.ASK_QUESTION


@patch("app.agents.intent_agent.ChatGroq")
def test_tool_query_selects_specific_plugin(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {"detected_intent": "calculate_emi", "selected_plugins": ["calculate_emi"], "reasoning": "EMI ask"}
    )
    state = _state("EMI on 2 lakh over 24 months?", [QueryCategory.TOOL_QUERY])
    result = intent_agent(state)
    assert result["selected_plugins"] == [Intent.CALCULATE_EMI]


@patch("app.agents.intent_agent.ChatGroq")
def test_compound_tool_query_selects_multiple_plugins(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {
            "detected_intent": "check_eligibility",
            "selected_plugins": ["check_eligibility", "calculate_foir"],
            "reasoning": "eligibility and FOIR",
        }
    )
    state = _state("am I eligible, and what's my FOIR?", [QueryCategory.TOOL_QUERY])
    result = intent_agent(state)
    assert result["selected_plugins"] == [Intent.CHECK_ELIGIBILITY, Intent.CALCULATE_FOIR]


@patch("app.agents.intent_agent.ChatGroq")
def test_invalid_intents_dropped_not_crashed(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {"detected_intent": "check_eligibility", "selected_plugins": ["check_eligibility", "not_real"]}
    )
    state = _state("am I eligible?", [QueryCategory.TOOL_QUERY])
    result = intent_agent(state)
    assert result["selected_plugins"] == [Intent.CHECK_ELIGIBILITY]


@patch("app.agents.intent_agent.ChatGroq")
def test_document_intent_dropped_without_pending_action(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {"detected_intent": "upload_document", "selected_plugins": ["upload_document"]}
    )
    state = _state("here's my slip", [QueryCategory.DOCUMENT_QUERY], pending_action=None)
    result = intent_agent(state)
    assert result["selected_plugins"] == []


@patch("app.agents.intent_agent.ChatGroq")
def test_document_intent_kept_with_pending_action(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {"detected_intent": "upload_document", "selected_plugins": ["upload_document"]}
    )
    state = _state("here's my slip", [QueryCategory.DOCUMENT_QUERY], pending_action=b"bytes")
    result = intent_agent(state)
    assert result["selected_plugins"] == [Intent.UPLOAD_DOCUMENT]


@patch("app.agents.intent_agent.ChatGroq")
def test_malformed_output_falls_back_to_ask_question(mock_chatgroq):
    msg = MagicMock()
    msg.content = "not json"
    llm = MagicMock()
    llm.invoke.return_value = msg
    mock_chatgroq.return_value = llm

    state = _state("blah", [QueryCategory.TOOL_QUERY])
    result = intent_agent(state)
    assert result["detected_intent"] == Intent.ASK_QUESTION
    assert result["selected_plugins"] == []
