# LoanIQ — Streamlit Frontend

A minimal, single-file chat UI over the FastAPI backend. No business logic lives here — it only calls `/chat` and `/documents/upload` and renders what comes back, matching the separation of concerns in the backend itself (deterministic logic in plugins, not in the UI layer).

## Run

```bash
# from the project root, with the backend already running on :8000
pip install -r frontend/requirements.txt
streamlit run frontend/app.py
```

Opens at `http://localhost:8501`.

## Configuration

The backend URL defaults to `http://localhost:8000/api/v1`. Override it either:

- Via environment variable before launch: `LOANIQ_API_URL=http://your-host:8000/api/v1 streamlit run frontend/app.py`
- Or live, in the app's sidebar under **⚙️ Settings**

## What it does

- **Chat** — free-form questions (policy, eligibility, EMI) via `POST /chat`
- **Document upload** — Aadhaar/PAN/salary slip images via `POST /documents/upload`, sidebar panel
- **Live plugin results** — the sidebar renders whatever `plugin_results` the last API call returned (eligibility verdict, EMI breakdown, offers, document extraction) as compact cards — this updates automatically as new plugins are added on the backend, since the renderer reads keys generically rather than hardcoding one layout per plugin
- **Session management** — one Streamlit session = one backend `session_id` = one LangGraph checkpointer thread; "Start new session" in the sidebar resets all three

## What it deliberately doesn't do

- No auth (matches the backend's current POC scope — see `docs/ARCHITECTURE.md` §12)
- No `/analyzers/bank-statement` or `/analyzers/financial-statement` UI yet — those are currently JSON-payload endpoints meant for system-to-system integration (see README's "Integrating your existing bank/financial statement analyzers" section), not something an end applicant would submit by hand. Worth adding a form for internal/ops use if that becomes a real need.
- No streaming responses — `POST /chat` returns a complete response, so the UI shows a spinner rather than a token-by-token stream. Adding streaming would require a corresponding backend change (SSE or websocket) that doesn't exist yet.
