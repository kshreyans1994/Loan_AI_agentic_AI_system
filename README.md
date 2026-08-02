<<<<<<< HEAD
# Loan_AI_agentic_AI_system
Agentic AI system for automated loan decision support, combining LLM routing, document OCR/VLM analysis, hybrid RAG, deterministic financial plugins, and audit-friendly review workflows.
=======
# AI-Powered Loan Application Chat Agent

## Project Summary

This project is an AI-driven loan application assistant that combines conversational chat, document intelligence, deterministic financial calculations, and retrieval-augmented policy reasoning to support end-to-end loan workflows. Users can interact with the system through a chat interface, upload supporting documents such as salary slips or bank statements, submit external analyzer JSON payloads, and receive grounded eligibility, EMI, FOIR, and offer-related responses based on both structured plugin outputs and policy documents.

The platform is designed for auditability and explainability in a regulated lending environment. Instead of relying on the model alone for business decisions, the system separates routing, document understanding, deterministic calculations, policy retrieval, and human review into modular agent stages. The current runtime also includes request-to-response trace logging, a safer upload path for raw document bytes, and graceful degradation when persistence services such as Postgres are unavailable so the user-facing response is not blocked by backend storage issues.

### Key Functionalities

- Conversational loan assistance through a FastAPI backend and Streamlit frontend
- Document upload and OCR/VLM-based extraction for financial documents
- Submission of bank/financial-statement analyzer JSON payloads through dedicated API endpoints
- Policy-grounded answer generation using hybrid RAG over PostgreSQL + pgvector
- Deterministic plugin-based calculations for EMI, FOIR, eligibility, repo rate, and offer recommendation
- Long-term user memory and session-level context handling
- Human-in-the-loop review for high-risk applications
- End-to-end turn tracing from request receipt to final response emission
- Audit logging for decision traceability and operational observability with graceful non-blocking persistence fallback

### Tech Stack

- Orchestration: LangGraph
- API: FastAPI
- Frontend: Streamlit
- LLM/VLM: Groq
- OCR: Tesseract
- Vector store and memory persistence: PostgreSQL + pgvector
- Embeddings: sentence-transformers
- Web search fallback: Tavily
- Object storage: S3-compatible storage via MinIO/S3
- Deployment: Docker, Jenkins, ArgoCD, Kubernetes/Kustomize
- Turn observability: explicit request/response lifecycle logging in the API layer
- Persistence resilience: Postgres audit and memory writes are best-effort and warn instead of stalling the user response when the database is down

A conversational loan assistant that automates document verification and eligibility decisioning end-to-end — built with **LangGraph** for orchestration, **Groq (Llama 3.3 / vision)** for LLM and VLM inference, **Tesseract OCR** for text extraction, **PostgreSQL + pgvector** for RAG-based policy retrieval, and **FastAPI logging** for request lifecycle visibility.

This project turns a manual, multi-day loan document review process into a real-time conversational flow: upload KYC documents, get instant OCR+VLM extraction and validation, receive an eligibility decision grounded in actual policy text (not model guesswork), and get a personalized offer — all through one chat interface.

## Why this exists

Most "AI chatbot" demos stop at prompt-and-response. This one demonstrates the harder, more interview-relevant parts of building an agentic system:

