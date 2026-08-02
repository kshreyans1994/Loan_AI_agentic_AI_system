"""
Central application configuration.

All secrets and environment-specific values are loaded from environment
variables (or a local .env file, never committed). Nothing here is a
hardcoded credential — see .env.example for the variables you need to set.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM provider (Groq) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_temperature: float = 0.1

    # --- Vision-language model for document understanding ---
    # Any OpenAI-vision-compatible endpoint works here; Groq's vision-capable
    # models or a self-hosted VLM can be swapped in via this base_url.
    vlm_provider: str = "groq"
    vlm_model: str = "llama-3.2-11b-vision-preview"

    # --- Postgres + pgvector ---
    postgres_dsn: str = "postgresql://loan_user:loan_pass@localhost:5432/loan_agent"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # --- Redis: NOT CURRENTLY USED anywhere in the codebase. This is a
    # reserved setting for future work — rate limiting and cross-restart
    # session persistence — not something already wired in. Short-term
    # conversation memory is handled by LangGraph's checkpointer (see
    # app/graph/pipeline.py), and long-term memory by Postgres (see
    # app/core/memory_long_term.py). Remove this setting if you don't
    # plan to add Redis-backed features; keep it as a placeholder if you do. ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Web search fallback ---
    tavily_api_key: str = ""

    # --- Observability ---
    langsmith_api_key: str | None = None
    langsmith_project: str = "loan-ai-agent"
    otel_exporter_endpoint: str | None = None

    # --- App behavior ---
    max_upload_mb: int = 10

    # --- Logging (see app/core/logging_config.py) ---
    log_level: str = "INFO"  # DEBUG for full per-node trace during local debugging
    log_format: str = "text"  # "text" for local dev, "json" for shipping to a log aggregator
    ocr_confidence_threshold: float = 0.60
    session_ttl_seconds: int = 3600

    # --- Decision Agent / HITL (see app/agents/decision_agent.py) ---
    # risk_score (0-1, computed deterministically from FOIR, credit-score
    # margin, and plugin failures) at/above this routes to human_review.
    decision_risk_threshold: float = 0.85
    # One of decision_agent's risk factors: requested amount at/above
    # this contributes to risk_score regardless of how clean the
    # eligibility result otherwise looks.
    human_review_amount_threshold: float = 500_000

    # --- Hybrid RAG (see app/rag/retriever.py) ---
    rag_vector_weight: float = 0.6  # RRF blend weight, vector vs lexical
    rag_lexical_weight: float = 0.4
    rag_rerank_top_n: int = 8  # candidates pulled pre-rerank
    rag_final_top_k: int = 4  # chunks kept after rerank + compression
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- Object storage (S3/MinIO) for uploaded documents + policy PDFs ---
    object_storage_enabled: bool = False
    object_storage_endpoint_url: str | None = None  # set for MinIO; leave unset for AWS S3
    object_storage_bucket: str = "loaniq-documents"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
