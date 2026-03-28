"""
app.py — The Data and AI Pulse Streamlit Dashboard

Displays the latest news from 13 curated agents covering Microsoft Fabric,
Azure AI Foundry, Power BI, Copilot Studio, and Technology Gadgets.

Run with:
    streamlit run app.py
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

from agents import (
    AGENTS,
    FetchResult,
    NewsAgent,
    NewsItem,
    _parse_item_date,
    get_active_agents,
    get_active_categories,
)

_CONFIG_FILE = Path(__file__).parent / "agents_config.json"


def _config_mtime() -> str:
    """Return the last-modified timestamp of agents_config.json.
    Used as part of the fetch cache key so any admin change busts the cache.
    """
    if _CONFIG_FILE.exists():
        return str(int(_CONFIG_FILE.stat().st_mtime))
    return "0"


def _app_cfg() -> dict:
    """Return the app display config section from agents_config.json."""
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh).get("app", {})
    except Exception:
        return {}


_APP = _app_cfg()
_COLORS = _APP.get("colors", {})
_APP_TITLE     = _APP.get("title",     "The Data and AI Pulse")
_APP_SUBTITLE  = _APP.get("subtitle",  "Microsoft Fabric &nbsp;·&nbsp; Azure AI Foundry &nbsp;·&nbsp; Power BI &nbsp;·&nbsp; Copilot Studio &nbsp;·&nbsp; Tech Gadgets")
_APP_LOGO      = _APP.get("logo_url",  "")
_APP_COPYRIGHT = _APP.get("copyright", "© 2026 Pearl Innovations Limited. All rights reserved.")

load_dotenv()

# ---------------------------------------------------------------------------
# Page configuration  (MUST be the very first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=_APP_TITLE,
    page_icon=_APP_LOGO or "📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS theme
# ---------------------------------------------------------------------------
# st.markdown(unsafe_allow_html=True) bypasses DOMPurify so attribute
# selectors like [data-testid] and [role] reach the Streamlit components.
#
# Tab colours are computed from st.context.theme.type ("dark"/"light"),
# which reflects the Streamlit theme toggle — not the OS preference.
# ---------------------------------------------------------------------------
_is_dark = st.context.theme.get("type") == "dark"
_tab_inactive = "#c8cce8" if _is_dark else "#111111"
_tab_active   = _COLORS.get("accent", "#0078D4")

_sidebar_bg     = _COLORS.get("sidebar_bg",            "#12172b")
_sidebar_text   = _COLORS.get("sidebar_text",          "#d4d8ec")
_sidebar_btn    = _COLORS.get("sidebar_button",        "#E63946")
_sidebar_btn_hv = _COLORS.get("sidebar_button_hover",  "#c9303c")
_header_grad    = _COLORS.get("header_gradient",       "linear-gradient(135deg, #0f1320 0%, #1c2040 60%, #3d1022 100%)")

st.markdown(
    f"""
