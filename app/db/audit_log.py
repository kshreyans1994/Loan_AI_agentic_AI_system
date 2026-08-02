"""
Decision audit log.

Writes one row to decision_audit_log (see app/db/schema.sql) per turn
that reaches the decision agent — "why did this response go out" needs
a reproducible record, same reasoning as the deterministic plugins
themselves (see docs/ARCHITECTURE.md §7). Runs regardless of whether
user_id is set (unlike long-term memory, which is opt-in per caller) —
an audit trail exists for anonymous sessions too; only long-term
*personalization* is opt-in, not compliance logging.

Fails silently (logs a warning, doesn't raise) if Postgres is
unreachable — a database outage in the audit-logging path shouldn't
take down the actual user-facing response, though a production
deployment would want this on a monitored dead-letter queue rather
than a bare log line.
"""
from __future__ import annotations

import json
import logging

import psycopg

from app.core.config import get_settings
from app.core.schemas import AgentState

logger = logging.getLogger(__name__)


def write_audit_log(state: AgentState) -> dict:
    if state.risk_score is None:
        # Guardrail-blocked turns never reach the decision agent, so
        # there's nothing decision-related to audit for them — the
        # guardrail's own block IS the auditable event, logged by
        # whatever's calling this graph (e.g. request logging in
        # app/api/routes.py), not duplicated here.
        return {}

    settings = get_settings()
    try:
        with psycopg.connect(settings.postgres_dsn, autocommit=True, connect_timeout=1) as conn:
            conn.execute(
                """
                INSERT INTO decision_audit_log (
                    session_id, user_id, detected_intent, selected_plugins,
                    plugin_results, risk_score, risk_factors,
                    required_human_review, human_decision, human_feedback,
                    output_guardrail_allowed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    state.session_id,
                    state.user_id,
                    state.detected_intent.value if state.detected_intent else None,
                    json.dumps([p.value for p in state.selected_plugins]),
                    json.dumps([r.model_dump() for r in state.plugin_results]),
                    state.risk_score,
                    json.dumps(state.risk_factors),
                    state.requires_human_review,
                    state.human_decision,
                    state.human_feedback,
                    state.output_guardrail_allowed,
                ),
            )
    except psycopg.Error as exc:
        logger.warning(
            "Audit persistence skipped for session=%s: Postgres unavailable. Chat response continues; audit write was not saved. Error=%s",
            state.session_id,
            exc,
        )

    return {}
