# Architecture

## 1. Design goals

1. **Auditability over cleverness.** Loan eligibility is a regulated decision. Every number the user sees must be traceable to either a deterministic plugin calculation or a retrieved policy chunk — never a model hallucination. LLMs in this pipeline route, classify, and synthesize language; they never compute or decide a lending outcome themselves.
2. **Testable nodes.** Every LangGraph node is a plain function of `AgentState -> dict`, so it can be called directly in a unit test without spinning up the graph or a live LLM connection.
3. **Swappable infra.** OCR engine, VLM provider, credit bureau, embedding model, reranker, and object storage are all behind small interfaces. This is a portfolio project, not a production fintech system — the seams matter more than the specific implementations behind them.

## 2. End-to-end workflow

```
User
  │
  ▼
FastAPI Gateway (app/api/routes.py)
  │
  ▼
Guardrail Agent ──(blocked)──▶ Output ("can't help with that")
  │ (allowed)                    [nothing downstream runs]
  ▼
Supervisor Agent          (LLM: which categories does this turn need?
  │                         tool_query / policy_query / document_query
  │                         — a turn can select more than one)
  ▼
Intent Agent               (LLM: within those categories, which SPECIFIC
  │                         plugin(s)? e.g. tool_query -> calculate_emi
  │                         AND calculate_foir in one turn)
  ▼
        ┌───────────────┬─────────────────┐
        ▼               ▼                 ▼
   Tool Layer        RAG Agent      Document Agent
  (deterministic    (hybrid vector  (OCR + VLM, only
   plugins: EMI,    + lexical       runs if a document
   FOIR, eligibility, search, see   was actually
   credit score,    §6)             attached)
   repo rate,
   interest rate)
        │               │                 │
        └───────────────┴─────────────────┘
                        │
                        ▼
                 Decision Agent        (deterministic: aggregates every
                        │               plugin result into risk_score
                        │               0.0-1.0, see §9)
                        │
              risk_score >= threshold?
                        │
          ┌─────────────┴─────────────┐
         NO                          YES
          │                           │
          ▼                           ▼
   Response Agent            Human Review (interrupt(),
          │                   pauses here) ──▶ Credit
          │                   Officer approves/rejects ──▶┐
          │                                                │
          └───────────────────┬────────────────────────────┘
                               ▼
                      Output Guardrail        (checks the DRAFTED
                               │                response before the
                               │                user sees it, see §10)
                               ▼
                       Write Audit Log        (decision_audit_log —
                               │                compliance trail, §12)
                               ▼
                      Save Long-Term Memory
                               │
                               ▼
                              User
```

Six gates/agents sit between the raw user message and the final response, each answering a distinct question:

1. **Guardrail** (§8, input side) — is this input safe to act on at all? A block short-circuits straight to output; nothing downstream runs.
2. **Supervisor** (§9) — which coarse category/categories does this turn need?
3. **Intent Agent** (§9) — within those categories, which *specific* plugin(s)?
4. **Decision Agent** (§9) — deterministically aggregate every plugin result into a risk score.
5. **Human Review** — conditional on that risk score; most turns skip it entirely.
6. **Output Guardrail** (§10) — does the *drafted response* itself need to be blocked before the user sees it?

Two adaptations carried over from the original design, both about avoiding wasted work on turns that don't need it:

1. **Document processing (OCR+VLM) is not a standalone graph node.** It's invoked conditionally, inside `DocumentVerifierPlugin`, only when the intent agent selects `upload_document`. Making it a permanent node in the linear chain would mean every EMI-calculation or small-talk turn pays the cost of a no-op check.
2. **Web search is a conditional fallback, not a parallel always-on step.** It only fires when RAG retrieval comes back thin (§13) and `policy_query` was actually selected — most policy/FAQ/rate-tier questions are already covered by the seeded knowledge base.

## 3. State management

