"""
AIChat.py — AI-powered chat page for The Data and AI Pulse.

Uses a Semantic Kernel ChatCompletionAgent backed by the NewsPlugin to answer
questions about the latest Microsoft Data & AI news, grounded in live content
fetched from the agent fleet in real time.
"""

import logging
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import configure_logging
configure_logging()
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="AI Chat — Data and AI Pulse",
    page_icon="🤖",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
/* ── Background ─────────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] > .main {
    background: var(--background-color, #f0f2f7);
}

/* ── Sidebar ────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {background: #12172b !important;}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div  {color: #d4d8ec !important;}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3   {color: #ffffff !important;}
[data-testid="stSidebar"] .stButton button {
    background: #E63946; color: white; border: none;
    border-radius: 8px; font-weight: 600;
}
[data-testid="stSidebar"] .stButton button:hover {background: #c9303c;}

/* ── Top header bar ─────────────────────────────────────────────── */
.header-bar {
    display: flex; align-items: center; gap: 14px;
    background: linear-gradient(135deg, #0f1320 0%, #1c2040 60%, #3d1022 100%);
    color: white; padding: 14px 24px; border-radius: 14px;
    margin-bottom: 10px; box-shadow: 0 4px 18px rgba(0,0,0,0.4);
}
.header-title {font-size:1.5rem; font-weight:800; margin:0; color:white !important; flex:1;}
.header-sub   {font-size:0.82rem; opacity:0.9; color:white !important; margin-top:2px;}

/* Tighten chat bubbles */
.stChatMessage { padding: 10px 14px !important; }
/* Suggestion buttons in sidebar */
section[data-testid="stSidebar"] .stButton button {
    text-align: left !important;
    white-space: normal !important;
    height: auto !important;
    padding: 8px 12px !important;
    font-size: 0.82rem !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Prerequisite checks — show clear guidance before attempting imports
# ---------------------------------------------------------------------------

def _sk_installed() -> bool:
    try:
        import semantic_kernel  # noqa: F401
        return True
    except ImportError:
        return False


def _credentials_present() -> bool:
    from dotenv import load_dotenv
    load_dotenv()
    return bool(
        os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    )


def _health_check_azure_config() -> tuple[bool, str]:
    """
    Validate Azure OpenAI configuration and connectivity.
    Returns (is_ok, message).
    """
    from dotenv import load_dotenv
    import socket
    from urllib.parse import urlparse
    
    load_dotenv()
    
    azure_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    azure_deploy = (
        os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or ""
    ).strip()
    
    # If using OpenAI instead, skip Azure checks
    if not azure_key or not azure_endpoint:
        return True, ""  # OpenAI path, not an error
    
    # Validate endpoint format
    if not azure_endpoint.startswith(("http://", "https://")):
        return False, (
            "❌ **AZURE_OPENAI_ENDPOINT format invalid.** "
            "Should start with `https://` (e.g., `https://myresource.openai.azure.com/`)"
        )
    
    # Validate deployment name
    if not azure_deploy:
        return False, (
            "❌ **AZURE_OPENAI_CHAT_DEPLOYMENT_NAME is not set.** "
            "Add your deployment name (e.g., `gpt-4o`, `gpt-4o-mini`) to `.env`."
        )
    
    # Validate DNS resolution
    parsed = urlparse(azure_endpoint)
    host = parsed.hostname
    if not host:
        return False, (
            "❌ **AZURE_OPENAI_ENDPOINT is malformed.** "
            f"Could not extract hostname from `{azure_endpoint}`."
        )
    
    try:
        socket.getaddrinfo(host, 443)
    except OSError:
        return False, (
            f"❌ **Cannot resolve Azure endpoint hostname:** `{host}`  \n"
            "**Possible causes:**\n"
            "- Resource name is incorrect\n"
            "- No internet or DNS access\n"
            "- Firewall/proxy blocking Azure\n\n"
            "**Fix:** Copy the correct endpoint from Azure Portal → Azure OpenAI → Keys + Endpoint."
        )
    
    return True, ""


st.html(
    """<div class="header-bar">
        <div style="flex:1;">
            <div class="header-title">🤖 Data and AI Pulse — AI Chat</div>
            <div class="header-sub">Ask me anything about Microsoft Fabric, Azure AI Foundry, Power BI, Copilot Studio, Real-Time Intelligence, and more. I fetch live news to ground every answer.</div>
        </div>
    </div>"""
)

if not _sk_installed():
    st.error(
        "**`semantic-kernel` is not installed.**\n\n"
        "Run the following, then restart the app:\n"
        "```\npip install semantic-kernel>=1.0\n```"
    )
    st.stop()

if not _credentials_present():
    st.warning(
        "**No AI credentials found.**\n\n"
        "Add one of the following to your `.env` file and restart:\n\n"
        "**Azure OpenAI**\n"
        "```\n"
        "AZURE_OPENAI_API_KEY=<your-key>\n"
        "AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/\n"
        "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=gpt-4o\n"
        "```\n"
        "**OpenAI**\n"
        "```\nOPENAI_API_KEY=sk-...\n```"
    )
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Health check for Azure configuration (non-blocking, informational)
# ─────────────────────────────────────────────────────────────────────────────

_health_ok, _health_msg = _health_check_azure_config()
if not _health_ok:
    st.warning(f"⚠️ **Config issue detected:**\n\n{_health_msg}")

# ---------------------------------------------------------------------------
# Session-state initialisation
# ---------------------------------------------------------------------------

if "sk_agent" not in st.session_state:
    st.session_state.sk_agent = None
if "sk_thread" not in st.session_state:
    st.session_state.sk_thread = None
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []      # [{"role": "user"|"assistant", "content": str, "token_usage": dict}]
if "token_totals" not in st.session_state:
    st.session_state.token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

# ---------------------------------------------------------------------------
# Initialise the SK agent once per session
# ---------------------------------------------------------------------------

if st.session_state.sk_agent is None:
    with st.spinner("Initialising AI assistant…"):
        try:
            from agents_sk import create_agent, new_thread
            st.session_state.sk_agent  = create_agent()
            st.session_state.sk_thread = new_thread()
        except Exception as exc:
            msg = str(exc)
            if "Unable to resolve AZURE_OPENAI_ENDPOINT host" in msg:
                msg += (
                    "\n\nTip: In Azure AI Foundry or Azure Portal, copy the exact endpoint for your Azure OpenAI resource "
                    "and paste it into AZURE_OPENAI_ENDPOINT in .env."
                )
            st.error(
                f"**Failed to initialise assistant.**\n\n"
                f"```\n{msg}\n```\n\n"
                "Check your `.env` credentials and that `semantic-kernel` is installed."
            )
            st.stop()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    # ── Logo ────────────────────────────────────────────────────────
    import json as _json
    _cfg_path = Path(__file__).parent.parent / "agents_config.json"
    try:
        _logo = _json.loads(_cfg_path.read_text(encoding="utf-8")).get("app", {}).get("logo_url", "")
    except Exception:
        _logo = ""
    if _logo:
        st.markdown(
            f'<div style="background:white;border-radius:8px;padding:8px 12px;'
            f'margin-bottom:6px;text-align:center;">'
            f'<img src="{_logo}" style="max-width:190px;width:100%;height:auto;" />'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown("### 🤖 AI Chat")
    st.markdown("---")

    if st.button("🗑️  Clear conversation", use_container_width=True):
        from agents_sk import new_thread
        st.session_state.sk_thread     = new_thread()
        st.session_state.chat_messages = []
        st.session_state.token_totals  = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        st.rerun()

    st.markdown("---")
    st.markdown("**Try asking:**")

    _SUGGESTIONS = [
        "What's new in Power BI this week?",
        "Summarise the latest Azure AI Foundry announcements",
        "What are the newest Microsoft Fabric features?",
        "Any news about Copilot Studio updates?",
        "Search for news about Model Context Protocol (MCP)",
        "What's happening with Real-Time Intelligence in Fabric?",
        "Show me the latest Fabric IQ and AI announcements",
    ]

    for _s in _SUGGESTIONS:
        if st.button(_s, use_container_width=True, key=f"sug_{hash(_s)}"):
            st.session_state["_prefill"] = _s
            st.rerun()

    st.markdown("---")
    st.caption(
        "**Powered by**  \n"
        "🧠 Semantic Kernel  \n"
        "🔌 NewsPlugin (live fetch)  \n"
        "☁️ Azure OpenAI / OpenAI"
    )

    # ── Session token usage ───────────────────────────────────────────
    _t = st.session_state.token_totals
    if _t["total_tokens"] > 0:
        st.markdown("---")
        st.markdown("**Session token usage**")
        st.caption(
            f"Prompt: &nbsp;&nbsp;&nbsp;&nbsp;**{_t['prompt_tokens']:,}**  \n"
            f"Completion: **{_t['completion_tokens']:,}**  \n"
            f"Total: &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;**{_t['total_tokens']:,}**"
        )

# ---------------------------------------------------------------------------
# Replay previous messages
# ---------------------------------------------------------------------------

for _msg in st.session_state.chat_messages:
    with st.chat_message(_msg["role"]):
        st.markdown(_msg["content"])
        _u = _msg.get("token_usage", {})
        if _msg["role"] == "assistant" and _u.get("total_tokens"):
            st.caption(
                f"🔢 {_u['prompt_tokens']:,} prompt · "
                f"{_u['completion_tokens']:,} completion · "
                f"**{_u['total_tokens']:,} total**"
            )

# ---------------------------------------------------------------------------
# Chat input  (sidebar suggestion acts as prefill)
# ---------------------------------------------------------------------------

_prefill = st.session_state.pop("_prefill", None)
prompt   = st.chat_input("Ask about news, announcements, or any Data & AI topic…") or _prefill

if prompt:
    # ── Show user message ────────────────────────────────────────────────
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # ── Stream agent response ────────────────────────────────────────────
    from agents_sk import stream_agent

    _usage: dict = {}
    with st.chat_message("assistant"):
        try:
            response_text = st.write_stream(
                stream_agent(
                    st.session_state.sk_agent,
                    prompt,
                    st.session_state.sk_thread,
                    usage_out=_usage,
                )
            )
        except Exception as exc:
            logger.error("Failed to stream agent response: %s", exc, exc_info=True)
            response_text = f"⚠️ **Error generating response:**\n\n```\n{exc}\n```"
            st.error(response_text)

        # Display per-response token breakdown
        if _usage.get("total_tokens"):
            st.caption(
                f"🔢 {_usage['prompt_tokens']:,} prompt · "
                f"{_usage['completion_tokens']:,} completion · "
                f"**{_usage['total_tokens']:,} total**"
            )

    # Accumulate session totals
    for _k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        st.session_state.token_totals[_k] += _usage.get(_k, 0)

    st.session_state.chat_messages.append(
        {"role": "assistant", "content": response_text or "", "token_usage": _usage}
    )
