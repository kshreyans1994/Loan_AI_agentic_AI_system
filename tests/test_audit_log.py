from unittest.mock import MagicMock, patch

from app.core.schemas import AgentState, Intent
from app.db.audit_log import write_audit_log


def test_write_audit_log_uses_fast_connect_timeout():
    state = AgentState(
        session_id="s1",
        detected_intent=Intent.ASK_QUESTION,
        risk_score=0.0,
    )
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False

    with patch("app.db.audit_log.psycopg.connect", return_value=conn) as mock_connect:
        result = write_audit_log(state)

    assert result == {}
    _, kwargs = mock_connect.call_args
    assert kwargs["connect_timeout"] == 1
