"""
agents_sk.py — Semantic Kernel Agent integration for The Data and AI Pulse.

Wraps the NewsAgent fleet as a KernelPlugin so a ChatCompletionAgent can
autonomously fetch, filter, and summarise news in response to user queries.

Requires:
    pip install semantic-kernel>=1.0
    .env must contain AZURE_OPENAI_* or OPENAI_API_KEY credentials.
"""

import asyncio
import json
import logging
import os
import queue as _queue
import threading as _threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Annotated, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful import — the decorator must exist at class-definition time,
# but we don't want a hard crash if the package isn't installed yet.
# ---------------------------------------------------------------------------
try:
    from semantic_kernel.functions import kernel_function
    _SK_AVAILABLE = True
except ImportError:
    _SK_AVAILABLE = False

    def kernel_function(**kwargs):          # pragma: no cover
        """No-op fallback when semantic-kernel is not installed."""
        def decorator(fn):
            return fn
        return decorator

if TYPE_CHECKING:
    from semantic_kernel.agents import ChatCompletionAgent
    from semantic_kernel.agents.chat_completion.chat_completion_agent import ChatHistoryAgentThread


# ---------------------------------------------------------------------------
# AI service factory
# ---------------------------------------------------------------------------

def _build_ai_service():
    """Return AzureChatCompletion or OpenAIChatCompletion based on env vars."""
    if not _SK_AVAILABLE:
        raise ImportError(
            "semantic-kernel is not installed.\n"
            "Run:  pip install semantic-kernel>=1.0"
        )
    azure_key      = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    # Support both naming conventions used across projects
    azure_deploy   = (
        os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or "gpt-4o"
    )
    openai_key     = os.getenv("OPENAI_API_KEY")

    if azure_key and azure_endpoint:
        from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
        return AzureChatCompletion(
            api_key=azure_key,
            endpoint=azure_endpoint,
            deployment_name=azure_deploy,
            api_version="2024-12-01-preview",
        )
    if openai_key:
        from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
        model = os.getenv("OPENAI_CHAT_MODEL_ID", "gpt-4o-mini")
        return OpenAIChatCompletion(ai_model_id=model, api_key=openai_key)

    raise EnvironmentError(
        "No AI credentials found.\n"
        "Add one of the following to your .env file:\n"
        "  AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_CHAT_DEPLOYMENT_NAME\n"
        "  OPENAI_API_KEY"
    )


# ---------------------------------------------------------------------------
# News Plugin  —  exposed as tools to the Semantic Kernel agent
# ---------------------------------------------------------------------------

class NewsPlugin:
    """
    Semantic Kernel plugin that exposes the NewsAgent fleet as callable tools.

    The ChatCompletionAgent autonomously decides which tools to invoke based on
    the user query via the LLM's function-calling capability.
    """

    def __init__(self) -> None:
        from agents import get_active_agents
        self._agents = {a.name: a for a in get_active_agents()}

    # ── Tool 1: discover what agents are available ────────────────────────

    @kernel_function(
        description=(
            "List all available news agents with their names, categories, "
            "and what topics they cover. Call this first if unsure which agent to use."
        )
    )
    def list_agents(self) -> Annotated[str, "JSON array of available news agents"]:
        items = [
            {
                "name": a.name,
                "category": a.category,
                "description": a.description,
            }
            for a in self._agents.values()
        ]
        return json.dumps(items, indent=2)

    # ── Tool 2: fetch one agent's latest articles ─────────────────────────

    @kernel_function(
        description=(
            "Fetch the latest news articles from one specific agent by name. "
            "Call list_agents first if you are unsure of the exact agent name."
        )
    )
    def fetch_agent_news(
        self,
        agent_name: Annotated[
            str,
            "The exact name of the news agent, e.g. 'Power BI', 'Fabric Analytics', "
            "'Azure AI Foundry', 'Copilot Studio'. Use list_agents to see all names.",
        ],
        max_items: Annotated[int, "How many articles to return (1–10). Default is 5."] = 5,
    ) -> Annotated[str, "Formatted news articles from this agent"]:
        agent = self._agents.get(agent_name)

        # Fuzzy match by substring if exact name wasn't found
        if agent is None:
            q = agent_name.lower()
            for k, v in self._agents.items():
                if q in k.lower() or k.lower() in q:
                    agent = v
                    break

        if agent is None:
            return (
                f"No agent found named '{agent_name}'. "
                "Use list_agents to see all available agent names."
            )

        result = agent.fetch()
        if not result.ok:
            return f"Failed to fetch from '{agent.name}': {result.error or 'unknown error'}"

        cap = max(1, min(int(max_items), 10))
        lines: List[str] = [f"## {agent.icon} {agent.name} — {agent.category}\n"]

        for idx, item in enumerate(result.items[:cap], 1):
            lines.append(f"### {idx}. {item.title}")
            if item.date:
                lines.append(f"**Date:** {item.date}")
            if item.author:
                lines.append(f"**Author:** {item.author}")
            if item.excerpt:
                lines.append(f"{item.excerpt[:350]}")
            if item.key_points:
                lines.append("**Key topics:** " + ", ".join(item.key_points[:4]))
            lines.append(f"**URL:** {item.url}\n")

        return "\n".join(lines)

    # ── Tool 3: cross-agent keyword search ───────────────────────────────

    @kernel_function(
        description=(
            "Search for news articles matching a keyword or topic across ALL available "
            "agents simultaneously. Use this when the topic spans multiple agents, "
            "or when you are unsure which agent covers the topic."
        )
    )
    def search_all_news(
        self,
        keyword: Annotated[str, "The search term or topic to look for across all news agents"],
        max_per_agent: Annotated[
            int, "Maximum results to return per agent (1–5). Default is 3."
        ] = 3,
    ) -> Annotated[str, "Matching articles grouped by agent"]:
        q = keyword.lower()
        sections: List[str] = []

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(a.fetch): a for a in self._agents.values()}
            for future in as_completed(futures):
                a = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.warning("Agent [%s] fetch failed during search: %s", a.name, exc)
                    continue
                if not result.ok:
                    continue

                cap = max(1, min(int(max_per_agent), 5))
                matches = [
                    item for item in result.items
                    if q in item.title.lower() or q in item.excerpt.lower()
                ][:cap]

                if not matches:
                    continue

                lines = [f"\n### {a.icon} {a.name}"]
                for item in matches:
                    lines.append(f"- **{item.title}** ({item.date})")
                    lines.append(f"  {item.excerpt[:220]}")
                    lines.append(f"  <{item.url}>")
                sections.append("\n".join(lines))

        if not sections:
            return f"No articles found matching '{keyword}' across any agent."

        return f"# Search results for '{keyword}'\n" + "\n".join(sections)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Data and AI Pulse Assistant — a knowledgeable, friendly expert on \