`app/core/schemas.py::AgentState` is the single object threaded through every node. Each node reads what it needs and returns a **partial** dict; LangGraph merges that into the running state. This keeps every node a pure, independently-testable function — see any `tests/test_*.py` file for a node being called directly with a hand-built `AgentState`, no graph or LLM required.

Fields are grouped by which stage of the pipeline owns them: guardrail (`guardrail_allowed`, `guardrail_reason`), supervisor (`selected_categories`, `supervisor_reasoning`), intent agent (`detected_intent`, `selected_plugins`, `intent_reasoning`), decision agent (`risk_score`, `risk_factors`, `requires_human_review`), human review (`human_decision`, `human_feedback`), output guardrail (`output_guardrail_allowed`, `output_guardrail_reason`). A node only ever writes to the fields it owns — this is what makes "why did this turn end up here" traceable after the fact: each field's value has exactly one node responsible for setting it.

## 4. Plugin registry pattern

Instead of an `if intent == X: call_plugin_x()` chain, `app/plugins/registry.py` maps `Intent -> Plugin`. `execute_plugins` loops over `state.selected_plugins` (which can contain more than one intent — see §9) and calls `.run()` on each. Adding a new capability (the project already did this three times for this revision — FOIR, repo rate, interest rate) means:

1. Implement the `Plugin` interface (one `run()` method).
2. Add one line to `PLUGIN_REGISTRY`.
3. Add the corresponding value to the `Intent` enum.

No changes to graph wiring, no changes to either routing prompt beyond adding the new intent name to its list of valid options.

## 5. Document intelligence pipeline

```
Image bytes
    │
    ▼
┌─────────────┐     raw text + per-word confidence
│  OCR Engine  │────────────────────────────┐
│ (Tesseract)  │                             │
└─────────────┘                             ▼
    │                              ┌──────────────────┐
    │ image bytes                  │   VLM (Groq       │
    └─────────────────────────────▶│  vision model)     │──▶ doc_type, structured
                                    │  reasons over image │    fields, quality flags
                                    │  + OCR text jointly  │
                                    └──────────────────┘
                                              │
                                              ▼
                                    ┌──────────────────┐
                                    │ Format validation │──▶ DocumentExtraction
                                    │ (PAN/Aadhaar regex,│    (is_valid + errors)
                                    │  required-field     │
                                    │  checks)             │
                                    └──────────────────┘
```

**Why both OCR and VLM, not just one:** OCR alone gives flat text with no notion of "this specific 10-character string is the PAN field" — it can't disambiguate a PAN number from a phone number sitting next to it on a form. A VLM alone (image-only, no OCR context) is more token-expensive and less reliable at precise character-level extraction. Passing OCR text *into* the VLM call as grounding context gets the precision of OCR with the layout/structure understanding of vision reasoning.

**Validation is intentionally dumb.** Regex checks on PAN/Aadhaar format and a presence check for salary-slip income are the last deterministic gate before a document is marked valid. If OCR misreads a character and the VLM doesn't catch it, a shape-based sanity check still can.

The original uploaded file is also persisted to object storage independently of this extraction pipeline — see §11.

## 6. Hybrid RAG design

Retrieval fires conditionally — only when the supervisor selects `policy_query` — and, when it does, runs through a multi-stage hybrid pipeline rather than a single vector-similarity call:

```
query -> query_rewriter -> metadata_filter -> [vector_search, lexical_search]
      -> merge (Reciprocal Rank Fusion) -> rerank (cross-encoder)
      -> context_compression -> response generation
```

All of this lives inside `HybridRetriever` (`app/rag/retriever.py`) as one internal pipeline rather than seven separate graph nodes — the top-level graph diagram in §2 collapses it into a single conceptual "RAG Agent" step, the same way the source diagram's own "Query Flow" does. These steps are inherently sequential with no branch point a human or another agent would ever need to intervene on mid-way, so splitting them into graph nodes would add traversal overhead without adding any real flexibility.

