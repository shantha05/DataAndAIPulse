# The Data and AI Pulse

A Streamlit dashboard that aggregates and displays the latest news across Microsoft Fabric, Azure AI Foundry, Power BI, Copilot Studio, and consumer technology — curated by a configurable fleet of news agents and an AI Chat assistant powered by Microsoft Semantic Kernel.

Built by [Pearl Innovations](https://pearlinnovations.co.nz).

---

## Features

- **14 built-in news agents** covering Microsoft Fabric, Power BI, Azure AI Foundry, Copilot Studio, Real-Time Intelligence, Data Factory, and more
- **Category tabs** for focused browsing (All, Analytics, AI, Power BI, Azure AI, Copilot, Real-Time, Platform, etc.)
- **Full-text search** across all articles in the sidebar
- **Parallel fetching** — all agents run concurrently so the page loads fast
- **AI Chat page** — conversational assistant backed by Microsoft Semantic Kernel that can answer questions about the latest news using live data fetched from the agent fleet
- **Admin page** — add, edit, disable, and override agents without touching code
- **Dark/light mode** — follows the Streamlit theme toggle
- **All configuration in one file** — branding, colors, agent definitions, and runtime settings live in `agents_config.json`

---

## Project Structure

```
DataAndAIPulseAgent/
├── app.py                  # Main Streamlit dashboard
├── agents.py               # Agent data models, HTTP fetching, HTML parsing
├── agents_sk.py            # Semantic Kernel agent integration (AI Chat backend)
├── agents_config.json      # Central config: agents, settings, app branding
├── pages/
│   ├── AIChat.py           # AI Chat page (Semantic Kernel + streaming UI)
│   └── Admin.py            # Admin UI for managing agents
├── requirements.txt
├── .env.example            # Environment variable template
└── .gitignore
```

---

## Requirements

- Python 3.10 or later
- Internet access (agents fetch live news from public URLs)
- Azure OpenAI or OpenAI API credentials (required for AI Chat only)

---

## Quickstart

### 1. Clone the repository

```bash
git clone https://github.com/your-org/DataAndAIPulseAgent.git
cd DataAndAIPulseAgent
```

### 2. Create and activate a virtual environment

```bash
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key (for AI Chat) |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | Chat model deployment name (e.g. `gpt-4o-mini`) |
| `OPENAI_API_KEY` | OpenAI API key (alternative to Azure OpenAI) |
| `FETCH_TIMEOUT_SECONDS` | Per-URL request timeout (default: 20) |
| `CACHE_TTL_MINUTES` | How long fetched results are cached (default: 30) |

The main dashboard runs without any API key. API credentials are only required for the **AI Chat** page.

### 5. Run the app

```bash
streamlit run app.py
```

The dashboard opens at [http://localhost:8501](http://localhost:8501).

---

## AI Chat

The **AI Chat** page (`pages/AIChat.py`) provides a conversational interface to the news agent fleet, powered by [Microsoft Semantic Kernel](https://github.com/microsoft/semantic-kernel) — Microsoft's open-source agent orchestration SDK.

### How orchestration works

Unlike a hardcoded pipeline where the app decides which data to fetch, Semantic Kernel uses the LLM itself as the orchestrator. When a user asks a question, the `ChatCompletionAgent`:

1. Receives the question and a description of all available tools
2. **Reasons autonomously** about which tools to call and in what order — no fixed logic
3. Calls those tools (one or more), receives results, reasons again if needed
4. Synthesises a final answer grounded in the live data it retrieved

For example, a question like *"What's the latest on Fabric and Copilot Studio?"* may cause the agent to call `list_agents()` to discover available agents, then call `fetch_agent_news()` twice — once for Fabric, once for Copilot Studio — before composing a combined answer. The app code never hardcodes this sequence; the LLM decides it.

### Plugin and tool-calling pattern

The bridge between Semantic Kernel and the existing news scrapers is `agents_sk.py`. It follows SK's **plugin** pattern:

- `NewsPlugin` is a plain Python class; its methods are decorated with `@kernel_function`
- The `@kernel_function` decorator registers each method as a named tool in the SK kernel, including its description — which the LLM reads to decide when to call it
- SK serialises method signatures and descriptions into the LLM's function-calling schema automatically
- `agents.py` (the scraping layer) is **never modified** — `NewsPlugin` wraps it as-is

```python
# agents_sk.py — simplified example of the plugin pattern
class NewsPlugin:
    @kernel_function(description="Fetch latest articles from a named news agent")
    def fetch_agent_news(self, agent_name: str, max_items: int = 10) -> str:
        agent = self._agents[agent_name]
        articles = agent.fetch()          # delegates to existing agents.py logic
        return json.dumps(articles)       # returns structured data to the LLM
```

### Architecture

```
pages/AIChat.py  (Streamlit UI)
    │  calls stream_agent() — sync wrapper for st.write_stream()
    ▼
agents_sk.py
    ├── create_agent()      — builds ChatCompletionAgent with NewsPlugin attached
    ├── new_thread()        — creates ChatHistoryAgentThread (per-session state)
    └── stream_agent()      — runs async SK invoke_stream() in a daemon thread
            │
            ▼
    ChatCompletionAgent  (Semantic Kernel 1.41+)
            │  LLM autonomously decides which tools to call and in what order
            ▼
    NewsPlugin  (KernelPlugin with @kernel_function tools)
            ├── list_agents()          — discover available agents + categories
            ├── fetch_agent_news()     — fetch articles from one specific agent
            └── search_all_news()      — parallel keyword search across all agents
                        │
                        ▼
            NewsAgent fleet  (agents.py)  — live web scraping via requests + BeautifulSoup
```

### Key components

| Component | Role |
|---|---|
| `ChatCompletionAgent` | SK orchestrator — autonomously plans and calls tools via LLM function-calling |
| `NewsPlugin` | SK plugin — wraps the news fleet as three `@kernel_function` tools |
| `@kernel_function` | Decorator that registers Python methods as LLM-callable tools with descriptions |
| `ChatHistoryAgentThread` | Per-session conversation state — maintains multi-turn context (SK 1.41+ API) |
| `AzureChatCompletion` | Azure OpenAI connector (`api_version: 2024-12-01-preview`) |
| `stream_agent()` | Sync generator bridging async SK streaming to Streamlit's `st.write_stream()` |
| `agents.py` | Unchanged scraping layer — wrapped by `NewsPlugin`, not modified for SK |

### Using AI Chat

1. Navigate to **AI Chat** in the sidebar
2. Type a question or click one of the suggestion buttons, e.g.:
   - *"What's new in Microsoft Fabric this week?"*
   - *"Summarise the latest Azure AI Foundry announcements"*
   - *"Find news about Copilot Studio agents"*
3. The agent autonomously decides which news sources to query, fetches live articles, and streams a grounded summarised answer token-by-token

---

## Configuration

All behaviour is controlled by `agents_config.json`:

```jsonc
{
  "settings": {
    "cutoff_days": 90,   // articles older than this are filtered out
    "max_pages": 10,     // max pagination pages to follow per agent
    "max_items": 50      // max articles to keep per agent
  },
  "app": {
    "title": "The Data and AI Pulse",
    "subtitle": "...",
    "logo_url": "...",
    "copyright": "...",
    "colors": { ... }    // sidebar, header, accent colors
  },
  "builtin_agents": [ ... ],   // the 14 pre-defined agents
  "disabled_agents": [],       // names of agents to hide
  "custom_agents": [],         // user-defined agents added via Admin
  "overrides": {}              // per-agent field overrides (url, color, etc.)
}
```

### Managing agents via the Admin page

Navigate to **Admin** in the sidebar. From there you can:

- **Edit** any built-in agent's name, URL(s), category, icon, color, and description
- **Disable** agents you don't want to see on the main dashboard
- **Add custom agents** pointing to any publicly accessible URL
- Save changes — they take effect immediately on the next refresh

---

## How agents work

Each agent is defined by one or more URLs. On refresh, every agent:

1. Fetches the URL(s) in parallel using `requests`
2. Detects whether the response is a listing page (multiple `<article>` elements or heading-linked cards) or a single article
3. Parses article titles, URLs, dates, authors, and excerpts using `BeautifulSoup`
4. Deduplicates and sorts by date, keeping the most recent `max_items` articles

Supported page types include WordPress blogs, Microsoft Dev Blogs, Ars Technica, and any HTML site with semantic `<article>` markup or linked heading cards.

---

## License

© 2026 Pearl Innovations Limited. All rights reserved.