- **Structured state, not free text** — a typed `AgentState` threads through every LangGraph node, so the graph can be unit-tested node-by-node instead of only end-to-end.
- **Deterministic business logic where it matters** — EMI math and eligibility rules are plain Python, not LLM output. In a regulated domain like lending, "the model decided you're ineligible" is not an acceptable audit trail.
- **A real two-pass document pipeline** — OCR extracts text, a vision-language model reasons over the *image* (layout, tables, tampering signals) using the OCR text as context, and format validation (regex checks on PAN/Aadhaar) catches malformed extractions before they reach a decision.
- **RAG that's actually grounded** — the response generator is instructed never to invent numbers; it can only surface what plugins and retrieval actually returned.
- **Two distinct memory systems, not one blurred together** — short-term (this conversation, via LangGraph's checkpointer) and long-term (durable facts about this user across sessions, via Postgres) solve different problems and use different mechanisms. See `docs/ARCHITECTURE.md` §9 for why conflating them is a common mistake.
- **Web search as a gated fallback, not an always-on step** — only fires when the RAG knowledge base comes back thin, and the model is told to flag web-sourced claims as live lookups rather than settled policy.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design writeup, including the end-to-end workflow diagram, plugin registry pattern, and scaling notes.

```
User message
    │
    ▼
[Recall Long-Term Memory]  (Postgres — durable facts, if user_id given; no-op otherwise)
    │
    ▼
[Input Guardrail]          (safe-to-act check; short-circuits blocked turns)
    │
    ▼
[Supervisor Agent]         (LLM: picks coarse category/categories)
    │
    ▼
[Intent Agent]             (LLM: picks specific plugin(s) within those categories)
    │
    ▼
[Plugin Execution]         (Eligibility / EMI / Credit Score / Document Verifier / Offers)
    │
    ▼
[RAG Retrieval]             (pgvector similarity search over policy knowledge base)
    │
    ▼
[Web Search]                 (fallback only — fires if RAG results are thin/absent)
    │
    ▼
[Response Generation]         (Groq LLM, grounded in plugin + RAG + memory + web context)
    │
    ▼
[Save Long-Term Memory]        (extracts durable facts from this turn, if user_id given)
    │
    ▼
Final response + structured plugin data
```

Short-term memory (the running conversation within one session) doesn't appear as a graph node — it's handled automatically by LangGraph's checkpointer, keyed by `session_id` as the thread ID. Every node in the graph above already has access to the full conversation history for free.

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph |
| LLM | Groq (Llama 3.3 70B) |
| Vision-Language Model | Groq (Llama 3.2 11B Vision) |
| OCR | Tesseract (pytesseract) |
| Vector store | PostgreSQL + pgvector |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Short-term memory | LangGraph checkpointer (in-process, thread-keyed) |
| Long-term memory | PostgreSQL (durable facts + session summaries) |
| Web search | Tavily (gated fallback when RAG is thin) |
| API | FastAPI |
| Session/cache | Redis — *not wired in yet; reserved config only, see Known Limitations* |
| Observability | LangSmith, OpenTelemetry |

## Project structure

```
loan-ai-agent/
├── app/
│   ├── agents/                  # LangGraph node functions
│   │   ├── intent_detector.py
│   │   ├── plugin_executor.py   # also patches application state (income promotion, precedence)
│   │   ├── rag_retrieval.py
│   │   ├── web_search.py        # Fallback node (fires only if RAG is thin)
│   │   ├── long_term_memory.py  # Recall + save nodes (facts across sessions)
│   │   └── response_generator.py
│   ├── api/
│   │   └── routes.py            # FastAPI: /chat, /documents/upload, /analyzers/*
│   ├── core/
│   │   ├── config.py            # Settings (env-driven, no hardcoded secrets)
│   │   ├── schemas.py           # Shared Pydantic models incl. AgentState
│   │   └── memory_long_term.py  # Postgres-backed long-term memory store
│   ├── db/
│   │   ├── schema.sql           # Postgres + pgvector DDL
│   │   └── memory_schema.sql    # Long-term memory tables
│   ├── document_ai/
│   │   ├── ocr.py                # Tesseract OCR engine (swappable interface)
│   │   ├── vlm.py                 # Vision-language document understanding
│   │   └── pipeline.py             # OCR + VLM + validation orchestration
│   ├── graph/
│   │   └── pipeline.py             # LangGraph graph assembly + checkpointer
│   ├── plugins/
│   │   ├── base.py
│   │   ├── eligibility_check.py
│   │   ├── emi_calculator.py
│   │   ├── credit_score.py
│   │   ├── document_verifier.py
│   │   ├── external_analyzer_ingest.py  # ingests YOUR bank/financial statement analyzer JSON
│   │   ├── offer_recommendation.py
│   │   └── registry.py             # Intent -> Plugin dispatch table
│   ├── rag/
│   │   ├── retriever.py             # pgvector similarity search
│   │   └── web_search_client.py     # Tavily client (swappable interface)
│   └── main.py                       # FastAPI app entrypoint
├── scripts/
│   └── seed_knowledge_base.py
├── data/seed/knowledge_base.json
├── tests/
│   ├── test_emi_calculator.py
│   ├── test_eligibility_check.py
│   ├── test_document_pipeline_validation.py
│   ├── test_web_search_fallback.py
│   ├── test_external_analyzer_ingest.py
│   └── test_plugin_executor_application_updates.py
├── docs/ARCHITECTURE.md
├── requirements.txt
└── .env.example
```

## Running locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Tesseract (OS-level dependency)
#    macOS: brew install tesseract
#    Ubuntu: apt-get install tesseract-ocr

# 3. Start Postgres with pgvector (Docker example)
docker run -d --name loan-pg -e POSTGRES_USER=loan_user \
  -e POSTGRES_PASSWORD=loan_pass -e POSTGRES_DB=loan_agent \
  -p 5432:5432 pgvector/pgvector:pg16

# 4. Apply schema (RAG knowledge base + long-term memory tables)
psql postgresql://loan_user:loan_pass@localhost:5432/loan_agent -f app/db/schema.sql
psql postgresql://loan_user:loan_pass@localhost:5432/loan_agent -f app/db/memory_schema.sql

# 5. Configure environment
cp .env.example .env   # then add GROQ_API_KEY and (optionally) TAVILY_API_KEY
#    Web search fallback silently returns no results if TAVILY_API_KEY is unset —
#    fine for local dev, but set it to see that code path in action.

# 6. Seed the knowledge base
python scripts/seed_knowledge_base.py

# 7. Run the API
uvicorn app.main:app --reload --port 8000

# 8. Run tests
pytest tests/ -v
```

## Deploying to Kubernetes with Jenkins + ArgoCD

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full pipeline: Jenkins handles CI (test, build, scan, push image, bump the GitOps manifest repo), ArgoCD handles CD (watches the manifest repo, reconciles the cluster). The `Dockerfile` and `deploy/` folder (Kustomize base + staging/production overlays + ArgoCD Application manifests) are ready to use as a starting point — the doc explains the staging→production promotion flow and how secrets are handled without ever committing plaintext values to Git.

## Frontend

A minimal Streamlit chat UI lives in `frontend/` — see [`frontend/README.md`](frontend/README.md) for setup. It's a thin client over the FastAPI backend (chat, document upload, live plugin-result cards), no business logic in the UI layer.

```bash
pip install -r frontend/requirements.txt
streamlit run frontend/app.py   # with the backend already running on :8000
```

## Example interaction

```
POST /api/v1/chat
{"message": "What's the EMI for a 5 lakh loan over 36 months?"}

→ Intent detected: calculate_emi
→ Plugin executed: emi_calculator
→ Response: "For a ₹5,00,000 loan over 36 months at our standard rate of
   10.5% p.a., your EMI would be approximately ₹16,255/month, with total
   interest of ₹85,180 over the tenure."
```

## Integrating your existing bank/financial statement analyzers

If you already have separate services that analyze bank statements or financial statements, this project ingests their JSON output directly rather than re-implementing that analysis:

```bash
POST /api/v1/analyzers/bank-statement
{
  "session_id": "sess-001",
  "user_id": "user-42",
  "payload": { ...your bank statement analyzer's raw JSON output... }
}

POST /api/v1/analyzers/financial-statement
{
  "session_id": "sess-001",
  "payload": { ...your financial statement analyzer's raw JSON output... }
}
```

**What happens under the hood:**
1. `ExternalAnalyzerIngestPlugin` (`app/plugins/external_analyzer_ingest.py`) normalizes your service's field names into this project's internal schema — edit `_map_bank_statement_payload` / `_map_financial_statement_payload` in that file to match your actual JSON keys.
2. The derived income figure is applied to `application.monthly_income` **only if it outranks whatever income signal is already set**, per a fixed precedence order: financial statement analysis > bank statement analysis > salary slip OCR. Uploading a salary slip first and then submitting a bank statement analysis correctly upgrades the income figure; submitting a bank statement analysis after a financial statement analysis won't downgrade it.
3. `eligibility_check` reads `application.monthly_income` as normal — no changes needed there — and the eligibility reasoning explicitly notes which source the income figure came from (e.g. `"Monthly income ₹45,000 (from bank_statement_analyzer) is below..."`) for audit clarity.

Same integration pattern as the OCR/VLM document pipeline: an external capability is wrapped in a plugin behind a consistent interface, and the plugin-execution node applies its output to shared state.

## Latest runtime changes

The current implementation includes several important operational improvements beyond the original baseline pipeline:

- Upload and analyzer submission payloads now flow through a shared graph state path that accepts raw document bytes and structured JSON analyzer payloads without breaking Pydantic validation.
- The API route now emits clear turn-level logs for request receipt and final response emission, which makes debugging and traceability much easier across the whole user journey.
- Postgres-backed audit logging and long-term memory persistence now fail fast with a short connect timeout and degrade gracefully with explicit warning logs rather than holding the user-facing response hostage.

## Known limitations (by design, for a portfolio build)

- Credit bureau integration is a **mocked, clearly-labeled adapter** — real CIBIL/Experian integration requires commercial agreements out of scope for a public repo.
- Document samples in `data/sample_docs/` are synthetic placeholders, not real ID formats, to avoid any PII/compliance concerns in a public codebase.
- Redis is **not currently used anywhere in the code** — it's a reserved config value (`redis_url` in `app/core/config.py`) for future rate-limiting or cross-restart session persistence work, not something already wired in. Short-term memory runs on LangGraph's in-process checkpointer today, which means conversation state is lost if the API process restarts — that's the concrete gap Redis (or `PostgresSaver`) would close.
- The current long-term persistence path is best-effort when Postgres is offline; the response still completes, but the durable memory/audit side-effect is skipped and logged instead of failing the turn.
>>>>>>> 0d195ab (Initial commit)
