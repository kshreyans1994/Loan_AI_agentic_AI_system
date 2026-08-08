"""
Hybrid RAG retrieval layer, backed by Postgres + pgvector for dense
search and Postgres full-text search (tsvector/ts_rank_cd) for lexical
search — this is the "BM25 Index" branch in the diagram, implemented as
Postgres full-text search rather than a separate in-memory BM25 library
(rank_bm25 et al. need to rebuild their index from scratch per query
unless you maintain a persistent index yourself; Postgres already
persists and indexes a tsvector column via GIN, which is the more
"production-ready" choice here given we're already running Postgres for
everything else — one fewer moving part, not a different algorithm
family in spirit (ts_rank_cd is a BM25-family lexical ranking function).

Pipeline (mirrors the diagram's Hybrid RAG Flow exactly):

  query -> query_rewriter -> metadata_filter -> [vector_search,
  lexical_search] -> merge (Reciprocal Rank Fusion) -> rerank
  (cross-encoder) -> context_compression -> caller (rag_retrieval.py)

These live as private methods on one class rather than separate graph
nodes — the top-level graph diagram (see docs/ARCHITECTURE.md §2)
collapses all of this into a single "RAG Agent" node, same as the
reference Query Flow diagram does. Splitting each of these seven steps
into its own LangGraph node would add graph-traversal overhead for
work that's inherently sequential and has no branching point a human
reviewer or another agent would ever need to intervene on mid-way.

Each step degrades gracefully rather than failing the whole retrieval:
a broken reranker model load skips reranking (falls back to RRF order)
rather than raising; an empty lexical or vector result just contributes
nothing to the merge rather than short-circuiting it.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.core.schemas import RetrievedChunk

# Very small, deliberately conservative heuristic — only fires on
# unambiguous keywords, so it can't accidentally filter out relevant
# results on a query it doesn't recognize. A production system would
# likely replace this with an LLM call or a proper query-tagging model;
# kept deterministic here to avoid a fourth LLM call on every RAG turn.
_METADATA_KEYWORD_FILTERS = {
    "nri": {"applicant_category": "nri"},
    "self employed": {"applicant_category": "self_employed"},
    "self-employed": {"applicant_category": "self_employed"},
    "co-applicant": {"topic": "co_applicant"},
    "prepayment": {"topic": "prepayment"},
    "foreclosure": {"topic": "prepayment"},
}

# Reciprocal Rank Fusion constant — standard default from the original
# RRF paper (Cormack et al.), not tuned for this dataset specifically.
_RRF_K = 60
logger = logging.getLogger("app.rag.retriever")


def _rewrite_query(raw_query: str) -> str:
    """Deterministic query cleanup: strips conversational filler so the
    retrieval query is closer to how policy documents are actually
    phrased. Kept rule-based (not an LLM call) — an LLM rewrite adds
    latency and cost to every RAG turn for a gain that's marginal on
    short, already-fairly-clean loan questions; revisit if retrieval
    quality on real user phrasing turns out to need it."""
    cleaned = re.sub(
        r"^(hey|hi|hello|so|umm?|can you|could you|please)\b[,\s]*",
        "",
        raw_query.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\?+$", "", cleaned).strip()
    return cleaned or raw_query


def _metadata_filter(query: str) -> dict:
    filters: dict = {}
    lowered = query.lower()
    for keyword, filter_dict in _METADATA_KEYWORD_FILTERS.items():
        if keyword in lowered:
            filters.update(filter_dict)
    return filters


def _reciprocal_rank_fusion(
    vector_results: list[RetrievedChunk],
    lexical_results: list[RetrievedChunk],
    vector_weight: float,
    lexical_weight: float,
) -> list[RetrievedChunk]:
    """Merges two ranked lists into one by rank position, not raw score
    — vector cosine similarity and ts_rank_cd are on incompatible
    scales, so merging by score directly would silently let whichever
    metric happens to produce larger numbers dominate. RRF sidesteps
    that by using each list's RANK instead."""
    scores: dict[str, float] = {}
    chunks_by_key: dict[str, RetrievedChunk] = {}

    for weight, results in ((vector_weight, vector_results), (lexical_weight, lexical_results)):
        for rank, chunk in enumerate(results):
            key = f"{chunk.source}::{chunk.content[:80]}"
            chunks_by_key[key] = chunk
            scores[key] = scores.get(key, 0.0) + weight * (1.0 / (_RRF_K + rank + 1))

    ranked_keys = sorted(scores, key=lambda k: scores[k], reverse=True)
    return [chunks_by_key[k] for k in ranked_keys]


def _compress_context(chunks: list[RetrievedChunk], max_chars_per_chunk: int = 600) -> list[RetrievedChunk]:
    """Two cheap, deterministic compression passes rather than an LLM
    summarization call (which would need to run per-chunk, per-turn):
    drop near-duplicate chunks (common when the same policy point is
    chunked with overlapping windows), and truncate each surviving
    chunk to a sentence boundary near max_chars_per_chunk so the
    response-generation prompt isn't padded with a whole document
    section for one relevant sentence."""
    seen_prefixes: set[str] = set()
    compressed: list[RetrievedChunk] = []

    for chunk in chunks:
        prefix = chunk.content[:120].strip().lower()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)

        content = chunk.content
        if len(content) > max_chars_per_chunk:
            truncated = content[:max_chars_per_chunk]
            last_period = truncated.rfind(". ")
            content = truncated[: last_period + 1] if last_period > 0 else truncated + "..."

        compressed.append(RetrievedChunk(content=content, source=chunk.source, score=chunk.score))

    return compressed


