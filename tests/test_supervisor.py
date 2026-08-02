import json
from unittest.mock import MagicMock, patch

from app.agents.supervisor import supervisor_agent
from app.core.schemas import AgentState, ChatMessage, QueryCategory


def _state(message: str, pending_action=None) -> AgentState:
    return AgentState(
        session_id="s1",
        messages=[ChatMessage(role="user", content=message)],
        pending_action=pending_action,
    )


def _mock_llm(content: dict):
    msg = MagicMock()
    msg.content = json.dumps(content)
    llm = MagicMock()
    llm.invoke.return_value = msg
    return llm


@patch("app.agents.supervisor.ChatGroq")
def test_single_category_selection(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {"selected_categories": ["tool_query"], "reasoning": "user wants EMI"}
    )
    result = supervisor_agent(_state("What's my EMI on 2 lakh over 24 months?"))
    assert result["selected_categories"] == [QueryCategory.TOOL_QUERY]


@patch("app.agents.supervisor.ChatGroq")
def test_compound_message_selects_multiple_categories(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {
            "selected_categories": ["tool_query", "policy_query"],
            "reasoning": "eligibility check plus a policy question",
        }
    )
    result = supervisor_agent(_state("Am I eligible, and what's your prepayment policy?"))
    assert result["selected_categories"] == [QueryCategory.TOOL_QUERY, QueryCategory.POLICY_QUERY]


@patch("app.agents.supervisor.ChatGroq")
def test_invalid_category_values_are_dropped_not_crashed(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm(
        {"selected_categories": ["tool_query", "not_a_real_category"]}
    )
    result = supervisor_agent(_state("am I eligible?"))
    assert result["selected_categories"] == [QueryCategory.TOOL_QUERY]


@patch("app.agents.supervisor.ChatGroq")
def test_document_query_dropped_without_pending_action(mock_chatgroq):
    # LLM hallucinates an upload category even though nothing was attached.
    mock_chatgroq.return_value = _mock_llm({"selected_categories": ["document_query"]})
    result = supervisor_agent(_state("here's my salary slip", pending_action=None))
    assert result["selected_categories"] == []


@patch("app.agents.supervisor.ChatGroq")
def test_document_query_kept_with_pending_action(mock_chatgroq):
    mock_chatgroq.return_value = _mock_llm({"selected_categories": ["document_query"]})
    result = supervisor_agent(_state("here's my salary slip", pending_action=b"fake-bytes"))
    assert result["selected_categories"] == [QueryCategory.DOCUMENT_QUERY]


@patch("app.agents.supervisor.ChatGroq")
def test_malformed_llm_output_falls_back_to_policy_query(mock_chatgroq):
    msg = MagicMock()
    msg.content = "not valid json"
    llm = MagicMock()
    llm.invoke.return_value = msg
    mock_chatgroq.return_value = llm

    result = supervisor_agent(_state("blah blah"))
    assert result["selected_categories"] == [QueryCategory.POLICY_QUERY]


def test_no_user_message_selects_nothing_without_calling_llm():
    state = AgentState(session_id="s1", messages=[])
    result = supervisor_agent(state)
    assert result["selected_categories"] == []
