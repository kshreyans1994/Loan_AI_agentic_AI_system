"""API routes exposing the chat agent over HTTP.

Short-term memory: each session_id maps to a LangGraph checkpointer
"thread" (config={"configurable": {"thread_id": session_id}}). The graph
itself persists message history and state across calls with the same
thread_id — the `_SESSIONS` dict below only tracks which session_ids
we've seen, it is NOT what makes memory work.

Long-term memory: pass a stable `user_id` (e.g. from auth) to get
cross-session recall. Omit it for anonymous/guest chats — the graph's
memory nodes no-op cleanly in that case (see app/agents/long_term_memory.py).
"""
from __future__ import annotations

import uuid

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from langgraph.types import Command
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.object_storage import get_object_storage
from app.core.schemas import AgentState, ChatMessage, Intent
from app.graph.pipeline import compiled_graph

router = APIRouter()
logger = logging.getLogger("app.api.turns")

# Tracks known session_ids only; actual conversation state lives in the
# LangGraph checkpointer, keyed by the same id as `thread_id`.
_KNOWN_SESSIONS: set[str] = set()


class ChatRequest(BaseModel):
    session_id: str | None = None
    user_id: str | None = None  # optional: enables long-term memory
    message: str


class ChatResponse(BaseModel):
    session_id: str
    response: str
    detected_intent: str | None
    plugin_results: list[dict]
    # True when the graph paused on human_review — `response` in that
    # case is a placeholder, not the real answer. The caller must POST
    # to /loan/review with an approve/reject decision to get the real
    # `final_response`. See app/agents/human_review.py for what pauses.
    awaiting_human_review: bool = False
    review_context: dict | None = None


def _thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _interrupt_payload(result: dict) -> dict | None:
    """LangGraph surfaces a paused interrupt() call as result['__interrupt__'],
    a tuple of Interrupt objects. Only one interrupt happens per turn in
    this graph (human_review is the only interrupt() call site), so we
    just take the first one's .value — the dict human_review passed in."""
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


def _to_chat_response(session_id: str, result: dict) -> ChatResponse:
    interrupt_payload = _interrupt_payload(result)
    if interrupt_payload:
        logger.info(
            "turn paused for human review",
            extra={"session_id": session_id, "node": "turn_summary"},
        )
        intent = interrupt_payload.get("detected_intent") or "your request"
        return ChatResponse(
            session_id=session_id,
            response=(
                f"I've routed \"{intent}\" and gathered the relevant data — a human "
                "reviewer needs to confirm this response before I can send it. "
                "I'll answer as soon as that's done."
            ),
            detected_intent=intent,
            plugin_results=interrupt_payload.get("plugin_results", []),
            awaiting_human_review=True,
            review_context=interrupt_payload,
        )

    updated_state = AgentState.model_validate(result)
    if updated_state.final_response:
        updated_state.messages.append(
            ChatMessage(role="assistant", content=updated_state.final_response)
        )
        compiled_graph.update_state(
            _thread_config(session_id),
            {"messages": [ChatMessage(role="assistant", content=updated_state.final_response)]},
        )

    # One line per completed turn — the thing to grep for first when a
    # developer is asking "what actually happened for session X" before
    # diving into the full per-node trace from app/graph/node_tracing.py.
    logger.info(
        "turn completed: intent=%s guardrail_allowed=%s output_guardrail_allowed=%s risk_score=%s human_decision=%s",
        updated_state.detected_intent.value if updated_state.detected_intent else None,
        updated_state.guardrail_allowed,
        updated_state.output_guardrail_allowed,
        updated_state.risk_score,
        updated_state.human_decision,
        extra={"session_id": session_id, "node": "turn_summary"},
    )

    return ChatResponse(
        session_id=updated_state.session_id,
        response=updated_state.final_response or "I'm not sure how to help with that yet.",
        detected_intent=updated_state.detected_intent.value if updated_state.detected_intent else None,
        plugin_results=[r.model_dump() for r in updated_state.plugin_results],
        awaiting_human_review=False,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid.uuid4())
    config = _thread_config(session_id)

    logger.info(
        "turn request received: session=%s user_id=%s message=%s",
        session_id,
        request.user_id,
        request.message,
        extra={"session_id": session_id, "node": "turn_request"},
    )

    if session_id in _KNOWN_SESSIONS:
        # Checkpointer already has this thread's state; only send the new
        # message and let the checkpointer merge it into existing history.
        turn_input = {"messages": [ChatMessage(role="user", content=request.message)]}
    else:
        _KNOWN_SESSIONS.add(session_id)
        turn_input = AgentState(
            session_id=session_id,
            user_id=request.user_id,
            messages=[ChatMessage(role="user", content=request.message)],
        )

    result = compiled_graph.invoke(turn_input, config=config)
    response = _to_chat_response(session_id, result)

    logger.info(
        "turn response emitted: session=%s detected_intent=%s awaiting_human_review=%s response_preview=%s",
        session_id,
        response.detected_intent,
        response.awaiting_human_review,
        response.response[:200] if response.response else "",
        extra={"session_id": session_id, "node": "turn_response"},
    )
    return response


