-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Knowledge base for RAG: loan policies, FAQs, product info, rate sheets
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    embedding   VECTOR(384),  -- matches all-MiniLM-L6-v2 dimension
    -- Lexical-search column for hybrid RAG (see app/rag/retriever.py).
    -- GENERATED so it's always in sync with `content` — no separate
    -- update path to forget to wire up when content changes.
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- IVFFlat index for approximate nearest-neighbor search at scale.
-- lists=100 is a reasonable default below ~1M rows; tune upward as the
-- knowledge base grows (rule of thumb: sqrt(num_rows)).
CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
    ON knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- GIN index for full-text (lexical/BM25-family) search — the other half
-- of hybrid retrieval alongside the vector index above.
CREATE INDEX IF NOT EXISTS knowledge_chunks_search_vector_idx
    ON knowledge_chunks
    USING gin (search_vector);

-- Persisted loan applications (session -> application state snapshot)
CREATE TABLE IF NOT EXISTS applications (
    session_id          TEXT PRIMARY KEY,
    applicant_name       TEXT,
    pan_number           TEXT,
    monthly_income        NUMERIC,
    requested_amount       NUMERIC,
    tenure_months          INTEGER,
    credit_score            INTEGER,
    eligibility_status       TEXT,
    eligibility_reasons      JSONB DEFAULT '[]',
    raw_state                JSONB,
    created_at               TIMESTAMPTZ DEFAULT now(),
    updated_at               TIMESTAMPTZ DEFAULT now()
);

-- Audit log for document processing (compliance requirement in fintech)
CREATE TABLE IF NOT EXISTS document_audit_log (
    id            SERIAL PRIMARY KEY,
    session_id     TEXT NOT NULL,
    doc_type        TEXT,
    ocr_confidence   NUMERIC,
    is_valid          BOOLEAN,
    validation_errors JSONB DEFAULT '[]',
    processed_at       TIMESTAMPTZ DEFAULT now()
);

-- Audit log for every decision-agent outcome (compliance/explainability
-- trail — see app/agents/decision_agent.py and app/db/audit_log.py).
-- Written once per turn that reaches the decision agent, regardless of
-- whether it triggered human review, so "why was this response sent"
-- has a reproducible record even for routine turns.
CREATE TABLE IF NOT EXISTS decision_audit_log (
    id                 SERIAL PRIMARY KEY,
    session_id          TEXT NOT NULL,
    user_id              TEXT,
    detected_intent        TEXT,
    selected_plugins         JSONB DEFAULT '[]',
    plugin_results             JSONB DEFAULT '[]',
    risk_score                  NUMERIC,
    risk_factors                  JSONB DEFAULT '[]',
    required_human_review           BOOLEAN,
    human_decision                    TEXT,
    human_feedback                      TEXT,
    output_guardrail_allowed              BOOLEAN,
    created_at                              TIMESTAMPTZ DEFAULT now()
);
