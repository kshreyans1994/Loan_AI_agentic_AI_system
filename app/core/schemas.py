"""
Shared Pydantic schemas.

Keeping these in one module means every agent, plugin, and API route
speaks the same typed contract instead of passing raw dicts around —
this is what lets LangGraph validate state transitions instead of
failing silently at runtime.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    AADHAAR = "aadhaar"
    PAN = "pan"
    SALARY_SLIP = "salary_slip"
    BANK_STATEMENT = "bank_statement"
    UNKNOWN = "unknown"


class Intent(str, Enum):
    APPLY_LOAN = "apply_loan"
    CHECK_ELIGIBILITY = "check_eligibility"
    CALCULATE_EMI = "calculate_emi"
    CALCULATE_FOIR = "calculate_foir"
    CHECK_REPO_RATE = "check_repo_rate"
    CHECK_INTEREST_RATE = "check_interest_rate"
    UPLOAD_DOCUMENT = "upload_document"
    CHECK_CREDIT_SCORE = "check_credit_score"
    SUBMIT_BANK_STATEMENT_ANALYSIS = "submit_bank_statement_analysis"
    SUBMIT_FINANCIAL_STATEMENT_ANALYSIS = "submit_financial_statement_analysis"
    ASK_QUESTION = "ask_question"
    SMALL_TALK = "small_talk"
    UNKNOWN = "unknown"


class QueryCategory(str, Enum):
    """The three top-level branches the supervisor routes a turn into.
    Coarser than Intent — a category can contain several intents (e.g.
    TOOL_QUERY covers calculate_emi, calculate_foir, check_eligibility,
    check_credit_score, check_repo_rate, check_interest_rate). The
    supervisor picks categories; app/agents/intent_agent.py picks the
    specific plugin(s) within each selected category."""
    TOOL_QUERY = "tool_query"
    POLICY_QUERY = "policy_query"
    DOCUMENT_QUERY = "document_query"


class ExtractedField(BaseModel):
    """A single field pulled from a document, with provenance."""
    name: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class DocumentExtraction(BaseModel):
    doc_type: DocumentType
    raw_text: str
    fields: list[ExtractedField] = Field(default_factory=list)
    ocr_confidence: float = Field(ge=0.0, le=1.0)
    vlm_summary: Optional[str] = None
    is_valid: bool = False
    validation_errors: list[str] = Field(default_factory=list)


class PluginResult(BaseModel):
    plugin_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class RetrievedChunk(BaseModel):
    content: str
    source: str
    score: float


class WebSearchResult(BaseModel):
    title: str
    snippet: str
    url: str


class ExternalAnalyzerSource(str, Enum):
    """Which external analyzer produced a given financial signal — kept
    on the record so eligibility reasoning and audit logs can say
    *which* system a number came from, not just that it exists."""
    BANK_STATEMENT_ANALYZER = "bank_statement_analyzer"
    FINANCIAL_STATEMENT_ANALYZER = "financial_statement_analyzer"


class BankStatementAnalysis(BaseModel):
    """
    Normalized shape for output from an external bank statement analyzer
    service. Field names here are what THIS project expects internally —
    see app/plugins/external_analyzer_ingest.py for the adapter that maps
    your existing service's actual JSON keys onto this shape.
    """
    average_monthly_credit: float
    average_monthly_debit: float
    average_monthly_balance: Optional[float] = None
    bounced_transactions_count: int = 0
    statement_period_months: int
    net_monthly_cash_flow: float
    source: ExternalAnalyzerSource = ExternalAnalyzerSource.BANK_STATEMENT_ANALYZER
    raw: dict[str, Any] = Field(default_factory=dict)  # original payload, preserved for audit


class FinancialStatementAnalysis(BaseModel):
    """
    Normalized shape for output from an external financial statement
    analyzer (e.g. for self-employed / business applicants — P&L,
    balance sheet derived signals rather than bank transaction flow).
    """
    annual_revenue: Optional[float] = None
    net_profit: Optional[float] = None
    debt_to_income_ratio: Optional[float] = None
    fiscal_year: Optional[str] = None
    derived_monthly_income: float
    source: ExternalAnalyzerSource = ExternalAnalyzerSource.FINANCIAL_STATEMENT_ANALYZER
    raw: dict[str, Any] = Field(default_factory=dict)


class LongTermMemoryFact(BaseModel):
    """A single durable fact about a user, recalled/saved across sessions —
    e.g. 'preferred loan tenure is 36 months' or 'previously applied and
    was rejected for low credit score in March'."""
    fact: str
    category: Literal["profile", "application_history", "preference"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LoanApplication(BaseModel):
    applicant_name: Optional[str] = None
    pan_number: Optional[str] = None
    aadhaar_number: Optional[str] = None
    monthly_income: Optional[float] = None
    # Tracks WHICH source last set monthly_income, so eligibility reasoning
    # and audit logs can say e.g. "income figure from bank_statement_analyzer,
    # not salary slip OCR" — matters when two sources disagree.
    income_signal_source: Optional[str] = None
    requested_amount: Optional[float] = None
    tenure_months: Optional[int] = None
    credit_score: Optional[int] = None
    # Sum of EMIs already being paid on other loans — needed for FOIR
    # (Fixed Obligation to Income Ratio). Defaults to 0, not None, so
    # FOIRCalculatorPlugin can compute without a special no-data branch.
    existing_monthly_emi: float = 0.0
    documents: dict[DocumentType, DocumentExtraction] = Field(default_factory=dict)
    bank_statement_analysis: Optional[BankStatementAnalysis] = None
    financial_statement_analysis: Optional[FinancialStatementAnalysis] = None
    eligibility_status: Optional[Literal["eligible", "ineligible", "pending"]] = None
    eligibility_reasons: list[str] = Field(default_factory=list)


class AgentState(BaseModel):
    """
    The single shared state object threaded through the LangGraph pipeline.
    Each node reads what it needs and returns a partial update, which
    LangGraph merges back in — this keeps nodes decoupled and testable
    in isolation.
    """
    session_id: str
    # user_id identifies the person ACROSS sessions/devices; session_id is
    # just this one conversation thread. Long-term memory keys off
    # user_id, short-term (checkpointer) keys off session_id. If a caller
    # doesn't provide one (e.g. anonymous/guest chat), long-term memory
    # recall/save nodes no-op rather than guessing an identity.
    user_id: Optional[str] = None
    messages: list[ChatMessage] = Field(default_factory=list)
    detected_intent: Optional[Intent] = None
    intent_confidence: float = 0.0
    application: LoanApplication = Field(default_factory=LoanApplication)
    retrieved_context: list[RetrievedChunk] = Field(default_factory=list)
    web_search_results: list[WebSearchResult] = Field(default_factory=list)
    long_term_memory: list[LongTermMemoryFact] = Field(default_factory=list)
    plugin_results: list[PluginResult] = Field(default_factory=list)
    # Arbitrary per-turn payload carried by the graph for document upload
    # or analyzer-submission steps. This is not user text; it can be raw
    # upload bytes or a structured JSON payload, so the field must accept
    # more than just a plain string.
    pending_action: Optional[Any] = None
    final_response: Optional[str] = None
    error: Optional[str] = None

    # --- Guardrail (input safety gate, runs before anything else) ---
    guardrail_allowed: bool = True
    guardrail_reason: Optional[str] = None

    # --- Supervisor (LLM: picks the coarse categories a turn needs) ---
    selected_categories: list[QueryCategory] = Field(default_factory=list)
    supervisor_reasoning: Optional[str] = None

    # --- Intent Agent (LLM: picks specific plugin(s) within the selected
    # categories — e.g. within tool_query, which of EMI/FOIR/eligibility/
    # credit-score/repo-rate/interest-rate actually run this turn) ---
    selected_plugins: list[Intent] = Field(default_factory=list)
    intent_reasoning: Optional[str] = None

    # --- Decision Agent (deterministic: aggregates plugin_results + any
    # document-extracted JSON into a risk_score, decides if HITL fires) ---
    risk_score: Optional[float] = None
    risk_factors: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    # --- Human-in-the-loop (conditional — only when risk_score exceeds
    # the threshold in Settings.decision_risk_threshold) ---
    human_decision: Optional[Literal["approved", "rejected"]] = None
    human_feedback: Optional[str] = None

    # --- Output guardrail (checks the drafted response before it goes
    # to the user; runs after generate_response) ---
    output_guardrail_allowed: bool = True
    output_guardrail_reason: Optional[str] = None
