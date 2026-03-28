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


st.markdown("## 🤖 Data and AI Pulse — AI Chat")
st.caption(
    "Ask me anything about Microsoft Fabric, Azure AI Foundry, Power BI, "
    "Copilot Studio, Real-Time Intelligence, and more. "
    "I fetch **live news** to ground every answer."
)
st.markdown("---")

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
            st.error(
                f"**Failed to initialise assistant.**\n\n"
                f"```\n{exc}\n```\n\n"
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
