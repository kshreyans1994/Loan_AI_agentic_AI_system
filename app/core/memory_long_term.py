"""
Long-term memory store.

Deliberately separate from short-term memory (LangGraph's checkpointer,
which handles the running conversation within one session/thread).
Long-term memory answers a different question: "what do we know about
this person from *previous* sessions?" — profile facts (income bracket,
past applications) and rolling conversation summaries.

Kept as plain Postgres reads/writes rather than a vector store: these are
small, structured, per-user fact sets, not a large corpus needing
semantic search. If fact volume per user grows large enough that keyword
lookup stops being enough, this is the seam to swap in pgvector (the
`knowledge_chunks` pattern in app/rag/retriever.py already shows how).
"""
from __future__ import annotations

import logging

import psycopg

from app.core.config import get_settings
from app.core.schemas import LongTermMemoryFact

logger = logging.getLogger(__name__)


class LongTermMemoryStore:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.settings.postgres_dsn, autocommit=True, connect_timeout=1)

    def get_facts(self, user_id: str, limit: int = 20) -> list[LongTermMemoryFact]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT fact, category, confidence
                    FROM user_memory_facts
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                ).fetchall()
        except psycopg.Error as exc:
            logger.warning(
                "Long-term memory recall skipped for user=%s: Postgres unavailable. Continuing without recalled memory. Error=%s",
                user_id,
                exc,
            )
            return []

        return [
            LongTermMemoryFact(fact=row[0], category=row[1], confidence=float(row[2]))
            for row in rows
        ]

    def save_fact(self, user_id: str, fact: LongTermMemoryFact) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO user_memory_facts (user_id, fact, category, confidence)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, fact) DO NOTHING
                    """,
                    (user_id, fact.fact, fact.category, fact.confidence),
                )
        except psycopg.Error as exc:
            logger.warning(
                "Long-term memory save skipped for user=%s: Postgres unavailable. Response continues without memory persistence. Error=%s",
                user_id,
                exc,
            )

    def get_recent_summaries(self, user_id: str, limit: int = 3) -> list[str]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT summary
                    FROM session_summaries
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                ).fetchall()
        except psycopg.Error as exc:
            logger.warning(
                "Session summary recall skipped for user=%s: Postgres unavailable. Continuing without summary recall. Error=%s",
                user_id,
                exc,
            )
            return []
        return [row[0] for row in rows]

    def save_summary(self, user_id: str, session_id: str, summary: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO session_summaries (user_id, session_id, summary)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, session_id, summary),
                )
        except psycopg.Error as exc:
            logger.warning(
                "Session summary save skipped for user=%s: Postgres unavailable. Response continues without summary persistence. Error=%s",
                user_id,
                exc,
            )


def get_long_term_memory_store() -> LongTermMemoryStore:
    return LongTermMemoryStore()