<style>
/* ── Base ───────────────────────────────────────────────────────── */
[data-testid="stAppViewContainer"] > .main {{
    background: var(--background-color, #f0f2f7);
}}

/* ── Sidebar ────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{background: {_sidebar_bg} !important;}}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div  {{color: {_sidebar_text} !important;}}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3   {{color: #ffffff !important;}}
[data-testid="stSidebar"] .stButton button {{
    background: {_sidebar_btn}; color: white; border: none;
    border-radius: 8px; font-weight: 600;
}}
[data-testid="stSidebar"] .stButton button:hover {{background: {_sidebar_btn_hv};}}

/* ── Top header bar ─────────────────────────────────────────────── */
.header-bar {{
    display: flex; align-items: center; gap: 14px;
    background: {_header_grad};
    color: white; padding: 14px 24px; border-radius: 14px;
    margin-bottom: 6px; box-shadow: 0 4px 18px rgba(0,0,0,0.4);
}}
""" + """
.header-title {font-size:1.5rem; font-weight:800; margin:0; color:white !important; flex:1;}
.header-sub   {font-size:0.78rem; opacity:0.88; color:white !important; flex:1;}
.stat-pill {
    background: rgba(255,255,255,0.18);
    border: 1px solid rgba(255,255,255,0.35);
    border-radius: 20px; padding: 4px 14px;
    font-size: 0.78rem; font-weight: 700; color: white; white-space: nowrap;
}
.stat-pill.err {background: rgba(231,76,60,0.6); border-color: #e74c3c;}

/* ── News card ──────────────────────────────────────────────────── */
/* var(--background-color) is white in light / near-black in dark   */
.news-card {
    background: var(--background-color, white);
    border-radius: 12px; padding: 18px 18px 12px;
    margin-bottom: 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    border-top: 4px solid var(--c, var(--primary-color, #0078D4));
}

/* ── Card header ────────────────────────────────────────────────── */
.card-head {
    display: flex; align-items: center; gap: 10px;
    margin-bottom: 12px; padding-bottom: 10px;
    border-bottom: 1px solid rgba(128,128,128,0.15);
}
.card-icon {font-size: 1.7rem; line-height: 1; flex-shrink: 0;}
.card-meta  {flex: 1;}
.card-name  {font-size: 0.98rem; font-weight: 800; color: var(--text-color, #111); margin: 0;}
.card-desc  {font-size: 0.73rem; color: var(--text-color, #999); opacity: 0.6; margin-top: 2px;}
.badge {
    display: inline-block; border-radius: 10px; padding: 2px 8px;
    font-size: 0.68rem; font-weight: 800; color: white;
    margin-left: 6px; vertical-align: middle;
}
.article-count {
    font-size: 0.72rem; font-weight: 700;
    background: rgba(128,128,128,0.1);
    border-radius: 10px; padding: 3px 9px;
    color: var(--text-color, #555); opacity: 0.85;
}

/* ── Article entries ────────────────────────────────────────────── */
.entry {padding: 9px 0; border-bottom: 1px solid rgba(128,128,128,0.12);}
.entry:last-child {border-bottom: none; padding-bottom: 0;}
.entry-title,
a.entry-title:link,
a.entry-title:visited {
    font-size: 0.90rem; font-weight: 700;
    color: #0078D4 !important;
    text-decoration: none; line-height: 1.35;
    display: block; margin-bottom: 3px;
}
.entry-title:hover, a.entry-title:hover {color: #005fa3 !important; text-decoration: underline;}
.entry-meta    {font-size: 0.71rem; color: var(--text-color, #aaa); opacity: 0.65; margin-bottom: 4px;}
.entry-excerpt {font-size: 0.82rem; color: var(--text-color, #555); opacity: 0.85; line-height: 1.55; margin-bottom: 5px;}
.kp-list {margin: 4px 0 5px; padding-left: 16px;}
.kp-list li {font-size: 0.77rem; color: var(--text-color, #666); opacity: 0.75; margin-bottom: 2px; line-height: 1.4;}
.read-more {
    font-size: 0.74rem; font-weight: 700;
    color: var(--c, var(--primary-color, #0078D4));
    text-decoration: none; border-bottom: 1px dotted;
}
.read-more:hover {border-bottom-style: solid;}

/* ── Error card ─────────────────────────────────────────────────── */
.error-card {
    background: rgba(231,76,60,0.08);
    border-left: 5px solid #e74c3c;
    border-radius: 12px; padding: 16px;
    color: #c0392b; font-size: 0.84rem;
}
.error-card b {font-size: 0.94rem;}

/* ── Show-more expander ─────────────────────────────────────────── */
details.show-more {
    margin-top: 10px;
    border-top: 1px dashed rgba(128,128,128,0.25);
    padding-top: 8px;
}
details.show-more summary {
    cursor: pointer; font-size: 0.78rem; font-weight: 700;
    color: var(--c, var(--primary-color, #0078D4));
    list-style: none; display: flex; align-items: center;
    gap: 5px; user-select: none; padding: 4px 0;
}
details.show-more summary::-webkit-details-marker {display: none;}
details.show-more summary::before {
    content: '▶'; font-size: 0.6rem; transition: transform 0.2s;
}
details.show-more[open] summary::before {transform: rotate(90deg);}
details.show-more[open] summary {margin-bottom: 6px;}

/* ── Timestamp / footer ─────────────────────────────────────────── */
.ts {font-size:0.68rem; color:var(--text-color,#ccc); opacity:0.45; text-align:right; margin-top:8px;}
</style>
""",
    unsafe_allow_html=True,
)

# Tab colours injected separately so we can use Python-computed values
# based on st.context.theme.type ("dark"/"light") — the Streamlit toggle.
st.markdown(
    f"""
<style>
[data-testid="stTabs"] [role="tab"],
[data-testid="stTabs"] [role="tab"] p,
[data-testid="stTabs"] [role="tab"] div,
[data-baseweb="tab"],
[data-baseweb="tab"] p,
[data-baseweb="tab"] div {{
    color: {_tab_inactive} !important;
    font-weight: 600; font-size: 0.88rem;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"],
[data-testid="stTabs"] [role="tab"][aria-selected="true"] p,
[data-testid="stTabs"] [role="tab"][aria-selected="true"] div,
[data-baseweb="tab"][aria-selected="true"],
[data-baseweb="tab"][aria-selected="true"] p,
[data-baseweb="tab"][aria-selected="true"] div {{
    color: {_tab_active} !important;
    font-weight: 800;
}}
[data-testid="stTabs"] [role="tab"]:hover,
[data-testid="stTabs"] [role="tab"]:hover p,
[data-testid="stTabs"] [role="tab"]:hover div,
[data-baseweb="tab"]:hover,
[data-baseweb="tab"]:hover p,
[data-baseweb="tab"]:hover div {{
    color: {_tab_active} !important;
}}
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Cached parallel fetch
# ---------------------------------------------------------------------------

@st.cache_data(ttl=int(os.getenv("CACHE_TTL_MINUTES", "30")) * 60, show_spinner=False)
def fetch_all_news(agent_names: tuple) -> Dict[str, FetchResult]:
    """Fetch all agents in parallel. Results are cached for TTL minutes.
    The tuple includes a config mtime token so admin changes bust the cache.
    """
    timeout = int(os.getenv("FETCH_TIMEOUT_SECONDS", "20"))
    # Strip the trailing mtime token before looking up agent names
    real_names = agent_names[:-1]
    agent_map: Dict[str, NewsAgent] = {a.name: a for a in get_active_agents()}
    results: Dict[str, FetchResult] = {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        future_to_name = {
            pool.submit(agent_map[name].fetch, timeout): name
            for name in real_names
            if name in agent_map
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                ag = agent_map[name]
                results[name] = FetchResult(
                    agent_name=ag.name,
                    agent_icon=ag.icon,
                    agent_color=ag.color,
                    category=ag.category,
                    source_url=ag.url,
                    resolved_url=ag.url,
                    items=[],
                    is_listing_page=False,
                    fetch_timestamp="",
                    error=str(exc),
                )
    return results


# ---------------------------------------------------------------------------
# Card renderer
# ---------------------------------------------------------------------------

def _fmt_date(raw: str) -> str:
    """Format a raw date string into a readable form like 'Mar 15, 2026'."""
    if not raw:
        return ""
    dt = _parse_item_date(raw)
    if dt:
        return dt.strftime("%b %d, %Y")
    # Fallback: trim ISO strings, return as-is otherwise
    if "T" in raw:
        return raw[:10]
    return raw[:30]


def _has_match(item: NewsItem, query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    return q in item.title.lower() or q in item.excerpt.lower()


def _build_entry_html(item: NewsItem, color: str) -> str:
    """Render a single article entry as an HTML block."""
    meta_parts: List[str] = []
    if item.date:
        meta_parts.append(f"📅 {_fmt_date(item.date)}")
    if item.author:
        meta_parts.append(f"✍️ {item.author}")
    meta_html = " &nbsp;·&nbsp; ".join(meta_parts)

    kp_html = ""
    if item.key_points:
        lis = "".join(f"<li>{kp}</li>" for kp in item.key_points[:8])
        kp_html = f'<ul class="kp-list">{lis}</ul>'

    excerpt = item.excerpt[:380].rstrip()
    if len(item.excerpt) > 380:
        excerpt += "…"

    return f"""
    <div class="entry">
        <a class="entry-title" href="{item.url}" target="_blank">{item.title}</a>
        {"<div class='entry-meta'>" + meta_html + "</div>" if meta_html else ""}
        <div class="entry-excerpt">{excerpt}</div>
        {kp_html}
        <a class="read-more" href="{item.url}" target="_blank" style="--c:{color};">Read full article →</a>
    </div>"""


def render_card(result: FetchResult, search: str = "") -> None:
    color = result.agent_color

    if not result.ok:
        st.html(
            f"""<div class="error-card">
                <b>{result.agent_icon} {result.agent_name}</b><br>
                ⚠️ {result.error or "No content could be retrieved."}
                <div class="ts">Attempted {result.fetch_timestamp}</div>
            </div>"""
        )
        return

    badge = (
        f'<span class="badge" style="background:{color};">{result.category}</span>'
    )
    src_urls = getattr(result, 'source_urls', [])
    src_note = (
        f' &nbsp;·&nbsp; {len(src_urls)} sources'
        if len(src_urls) > 1 else ""
    )
    count_label = (
        f'<span class="article-count">'
        f'{len(result.items)} article{"s" if len(result.items) != 1 else ""}'
        f'{src_note}'
        f'</span>'
    )

    # Card header + all articles in ONE st.html() call so show-more stays inside the card
    matched = [item for item in result.items if _has_match(item, search)]

    if not matched:
        st.html(
            f'<div class="news-card" style="--c:{color};">'  
            f'<div class="card-head"><span class="card-icon">{result.agent_icon}</span>'
            f'<div class="card-meta"><div class="card-name">{result.agent_name}{badge}</div></div>'
            f'{count_label}</div>'
            f'<p style="color:#bbb;font-size:0.82rem;padding:4px 0 8px;">'
            f'No matching articles for this search.</p></div>'
        )
        return

    preview_items = matched[:5]
    extra_items   = matched[5:]

    preview_html  = "".join(_build_entry_html(i, color) for i in preview_items)

    more_html = ""
    if extra_items:
        extra_inner = "".join(_build_entry_html(i, color) for i in extra_items)
        more_html = (
            f'<details class="show-more" style="--c:{color};">'
            f'<summary>Show {len(extra_items)} more article{"s" if len(extra_items) != 1 else ""}</summary>'
            f'{extra_inner}'
            f'</details>'
        )

    st.html(
        f'<div class="news-card" style="--c:{color};">'
        f'<div class="card-head">'
        f'<span class="card-icon">{result.agent_icon}</span>'
        f'<div class="card-meta">'
        f'<div class="card-name">{result.agent_name}{badge}</div>'
        f'<div class="card-desc" style="margin-top:3px;">{result.category}</div>'
        f'</div>'
        f'{count_label}'
        f'</div>'
        f'{preview_html}'
        f'{more_html}'
        f'<div class="ts">Fetched {result.fetch_timestamp}</div>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar(results: Optional[Dict[str, FetchResult]], agents: list) -> str:
    """Renders sidebar and returns the search query string."""
    if _APP_LOGO:
        st.sidebar.markdown(
            f'<div style="background:white;border-radius:8px;padding:8px 12px;'
            f'margin-bottom:6px;text-align:center;">'
            f'<img src="{_APP_LOGO}" style="max-width:190px;width:100%;height:auto;" />'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.sidebar.markdown(f"#### {_APP_TITLE}")
    st.sidebar.caption(f"Real-time news · {len(agents)} curated agents")
    st.sidebar.markdown("---")

    if st.sidebar.button("🔄  Refresh All News", use_container_width=True):
        fetch_all_news.clear()
        st.rerun()

    st.sidebar.markdown("### 🔎 Search")
    search_query = st.sidebar.text_input(
        "search",
        placeholder="e.g. AI, SQL, pipeline…",
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")

    if results:
        loaded = sum(1 for r in results.values() if r.ok)
        total = len(results)
        st.sidebar.markdown(f"### 🤖 Agents  ({loaded}/{total} loaded)")
        for agent in agents:
            r = results.get(agent.name)
            if r is None:
                status_icon = "⏳"
            elif r.ok:
                status_icon = "✅"
            else:
                status_icon = "❌"
            n = len(r.items) if (r and r.ok) else 0
            article_note = f"  `{n}`" if n else ""
            st.sidebar.markdown(f"{status_icon} {agent.icon} {agent.name}{article_note}")

    st.sidebar.markdown("---")
    st.sidebar.caption("News cached 30 min · Click Refresh to update")

    return search_query


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _render_grid(agents_to_show, results, search_query: str) -> None:
    """Render agents in a 2-column grid."""
    if not agents_to_show:
        st.info("No agents in this category.")
        return

    # Search pre-filter: hide cards where zero items match (keep error cards)
    if search_query:
        agents_to_show = [
            a for a in agents_to_show
            if not results.get(a.name)
            or results[a.name].error
            or any(_has_match(item, search_query) for item in results[a.name].items)
        ]
        if not agents_to_show:
            st.warning(
                f"No articles found matching **{search_query}**. Try a different keyword."
            )
            return

    for i in range(0, len(agents_to_show), 2):
        cols = st.columns(2, gap="large")
        for j, agent in enumerate(agents_to_show[i : i + 2]):
            with cols[j]:
                result = results.get(agent.name)
                if result:
                    render_card(result, search=search_query)
                else:
                    st.html(
                        f'<div class="error-card">⏳ Loading {agent.icon} {agent.name}…</div>'
                    )


def main() -> None:
    agents = get_active_agents()
    categories = get_active_categories()
    all_names = tuple(a.name for a in agents) + (_config_mtime(),)

    # Fetch (cached)
    with st.spinner("⏳ Fetching latest news from all agents…"):
        results = fetch_all_news(all_names)

    # Sidebar — search + status
    search_query = render_sidebar(results, agents)

    # ── Compact header bar with live stats ──────────────────────────
    loaded = sum(1 for r in results.values() if r.ok)
    total_articles = sum(len(r.items) for r in results.values() if r.ok)
    errors = len(results) - loaded
    error_pill = (
        f'<span class="stat-pill err">⚠️ {errors} error{"s" if errors != 1 else ""}</span>'
        if errors else ""
    )
    st.html(
        f"""<div class="header-bar">
            <div style="flex:1;">
                <div class="header-title">{_APP_TITLE}</div>
                <div class="header-sub">{_APP_SUBTITLE}</div>
            </div>
            <span class="stat-pill">📡 {len(agents)} agents</span>
            <span class="stat-pill">✅ {loaded} loaded</span>
            <span class="stat-pill">📰 {total_articles} articles</span>
            {error_pill}
        </div>"""
    )

    # ── Category tabs ────────────────────────────────────────────────
    # Build tab labels:  "🌐 All"  +  one per category
    category_agents: Dict[str, list] = {}
    for cat in categories:
        category_agents[cat] = [a for a in agents if a.category == cat]

    tab_labels = ["🌐 All"] + categories
    tabs = st.tabs(tab_labels)

    # "All" tab — show every agent in 2-column grid
    with tabs[0]:
        if search_query:
            st.caption(f'Showing results for: **{search_query}**')
        _render_grid(list(agents), results, search_query)

    # Per-category tabs
    for idx, cat in enumerate(categories):
        with tabs[idx + 1]:
            agents_in_cat = category_agents[cat]
            cat_articles = sum(
                len(results[a.name].items)
                for a in agents_in_cat
                if results.get(a.name) and results[a.name].ok
            )
            st.caption(
                f"{len(agents_in_cat)} agent{'s' if len(agents_in_cat) != 1 else ''} · "
                f"{cat_articles} article{'s' if cat_articles != 1 else ''}"
            )
            _render_grid(agents_in_cat, results, search_query)


    st.markdown(
        f"<p style='text-align:center;font-size:0.72rem;opacity:0.5;margin-top:2rem;'>"
        f"{_APP_COPYRIGHT}"
        f"</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
