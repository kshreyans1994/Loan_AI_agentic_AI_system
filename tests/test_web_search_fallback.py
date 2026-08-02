from app.agents.web_search import _rag_context_is_thin
from app.core.schemas import RetrievedChunk


def test_no_rag_context_is_thin():
    assert _rag_context_is_thin_state(retrieved_context=[]) is True


def test_low_score_rag_context_is_thin():
    chunks = [RetrievedChunk(content="x", source="y", score=0.2)]
    assert _rag_context_is_thin_state(retrieved_context=chunks) is True


def test_high_score_rag_context_is_not_thin():
    chunks = [RetrievedChunk(content="x", source="y", score=0.8)]
    assert _rag_context_is_thin_state(retrieved_context=chunks) is False


def test_mixed_scores_uses_max_not_average():
    # One strong hit should be enough even if others are weak
    chunks = [
        RetrievedChunk(content="a", source="s1", score=0.1),
        RetrievedChunk(content="b", source="s2", score=0.9),
    ]
    assert _rag_context_is_thin_state(retrieved_context=chunks) is False


def _rag_context_is_thin_state(retrieved_context):
    from app.core.schemas import AgentState

    state = AgentState(session_id="test-session", retrieved_context=retrieved_context)
    return _rag_context_is_thin(state)