@router.post("/documents/upload", response_model=ChatResponse)
async def upload_document(
    session_id: str, file: UploadFile = File(...), user_id: str | None = None
) -> ChatResponse:
    settings = get_settings()
    contents = await file.read()

    if len(contents) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")

    # Persist the ORIGINAL file independently of the OCR/extraction
    # pipeline — see app/core/object_storage.py docstring for why this
    # matters for audit/compliance. No-ops cleanly if storage isn't
    # configured (dev/demo default), and a storage failure here doesn't
    # block the actual document-processing turn — worst case, this
    # upload just isn't archived, which is logged, not fatal.
    storage = get_object_storage()
    if storage.is_enabled:
        try:
            storage.put_bytes(
                key=f"uploads/{session_id}/{file.filename}",
                data=contents,
                content_type=file.content_type or "application/octet-stream",
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "object storage upload failed for session=%s file=%s", session_id, file.filename, exc_info=True
            )

    config = _thread_config(session_id)
    upload_message = ChatMessage(role="user", content=f"[Uploaded document: {file.filename}]")

    if session_id in _KNOWN_SESSIONS:
        turn_input = {
            "messages": [upload_message],
            "detected_intent": Intent.UPLOAD_DOCUMENT,
            "pending_action": contents,
        }
    else:
        _KNOWN_SESSIONS.add(session_id)
        turn_input = AgentState(
            session_id=session_id,
            user_id=user_id,
            messages=[upload_message],
            detected_intent=Intent.UPLOAD_DOCUMENT,
            pending_action=contents,
        )

    result = compiled_graph.invoke(turn_input, config=config)
    return _to_chat_response(session_id, result)


class AnalyzerSubmission(BaseModel):
    session_id: str
    user_id: str | None = None
    # Raw JSON exactly as your existing bank-statement-analyzer or
    # financial-statement-analyzer service produces it. Field-name
    # mapping happens in app/plugins/external_analyzer_ingest.py.
    payload: dict


def _analyzer_intent(analyzer_type: str) -> Intent:
    return (
        Intent.SUBMIT_BANK_STATEMENT_ANALYSIS
        if analyzer_type == "bank_statement"
        else Intent.SUBMIT_FINANCIAL_STATEMENT_ANALYSIS
    )


async def _submit_analyzer_output(analyzer_type: str, request: AnalyzerSubmission) -> ChatResponse:
    config = _thread_config(request.session_id)
    intent = _analyzer_intent(analyzer_type)
    marker_message = ChatMessage(
        role="user", content=f"[Submitted {analyzer_type.replace('_', ' ')} analysis]"
    )

    if request.session_id in _KNOWN_SESSIONS:
        turn_input = {
            "messages": [marker_message],
            "detected_intent": intent,
            "pending_action": request.payload,
        }
    else:
        _KNOWN_SESSIONS.add(request.session_id)
        turn_input = AgentState(
            session_id=request.session_id,
            user_id=request.user_id,
            messages=[marker_message],
            detected_intent=intent,
            pending_action=request.payload,
        )

    result = compiled_graph.invoke(turn_input, config=config)
    return _to_chat_response(request.session_id, result)


@router.post("/analyzers/bank-statement", response_model=ChatResponse)
async def submit_bank_statement_analysis(request: AnalyzerSubmission) -> ChatResponse:
    """Submit output from your existing bank statement analyzer service."""
    return await _submit_analyzer_output("bank_statement", request)


@router.post("/analyzers/financial-statement", response_model=ChatResponse)
async def submit_financial_statement_analysis(request: AnalyzerSubmission) -> ChatResponse:
    """Submit output from your existing financial statement analyzer service."""
    return await _submit_analyzer_output("financial_statement", request)


class ReviewDecision(BaseModel):
    session_id: str
    approved: bool
    feedback: str | None = None


@router.post("/loan/review", response_model=ChatResponse)
async def submit_human_review(decision: ReviewDecision) -> ChatResponse:
    """Resume a graph run that's paused at human_review (see
    app/agents/human_review.py). session_id must belong to a thread that
    is actually paused there — calling this on a thread that isn't
    awaiting review is a no-op from LangGraph's side and will just
    re-run whatever's next in that thread's checkpointed state.
    """
    config = _thread_config(decision.session_id)
    resume_value = {"approved": decision.approved, "feedback": decision.feedback}

    result = compiled_graph.invoke(Command(resume=resume_value), config=config)
    return _to_chat_response(decision.session_id, result)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