- **Query rewriter** is deterministic (regex-based filler-stripping), not an LLM call — an LLM rewrite adds latency/cost to every RAG turn for a gain that's marginal on already-fairly-clean loan questions.
- **Metadata filter** is a small, conservative keyword heuristic (e.g. "NRI", "self-employed", "prepayment" map to metadata tags) — deliberately narrow so it can only ever *add* a filter on an unambiguous signal, never silently exclude relevant results on a query it doesn't recognize.
- **Vector search** — pgvector, IVFFlat index, local sentence-transformers embeddings (all-MiniLM-L6-v2, 384-dim) so the retrieval path works without an extra embedding-API dependency or cost.
- **Lexical search** — Postgres full-text search (`tsvector` + `ts_rank_cd`) rather than a separate in-memory BM25 library. `ts_rank_cd` is a BM25-family lexical ranking function; using Postgres's built-in version means the lexical index is persisted and GIN-indexed automatically, with no separate index-rebuild step to maintain — one fewer moving part, given Postgres is already running everything else here.
- **Merge** uses Reciprocal Rank Fusion, not a raw score blend — cosine similarity and `ts_rank_cd` are on incompatible scales, so combining by each result's *rank* (not its raw score) avoids letting whichever metric happens to produce larger numbers dominate.
- **Rerank** uses a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2` by default) over the RRF-merged candidates. Degrades gracefully — if the model can't load (no network access to the model hub, e.g.), reranking is skipped and the RRF order is used as-is, rather than failing the whole retrieval.
- **Context compression** drops near-duplicate chunks (common when the same policy point is chunked with overlapping windows) and truncates long chunks to a sentence boundary — both deterministic, not an LLM summarization pass per chunk.
- **Grounding instruction is explicit** in the response-generation system prompt: "never invent numbers that aren't in the provided data." This is a prompt-level control; the output guardrail (§10) is the closest thing to an enforcement backstop currently in place, though it doesn't yet verify every numeric claim against source data — see §14 for what's still out of scope.

## 7. Document intelligence + RAG relationship to the plugin layer

Document processing and RAG retrieval both feed into the same `execute_plugins` / `retrieve_context` stage but never touch `risk_score` or the eligibility decision directly — a document's extracted income figure flows into `LoanApplication.monthly_income` (see `plugin_executor.py::_application_updates_from_document`), and *then* the deterministic `EligibilityCheckPlugin`/`FOIRCalculatorPlugin` use that figure like any other input. Nothing about a document being AI-extracted or a policy chunk being retrieved gives it special standing in the actual decision — it's just data, subject to the same deterministic rules as data the user typed directly.

## 8. Guardrails (input and output)

Two separate guardrail nodes, front and back of the pipeline, checking different things:

**Input guardrail** (`app/agents/guardrail.py`, runs before the supervisor) — two layers, cheapest first:
1. Deterministic pattern checks — prompt-injection phrases, requests for another applicant's identity/financial data by ID number. Free, instant, catches the clearest cases without an LLM call.
2. LLM classification — only runs if layer 1 didn't already block. One extra LLM call per turn, which is why layer 1 exists first.

A block routes straight to a fixed refusal; nothing else in the graph runs. Fails *open* on an LLM parsing error, not closed — an outage in that one call shouldn't take the whole assistant down.

**Output guardrail** (`app/agents/output_guardrail.py`, runs after `generate_response`) — checks the *drafted response*, not the input, and runs on every turn (unlike the input guardrail's LLM layer, which only fires on ambiguous input — every turn that reaches here already produced a response, so this stays pattern-based/deterministic rather than adding a mandatory LLM call to 100% of turns):
1. **PII leakage** — flags an ID-number-shaped string in the response that doesn't belong to the current applicant (catches an LLM echoing an ID from retrieved context/memory that isn't theirs).
2. **Decision/reviewer contradiction** — if a human reviewer rejected this response, the drafted text can't contain approval language. This is a safety net for `generate_response`'s prompt instruction being ignored, not the only place that rule is enforced.

A failed output-guardrail check replaces `final_response` with a generic fallback message rather than leaving the turn unanswered — the user already asked; silently dropping the response isn't an option the way blocking upfront is.

## 9. Supervisor, Intent Agent, and Decision Agent — where LLM routing stops and deterministic decisioning starts

Three agents sit between the guardrail and the response, and they are **not** interchangeable in how much they're trusted:

- **Supervisor** (LLM) picks the coarse category/categories (`tool_query` / `policy_query` / `document_query`) a turn needs.
- **Intent Agent** (LLM) picks the specific plugin(s) within those categories — e.g. a compound message like "am I eligible, and what's my FOIR?" selects both `check_eligibility` and `calculate_foir` in one turn instead of forcing two round trips.
- **Decision Agent** (**deterministic, no LLM**) aggregates whatever those plugins actually returned into a single `risk_score` (0.0-1.0) and decides whether `human_review` fires.

The split matters: a wrong ROUTING choice (supervisor/intent agent) is low-consequence and self-correcting — worst case, the wrong plugin runs or none do, and the user can just ask again. A wrong RISK-SCORING choice directly decides whether a human ever reviews a lending-relevant response before it goes out — that's exactly the kind of consequential, auditable call this project keeps out of an LLM's hands, for the same reason eligibility/EMI/FOIR themselves are deterministic (see the plugin implementations and their docstrings). "Why was this turn/wasn't this turn escalated to a human" always has a reproducible, rule-based answer:

- Any plugin call failed → `+0.50`
- FOIR band is `high_risk` (≥55%) → `+0.45`, or `caution` (40-55%) → `+0.25`
- Eligibility check came back ineligible → `+0.20`
- Credit score within `human_review_credit_score_margin` (15 pts) of the eligibility cutoff, either direction → `+0.30`
- Requested amount ≥ `human_review_amount_threshold` (₹5,00,000) → `+0.20`

Weights sum (capped at 1.0); `requires_human_review = risk_score >= settings.decision_risk_threshold` (0.85 default). Both the weights and the threshold are named constants in `app/agents/decision_agent.py` and `app/core/config.py` respectively, each independently unit-tested (`tests/test_decision_agent.py`).

Guardrails on the two LLM agents' own output, since routing now trusts an LLM more than a fixed lookup table did: invalid category/intent values are dropped, not crashed on; `document_query`/`upload_document`-family selections can never survive without a genuinely attached payload this turn, regardless of what the LLM outputs; malformed/unparseable output falls back to a safe default (`policy_query` / `ask_question`) rather than crashing the graph or silently doing nothing.

**Historical note on this design, for anyone reading the commit history:** an earlier revision of this pipeline made human review run *unconditionally* on every turn (mirroring a paired travel-planner project's `human_approval_agent`) instead of being gated by a risk score. Both are legitimate designs — review-every-turn gives a stronger "nothing reaches the user unreviewed" guarantee at the cost of latency/reviewer-load on routine turns; risk-gated review (the current version) reserves that cost for turns that actually warrant it. This project currently runs risk-gated, per an explicit design decision to match a specific target architecture.

## 10. Human-in-the-loop review

`app/agents/human_review.py` calls LangGraph's `interrupt()` — but only when `decision_agent` set `requires_human_review = True`. Most turns (routine EMI/FOIR calculations, clean high-credit-score approvals, policy questions) never reach this node at all.

Mechanically: `interrupt()` pauses the graph mid-run; `POST /loan/review` resumes it via `Command(resume={"approved": bool, "feedback": str | None})`. `generate_response` is told the reviewer's decision is final — approved responses proceed normally, rejected ones are reframed as needing follow-up with the reviewer's note relayed to the user. The output guardrail (§8) is the backstop if that reframing instruction gets ignored.

## 11. Object storage (S3/MinIO)

`app/core/object_storage.py` wraps a boto3 S3 client that works against either real AWS S3 or a self-hosted MinIO (set `object_storage_endpoint_url` for the latter). Two uses:

- The **original uploaded file** (salary slip, bank statement) is persisted independently of the OCR/extraction pipeline, on upload (`app/api/routes.py`) — "what did the applicant actually submit" needs to survive on its own, separate from whatever the extraction pipeline read from it.
- **Policy source PDFs** (e.g. `Credit_Policy_2027.pdf`) that get chunked into `knowledge_chunks` for RAG stay retrievable in their original form, so a human can check the chunking against the source document.

Disabled by default (`object_storage_enabled = False`) so a local/demo run doesn't need real credentials to start — every call site checks `storage.is_enabled` and no-ops rather than raising when it's off, since "storage not configured" is an expected state in dev, not an error condition. A storage failure on upload is logged, not fatal — it doesn't block the actual document-processing turn.

## 12. Audit logging

`app/db/audit_log.py::write_audit_log` writes one row to `decision_audit_log` (see `schema.sql`) per turn that reaches the decision agent — session, detected intent, selected plugins, every plugin result, risk score and factors, human decision (if any), and the output guardrail's verdict. This is separate from (and broader than) the pre-existing `document_audit_log` table, which only covers document-processing compliance specifically.

Runs regardless of whether `user_id` is set — unlike long-term memory, which is opt-in per caller (§13), the audit trail exists for anonymous sessions too; only long-term *personalization* is opt-in, compliance logging isn't. Fails silently (logs a warning) if Postgres is unreachable, so a database outage in the audit-logging path doesn't take down the actual user-facing response — a production deployment would want this on a monitored dead-letter queue rather than a bare log line.

## 13. Short-term vs. long-term memory

**Short-term memory** — "what has been said in *this* conversation" — is handled entirely by **LangGraph's built-in checkpointer** (`MemorySaver`, in-process, keyed by `thread_id = session_id`). Each call to `compiled_graph.invoke(...)` with the same `thread_id` automatically has access to the accumulated state from prior turns in that thread — including a paused-and-resumed `interrupt()` cycle for human review.

`MemorySaver` is in-process, meaning state is lost on process restart — an accepted tradeoff for a portfolio build. The swap to survive restarts is one line — `langgraph.checkpoint.postgres.PostgresSaver` instead of `MemorySaver` in `app/graph/pipeline.py` — with zero changes to any node.

**Long-term memory** — "what do we know about this *user* from previous sessions" — is a separate, explicit concern: `recall_long_term_memory` pulls durable facts for the given `user_id` at the start of the graph; `save_long_term_memory` runs a small extraction pass at the end. Both no-op if `user_id` isn't provided — long-term memory is opt-in per caller, not assumed.

## 14. Scaling notes and what's intentionally out of scope

**Deployment path:** `app/main.py` is a standard ASGI app, deployable as-is to Container Apps/ECS/Cloud Run behind Uvicorn workers; Dockerfile/Jenkinsfile/k8s overlays/ArgoCD manifests are already in this repo (`deploy/`). Swapping pgvector for a different vector store means only touching `app/rag/retriever.py`; the retrieval interface doesn't change. OpenTelemetry is already in `requirements.txt`; wiring middleware into `app/main.py` is the remaining step for production observability.

**Out of scope for this revision:**
- Real credit bureau integration (mocked, clearly labeled — `credit_score.py`)
- A live RBI repo-rate feed (mocked, clearly labeled — `repo_rate_service.py`)
- Authentication/authorization on the API layer (`user_id` is accepted as-given from the caller; a real deployment would derive it from a verified auth token)
- Rate limiting and abuse protection
- Fact conflict resolution in long-term memory
- Output-guardrail verification of *every* numeric claim against source plugin/RAG data (currently only checks for foreign PII and reviewer-decision contradiction, not general numeric hallucination)
- A frontend (this is a backend/agent-architecture portfolio piece)
