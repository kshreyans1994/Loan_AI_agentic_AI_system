"""
LoanIQ — Streamlit frontend.

A thin UI layer over the FastAPI backend (see app/api/routes.py). This
file holds no business logic — no eligibility rules, no EMI math, no
document parsing. It only renders what the API returns, which is the
same separation of concerns the backend itself follows (deterministic
logic lives in plugins, not in whatever's closest to the user).

Run:
    streamlit run frontend/app.py

Configure the backend URL via the LOANIQ_API_URL env var, or edit
DEFAULT_API_URL below.
"""
from __future__ import annotations

import os
import uuid

import requests
import streamlit as st

DEFAULT_API_URL = os.environ.get("LOANIQ_API_URL", "http://localhost:8000/api/v1")

st.set_page_config(
    page_title="LoanIQ — AI Loan Assistant",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------
# Styling — dark navy/teal/gold theme matching the project's other
# artifacts (architecture diagram, tech stack infographic).
# ---------------------------------------------------------------------
st.markdown(
    """
    <style>
    :root{
        --bg:#0A1929; --panel:#0F2942; --panel-alt:#122F4D;
        --teal:#14B8A6; --gold:#D4AF37; --ink:#E8EDF2; --muted:#8FA3B8;
        --line:#1E3A54;
    }
    .stApp{ background: radial-gradient(circle at 8% 0%, rgba(20,184,166,0.08), transparent 40%),
                          radial-gradient(circle at 95% 100%, rgba(212,175,55,0.06), transparent 45%),
                          var(--bg); }

    /* Header */
    .loaniq-header{ display:flex; align-items:center; gap:14px; margin-bottom:4px; }
    .loaniq-badge{
        width:40px; height:40px; border-radius:10px;
        background:linear-gradient(135deg, var(--teal), var(--gold));
        display:flex; align-items:center; justify-content:center;
        font-size:20px; flex-shrink:0;
    }
    .loaniq-title{ font-size:28px; font-weight:800; color:var(--ink); letter-spacing:-0.5px; margin:0;}
    .loaniq-title span{ color:var(--teal); }
    .powered-tag{
        display:inline-flex; align-items:center; gap:6px;
        font-family:'Consolas','SF Mono',monospace; font-size:11px;
        color:var(--gold); background:rgba(212,175,55,0.08);
        border:1px solid rgba(212,175,55,0.3); border-radius:20px;
        padding:4px 12px; margin-top:8px; letter-spacing:0.5px;
    }
    .powered-tag::before{ content:"✨"; font-size:11px; }

    /* Sidebar */
    section[data-testid="stSidebar"]{ background:var(--panel); border-right:1px solid var(--line); }
    section[data-testid="stSidebar"] .block-container{ padding-top:1.5rem; }

    /* Cards for plugin results */
    .result-card{
        background:linear-gradient(180deg, var(--panel-alt), var(--panel));
        border:1px solid var(--line); border-radius:10px;
        padding:12px 14px; margin-bottom:10px;
    }
    .result-card.ok{ border-left:3px solid var(--teal); }
    .result-card.err{ border-left:3px solid #E06666; }
    .result-title{ font-size:11px; text-transform:uppercase; letter-spacing:1px;
        color:var(--muted); font-weight:700; margin-bottom:6px; }
    .result-body{ font-size:12.5px; color:var(--ink); line-height:1.5; }
    .result-body b{ color:var(--teal); }

    /* Chat bubbles */
    div[data-testid="stChatMessage"]{
        background:var(--panel); border:1px solid var(--line); border-radius:12px;
    }

    .empty-state{
        text-align:center; color:var(--muted); padding:60px 20px; font-size:14px;
    }
    .memory-tag{
        font-size:11px; padding:3px 10px; border-radius:20px; display:inline-block;
        font-family:'Consolas','SF Mono',monospace;
    }
    .memory-tag.on{ color:#14B8A6; background:rgba(20,184,166,0.1); border:1px solid rgba(20,184,166,0.3); }
    .memory-tag.off{ color:#8FA3B8; background:rgba(143,163,184,0.08); border:1px solid rgba(143,163,184,0.2); }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "user_id" not in st.session_state:
    # Deliberately NOT auto-generated like session_id — an empty user_id
    # means "anonymous", which is a valid, deliberate state (long-term
    # memory is opt-in, see app/agents/long_term_memory.py). Only a
    # value the person actually enters turns it on.
    st.session_state.user_id = ""
if "messages" not in st.session_state:
    st.session_state.messages = []
if "plugin_history" not in st.session_state:
    st.session_state.plugin_history = []
if "api_url" not in st.session_state:
    st.session_state.api_url = DEFAULT_API_URL


# ---------------------------------------------------------------------
# API helpers — every network call funnels through these two functions,
# so error handling (backend down, timeout) is written once.
# ---------------------------------------------------------------------
def call_chat(message: str) -> dict | None:
    try:
        resp = requests.post(
            f"{st.session_state.api_url}/chat",
            json={
                "session_id": st.session_state.session_id,
                "message": message,
                "user_id": st.session_state.user_id or None,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Couldn't reach LoanIQ backend: {e}")
        return None


def call_upload(file_bytes: bytes, filename: str) -> dict | None:
    try:
        resp = requests.post(
            f"{st.session_state.api_url}/documents/upload",
            params={
                "session_id": st.session_state.session_id,
                "user_id": st.session_state.user_id or None,
            },
            files={"file": (filename, file_bytes)},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Upload failed: {e}")
        return None


def render_plugin_result(result: dict) -> None:
    """Renders one plugin_results entry as a small card. Kept deliberately
    generic (reads whatever keys are present) rather than one branch per
    plugin name, so a new plugin added on the backend shows up here with
    no frontend changes."""
    ok = result.get("success")
    css_class = "ok" if ok else "err"
    name = result.get("plugin_name", "unknown").replace("_", " ").title()

    st.markdown(f'<div class="result-card {css_class}">', unsafe_allow_html=True)
    st.markdown(f'<div class="result-title">{"✓" if ok else "✕"} {name}</div>', unsafe_allow_html=True)

    if ok:
        data = result.get("data", {})
        lines = []
        for key, value in data.items():
            if key in ("application_updates", "fields"):
                continue  # internal/verbose — skip in the compact card view
            label = key.replace("_", " ").title()
            lines.append(f"<b>{label}:</b> {value}")
        body = "<br>".join(lines) if lines else "No details returned."
        st.markdown(f'<div class="result-body">{body}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="result-body">{result.get("error", "Unknown error")}</div>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Sidebar — session controls, document upload, live plugin results
# ---------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 👤 Identity")
    memory_on = bool(st.session_state.user_id.strip())
    tag_class = "on" if memory_on else "off"
    tag_text = "Long-term memory: ON" if memory_on else "Long-term memory: OFF (anonymous)"
    st.markdown(f'<span class="memory-tag {tag_class}">{tag_text}</span>', unsafe_allow_html=True)
    st.caption(
        "Enter a user ID to let LoanIQ remember facts about you across "
        "sessions (e.g. stated income, preferences). Leave blank to chat "
        "anonymously — nothing is persisted long-term."
    )
    st.session_state.user_id = st.text_input(
        "User ID",
        value=st.session_state.user_id,
        placeholder="e.g. your email or a made-up test ID",
        label_visibility="collapsed",
    )

    st.divider()

    st.markdown("### 📎 Documents")
    st.caption("Upload KYC documents — Aadhaar, PAN, or salary slip.")

    uploaded_file = st.file_uploader(
        "Upload a document",
        type=["jpg", "jpeg", "png"],
        label_visibility="collapsed",
    )
    if uploaded_file is not None:
        if st.button("Process document", use_container_width=True, type="primary"):
            with st.spinner("Running OCR + document analysis..."):
                result = call_upload(uploaded_file.getvalue(), uploaded_file.name)
            if result:
                st.session_state.messages.append(
                    {"role": "user", "content": f"📎 Uploaded: {uploaded_file.name}"}
                )
                st.session_state.messages.append(
                    {"role": "assistant", "content": result["response"]}
                )
                if result.get("plugin_results"):
                    st.session_state.plugin_history = result["plugin_results"]
                st.rerun()

    st.divider()

    st.markdown("### 📊 Latest Results")
    if st.session_state.plugin_history:
        for result in st.session_state.plugin_history:
            render_plugin_result(result)
    else:
        st.markdown(
            '<div class="empty-state">Plugin results (eligibility, EMI, offers) will appear here as you chat.</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    with st.expander("⚙️ Settings"):
        st.session_state.api_url = st.text_input("Backend API URL", value=st.session_state.api_url)
        st.caption(f"Session ID: `{st.session_state.session_id[:8]}...`")
        if st.session_state.user_id:
            st.caption(f"User ID: `{st.session_state.user_id}`")
        if st.button("Start new session", use_container_width=True):
            # Deliberately does NOT touch user_id — a new session is a
            # new conversation thread, but the same person. Resetting
            # user_id here would defeat the entire point of long-term
            # memory (recalling facts ACROSS sessions).
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.session_state.plugin_history = []
            st.rerun()


# ---------------------------------------------------------------------
# Main panel — header + chat
# ---------------------------------------------------------------------
st.markdown(
    """
    <div class="loaniq-header">
        <div class="loaniq-badge">💠</div>
        <div>
            <p class="loaniq-title">Loan<span>IQ</span></p>
        </div>
    </div>
    <div class="powered-tag">Powered by AI</div>
    """,
    unsafe_allow_html=True,
)
st.caption("Ask about eligibility, EMI, loan policies — or upload a document to get started.")
st.write("")

# Suggested prompts on first load
if not st.session_state.messages:
    st.markdown("##### Try asking:")
    cols = st.columns(3)
    suggestions = [
        "What documents do I need for a personal loan?",
        "What's the EMI for a ₹5 lakh loan over 3 years?",
        "Am I eligible for a ₹6 lakh loan?",
    ]
    clicked = None
    for col, suggestion in zip(cols, suggestions):
        with col:
            if st.button(suggestion, use_container_width=True):
                clicked = suggestion
    if clicked:
        st.session_state.messages.append({"role": "user", "content": clicked})
        with st.spinner("Thinking..."):
            result = call_chat(clicked)
        if result:
            st.session_state.messages.append({"role": "assistant", "content": result["response"]})
            if result.get("plugin_results"):
                st.session_state.plugin_history = result["plugin_results"]
        st.rerun()

# Chat history
for msg in st.session_state.messages:
    avatar = "💠" if msg["role"] == "assistant" else "🧑"
    with st.chat_message(msg["role"], avatar=avatar):
        st.write(msg["content"])

# Chat input
if prompt := st.chat_input("Ask LoanIQ anything about your loan..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑"):
        st.write(prompt)

    with st.chat_message("assistant", avatar="💠"):
        with st.spinner("Thinking..."):
            result = call_chat(prompt)
        if result:
            st.write(result["response"])
            st.session_state.messages.append({"role": "assistant", "content": result["response"]})
            if result.get("plugin_results"):
                st.session_state.plugin_history = result["plugin_results"]
            st.rerun()