Microsoft Fabric, Azure AI Foundry, Power BI, Copilot Studio, Real-Time Intelligence, \
and related Microsoft data and AI technologies.

You have access to a live news feed through three tools:
- **list_agents** — see which news agents are available and what they cover
- **fetch_agent_news** — get the latest articles from a specific agent
- **search_all_news** — search all agents for a keyword or topic

When a user asks about news, announcements, or what is new in any of these areas:
1. Use your tools to retrieve real, up-to-date content — do NOT rely on training data alone.
2. Synthesise the fetched content into a concise, well-structured response.
3. Always include article titles, publication dates, and URLs so the user can read further.
4. If the query spans multiple topics or agents, query each relevant agent and combine results.
5. If unsure which agent to query, call list_agents first to orient yourself.

Be factual, grounded, and always cite the sources you fetched.\
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_agent() -> "ChatCompletionAgent":
    """Create and return a Semantic Kernel ChatCompletionAgent backed by NewsPlugin."""
    from semantic_kernel.agents import ChatCompletionAgent

    logger.info("Creating ChatCompletionAgent (DataAIPulseAssistant)…")
    agent = ChatCompletionAgent(
        service=_build_ai_service(),
        name="DataAIPulseAssistant",
        instructions=_SYSTEM_PROMPT,
        plugins=[NewsPlugin()],
    )
    logger.info("ChatCompletionAgent created successfully")
    return agent


def new_thread() -> "ChatHistoryAgentThread":
    """Return a fresh ChatHistoryAgentThread (one per Streamlit session)."""
    from semantic_kernel.agents.chat_completion.chat_completion_agent import ChatHistoryAgentThread
    return ChatHistoryAgentThread()


# ---------------------------------------------------------------------------
# Synchronous wrappers — safe to call from Streamlit
# ---------------------------------------------------------------------------

def ask_agent(
    agent: "ChatCompletionAgent",
    question: str,
    thread: "ChatHistoryAgentThread",
) -> str:
    """
    Send a question to the SK agent and return the full reply as a string.
    Runs the async call in a dedicated thread so it is safe to call from
    Streamlit's main thread regardless of any existing event loop.
    """
    async def _ask() -> str:
        response = await agent.get_response(messages=question, thread=thread)
        return str(response.message.content)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, _ask())
        return future.result()


def stream_agent(
    agent: "ChatCompletionAgent",
    question: str,
    thread: "ChatHistoryAgentThread",
    usage_out: Optional[dict] = None,
):
    """
    Synchronous streaming generator — yields text chunks as they arrive.
    Designed for use with ``st.write_stream()``.
    The thread object maintains full conversation history across calls.

    If *usage_out* is provided (a plain dict), it will be populated with
    ``prompt_tokens``, ``completion_tokens``, and ``total_tokens`` once the
    stream completes, making the data available to the caller for display.
    """
    chunk_q: _queue.Queue = _queue.Queue()
    usage_q: _queue.Queue = _queue.Queue()

    async def _stream() -> None:
        prompt_tokens = 0
        completion_tokens = 0
        try:
            async for chunk in agent.invoke_stream(messages=question, thread=thread):
                # chunk is AgentResponseItem[StreamingChatMessageContent]
                text = getattr(chunk.message, "content", None) or ""
                if text:
                    chunk_q.put(text)
                # Extract token-usage metadata (usually present in the last chunk)
                metadata = getattr(chunk.message, "metadata", {}) or {}
                usage = metadata.get("usage")
                if usage is None:
                    # Fallback: inspect the raw inner_content from the OpenAI client
                    inner = getattr(chunk.message, "inner_content", None)
                    if inner:
                        usage = getattr(inner, "usage", None)
                if usage:
                    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        except Exception as exc:
            logger.error("Stream error for agent %r: %s", agent.name, exc, exc_info=True)
            chunk_q.put(f"\n\n⚠️ Stream error: {exc}")
        finally:
            usage_q.put({
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            })
            chunk_q.put(None)  # sentinel

    bg = _threading.Thread(target=lambda: asyncio.run(_stream()), daemon=True)
    bg.start()

    while True:
        piece = chunk_q.get()
        if piece is None:
            break
        yield piece

    # Populate usage_out after the stream is fully consumed
    if usage_out is not None:
        try:
            usage = usage_q.get_nowait()
            usage_out.update(usage)
            if usage["total_tokens"] > 0:
                logger.info(
                    "Token usage — prompt: %d, completion: %d, total: %d",
                    usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"],
                )
        except _queue.Empty:
            pass

    bg.join()
