import logging

import pytest
from langgraph.errors import GraphInterrupt

from app.core.logging_config import _JsonFormatter, _TextFormatter, log_with_session
from app.core.schemas import AgentState
from app.graph.node_tracing import traced


def _make_record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1, msg="hello", args=(), exc_info=None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_text_formatter_includes_session_and_node():
    record = _make_record(session_id="abc123", node="decision_agent", duration_ms=4.2)
    output = _TextFormatter().format(record)
    assert "session=abc123" in output
    assert "decision_agent" in output
    assert "dur=4.2ms" in output


def test_text_formatter_handles_missing_extras_gracefully():
    record = _make_record()
    output = _TextFormatter().format(record)
    assert "hello" in output


def test_json_formatter_produces_valid_json_with_expected_fields():
    import json

    record = _make_record(session_id="abc123", node="decision_agent", duration_ms=4.2)
    parsed = json.loads(_JsonFormatter().format(record))
    assert parsed["session_id"] == "abc123"
    assert parsed["node"] == "decision_agent"
    assert parsed["message"] == "hello"


def test_log_with_session_attaches_session_id(caplog):
    logger = logging.getLogger("test.log_with_session")
    with caplog.at_level(logging.INFO, logger="test.log_with_session"):
        log_with_session(logger, logging.INFO, "sess-1", "something happened", node="my_node")
    assert len(caplog.records) == 1
    assert caplog.records[0].session_id == "sess-1"
    assert caplog.records[0].node == "my_node"


def test_traced_logs_success_and_returns_result(caplog):
    def fake_node(state: AgentState) -> dict:
        return {"guardrail_allowed": True}

    wrapped = traced("guardrail_check", fake_node)
    state = AgentState(session_id="sess-2")

    with caplog.at_level(logging.INFO, logger="app.graph.trace"):
        result = wrapped(state)

    assert result == {"guardrail_allowed": True}
    finished_logs = [r for r in caplog.records if "node finished" in r.getMessage()]
    assert len(finished_logs) == 1
    assert finished_logs[0].node == "guardrail_check"
    assert finished_logs[0].session_id == "sess-2"


def test_traced_logs_and_reraises_real_exceptions(caplog):
    def failing_node(state: AgentState) -> dict:
        raise ValueError("boom")

    wrapped = traced("some_node", failing_node)
    state = AgentState(session_id="sess-3")

    with caplog.at_level(logging.ERROR, logger="app.graph.trace"):
        with pytest.raises(ValueError, match="boom"):
            wrapped(state)

    error_logs = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_logs) == 1
    assert error_logs[0].node == "some_node"


def test_traced_treats_graph_interrupt_as_a_pause_not_an_error(caplog):
    def pausing_node(state: AgentState) -> dict:
        raise GraphInterrupt([])

    wrapped = traced("human_review", pausing_node)
    state = AgentState(session_id="sess-4")

    with caplog.at_level(logging.DEBUG, logger="app.graph.trace"):
        with pytest.raises(GraphInterrupt):
            wrapped(state)

    error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_logs == []
    pause_logs = [r for r in caplog.records if "paused" in r.getMessage()]
    assert len(pause_logs) == 1
    assert pause_logs[0].node == "human_review"


def test_traced_falls_back_to_returned_keys_for_nodes_without_a_highlight_extractor(caplog):
    def unregistered_node(state: AgentState) -> dict:
        return {"some_field": "some_value"}

    wrapped = traced("totally_new_node", unregistered_node)
    state = AgentState(session_id="sess-5")

    with caplog.at_level(logging.INFO, logger="app.graph.trace"):
        wrapped(state)

    finished_logs = [r for r in caplog.records if "node finished" in r.getMessage()]
    assert "some_field" in finished_logs[0].getMessage()
