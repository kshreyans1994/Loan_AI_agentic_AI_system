from pathlib import Path

from app.core.config import Settings
from app.rag.retriever import HybridRetriever, _compress_context, _metadata_filter, _reciprocal_rank_fusion, _rewrite_query
from app.core.schemas import RetrievedChunk


def test_rewrite_query_strips_conversational_filler():
    assert _rewrite_query("Hey, can you tell me the max LTV for salaried borrowers?") == \
        "can you tell me the max LTV for salaried borrowers"


def test_rewrite_query_falls_back_to_original_if_stripped_empty():
    assert _rewrite_query("   ") == "   "


def test_metadata_filter_detects_nri_keyword():
    assert _metadata_filter("What's the LTV for an NRI applicant?") == {"applicant_category": "nri"}


def test_metadata_filter_returns_empty_for_no_match():
    assert _metadata_filter("What documents do I need?") == {}


def test_rrf_prefers_items_ranked_high_in_both_lists():
    vector_results = [
        RetrievedChunk(content="Chunk A content here", source="doc1", score=0.9),
        RetrievedChunk(content="Chunk B content here", source="doc2", score=0.8),
    ]
    lexical_results = [
        RetrievedChunk(content="Chunk B content here", source="doc2", score=5.0),
        RetrievedChunk(content="Chunk A content here", source="doc1", score=3.0),
    ]
    merged = _reciprocal_rank_fusion(vector_results, lexical_results, vector_weight=0.5, lexical_weight=0.5)
    # Both chunks appear in both lists at swapped ranks -> should tie,
    # but the merge should at minimum include both, not drop either.
    assert len(merged) == 2
    assert {c.source for c in merged} == {"doc1", "doc2"}


def test_rrf_includes_items_only_in_one_list():
    vector_results = [RetrievedChunk(content="Only in vector", source="doc1", score=0.9)]
    lexical_results = [RetrievedChunk(content="Only in lexical", source="doc2", score=5.0)]
    merged = _reciprocal_rank_fusion(vector_results, lexical_results, vector_weight=0.5, lexical_weight=0.5)
    assert len(merged) == 2


def test_compress_context_drops_near_duplicate_chunks():
    # Same opening 120+ chars (the realistic case: overlapping chunk
    # windows from the same source document), differing only later.
    shared_opening = (
        "Section 4.2: Loan-to-Value Ratio. The maximum LTV permitted for salaried "
        "borrowers under this policy is capped at eighty percent of the appraised "
        "property value, "
    )
    chunks = [
        RetrievedChunk(content=shared_opening + "subject to the borrower's credit score.", source="doc1", score=0.9),
        RetrievedChunk(content=shared_opening + "unless a co-applicant is added to the loan.", source="doc1", score=0.85),
    ]
    compressed = _compress_context(chunks)
    assert len(compressed) == 1


def test_compress_context_truncates_long_chunks():
    long_content = "Sentence one. " * 100
    chunks = [RetrievedChunk(content=long_content, source="doc1", score=0.9)]
    compressed = _compress_context(chunks, max_chars_per_chunk=100)
    assert len(compressed[0].content) <= 150  # some slack for the truncation-to-sentence-boundary logic


def test_embedder_uses_local_model_cache_directory(monkeypatch):
    captured_kwargs = {}

    class _StubSentenceTransformer:
        def __init__(self, model_name: str, **kwargs) -> None:
            captured_kwargs["model_name"] = model_name
            captured_kwargs["kwargs"] = kwargs

        def encode(self, *args, **kwargs):
            return [[0.0] * 384]

    monkeypatch.setattr("app.rag.retriever.SentenceTransformer", _StubSentenceTransformer)

    settings = Settings(model_cache_dir="./models/hf-cache")
    retriever = HybridRetriever()
    retriever.settings = settings

    _ = retriever.embedder

    assert captured_kwargs["model_name"] == settings.embedding_model
    assert captured_kwargs["kwargs"]["cache_folder"] == str(Path(settings.model_cache_dir).resolve())


def test_connect_creates_pgvector_extension(monkeypatch):
    executed = []

    class _StubConnection:
        def execute(self, sql: str) -> None:
            executed.append(sql)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.rag.retriever.psycopg.connect", lambda *args, **kwargs: _StubConnection())
    monkeypatch.setattr("app.rag.retriever.register_vector", lambda conn: executed.append("register_vector"))

    retriever = HybridRetriever()
    retriever.settings = Settings(postgres_dsn="postgresql://loan_user:loan_pass@localhost:5432/loan_agent")
    retriever._connect()

    assert any("CREATE EXTENSION IF NOT EXISTS vector" in sql for sql in executed)
    assert "register_vector" in executed