class HybridRetriever:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._embedder: SentenceTransformer | None = None
        self._reranker = None
        self._reranker_load_failed = False

    @property
    def embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            cache_dir = Path(self.settings.model_cache_dir).resolve()
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._embedder = SentenceTransformer(
                self.settings.embedding_model,
                cache_folder=str(cache_dir),
            )
        return self._embedder

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.settings.postgres_dsn, autocommit=True)
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        register_vector(conn)
        return conn

    def embed(self, text: str) -> list[float]:
        return self.embedder.encode(text, normalize_embeddings=True).tolist()

    def upsert_document(self, doc_id: str, content: str, source: str, metadata: dict | None = None) -> None:
        embedding = self.embed(content)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_chunks (id, content, source, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET content = EXCLUDED.content,
                    source = EXCLUDED.source,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
                """,
                (doc_id, content, source, metadata or {}, embedding),
            )

    # --- Individual retrieval steps (public so each is independently
    # testable, even though normal callers just use retrieve_hybrid) ---

    def vector_search(self, query: str, top_k: int, metadata_filter: dict) -> list[RetrievedChunk]:
        try:
            query_embedding = self.embed(query)
            where_clause = ""
            params: list = [query_embedding]
            if metadata_filter:
                where_clause = "WHERE metadata @> %s"
                params.append(metadata_filter)
            params.extend([query_embedding, top_k])

            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT content, source, 1 - (embedding <=> %s) AS score
                    FROM knowledge_chunks
                    {where_clause}
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    params,
                ).fetchall()

            return [RetrievedChunk(content=r[0], source=r[1], score=float(r[2])) for r in rows]
        except Exception:
            logger.warning(
                "vector search unavailable; falling back to lexical-only retrieval",
                exc_info=True,
            )
            return []

    def lexical_search(self, query: str, top_k: int, metadata_filter: dict) -> list[RetrievedChunk]:
        """Postgres full-text search over knowledge_chunks.search_vector
        (see schema.sql). ts_rank_cd is the lexical-relevance analogue
        to BM25 here — normalized 0-1-ish score, not directly comparable
        to cosine similarity, which is exactly why merging happens by
        RANK (RRF) rather than by these raw scores."""
        where_clauses = ["search_vector @@ plainto_tsquery('english', %s)"]
        params: list = [query]
        if metadata_filter:
            where_clauses.append("metadata @> %s")
            params.append(metadata_filter)
        params.extend([query, top_k])

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT content, source, ts_rank_cd(search_vector, plainto_tsquery('english', %s)) AS score
                FROM knowledge_chunks
                WHERE {' AND '.join(where_clauses)}
                ORDER BY score DESC
                LIMIT %s
                """,
                params,
            ).fetchall()

        return [RetrievedChunk(content=r[0], source=r[1], score=float(r[2])) for r in rows]

    def rerank(self, query: str, chunks: list[RetrievedChunk], top_n: int) -> list[RetrievedChunk]:
        if not chunks:
            return chunks
        if self._reranker_load_failed:
            return chunks[:top_n]

        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder

                cache_dir = Path(self.settings.model_cache_dir).resolve()
                cache_dir.mkdir(parents=True, exist_ok=True)
                self._reranker = CrossEncoder(
                    self.settings.reranker_model,
                    cache_folder=str(cache_dir),
                )
            except Exception:
                # Model load can fail offline / without HF hub access —
                # degrade to RRF order rather than breaking retrieval.
                self._reranker_load_failed = True
                return chunks[:top_n]

        pairs = [(query, c.content) for c in chunks]
        scores = self._reranker.predict(pairs)
        reranked = [
            RetrievedChunk(content=c.content, source=c.source, score=float(s))
            for c, s in sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
        ]
        return reranked[:top_n]

    def retrieve_hybrid(self, raw_query: str) -> list[RetrievedChunk]:
        s = self.settings
        query = _rewrite_query(raw_query)
        metadata_filter = _metadata_filter(query)

        vector_results = self.vector_search(query, top_k=s.rag_rerank_top_n, metadata_filter=metadata_filter)
        lexical_results = self.lexical_search(query, top_k=s.rag_rerank_top_n, metadata_filter=metadata_filter)

        merged = _reciprocal_rank_fusion(
            vector_results, lexical_results, s.rag_vector_weight, s.rag_lexical_weight
        )
        reranked = self.rerank(query, merged[: s.rag_rerank_top_n], top_n=s.rag_final_top_k)
        return _compress_context(reranked)

    # Kept for callers that just want plain vector search (e.g. a
    # future admin/debug endpoint) without the full hybrid pipeline.
    def retrieve(self, query: str, top_k: int = 5, min_score: float = 0.3) -> list[RetrievedChunk]:
        results = self.vector_search(query, top_k=top_k, metadata_filter={})
        return [r for r in results if r.score >= min_score]


def get_retriever() -> HybridRetriever:
    return HybridRetriever()
