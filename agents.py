"""
agents.py — News-fetching agent definitions for InsightsAgent dashboard.

Each NewsAgent is responsible for:
  - Fetching content from its assigned URL
  - Auto-detecting whether the page is a listing or a single article
  - Extracting titles, excerpts, key section headings, dates, and authors
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import urljoin, urlparse, urlunparse, urlencode, parse_qs

import requests
from bs4 import BeautifulSoup

try:
    from dateutil import parser as _dateutil_parser
    _HAS_DATEUTIL = True
except ImportError:
    _HAS_DATEUTIL = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config file — single source of truth for agents, settings, and app display
# ---------------------------------------------------------------------------

_CONFIG_FILE = Path(__file__).parent / "agents_config.json"


def _load_raw_config() -> dict:
    """Load the raw config dict from agents_config.json, or return an empty dict."""
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_config(config: dict) -> None:
    """Write the config dict to agents_config.json."""
    with open(_CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class NewsItem:
    """A single article or blog post extracted by an agent."""
    title: str
    url: str
    excerpt: str
    date: str = ""
    author: str = ""
    key_points: List[str] = field(default_factory=list)


@dataclass
class FetchResult:
    """The full result returned by an agent's fetch() call."""
    agent_name: str
    agent_icon: str
    agent_color: str
    category: str
    source_url: str
    resolved_url: str
    items: List[NewsItem]
    is_listing_page: bool
    fetch_timestamp: str
    error: Optional[str] = None
    source_urls: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Ensure source_urls is always present (guards against stale cached pickles)
        if not hasattr(self, 'source_urls') or self.source_urls is None:
            object.__setattr__(self, 'source_urls', [self.source_url] if self.source_url else [])

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.items) > 0


# ---------------------------------------------------------------------------
# Constants — loaded from config with safe fallbacks
# ---------------------------------------------------------------------------

_cfg_settings = _load_raw_config().get("settings", {})
_CUTOFF_DAYS: int = int(_cfg_settings.get("cutoff_days", 90))
_MAX_PAGES:   int = int(_cfg_settings.get("max_pages",   10))
_MAX_ITEMS:   int = int(_cfg_settings.get("max_items",   50))
del _cfg_settings  # don't leak the temp var


def _parse_item_date(date_str: str) -> Optional[datetime]:
    """Parse a date string into a UTC-aware datetime. Returns None if unparseable."""
    if not date_str:
        return None
    date_str = date_str.strip()
    if _HAS_DATEUTIL:
        try:
            dt = _dateutil_parser.parse(date_str, fuzzy=True)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    # Fallback: try common strptime patterns
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            dt = datetime.strptime(date_str[:40], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _is_recent(date_str: str, cutoff: datetime) -> bool:
    """Return True if item is within the cutoff window, or if the date is unknown."""
    dt = _parse_item_date(date_str)
    if dt is None:
        return True  # cannot determine age; keep it
    return dt >= cutoff


# Regex to find a human-readable date anywhere in element text
# Matches: "March 26, 2026" | "26 March 2026" | "Mar 26, 2026" | "2026-03-26"
_DATE_RE = re.compile(
    r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?'
    r'|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'\s+\d{1,2},?\s+\d{4}\b'
    r'|\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?'
    r'|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'\s+\d{4}\b'
    r'|\b\d{4}-\d{2}-\d{2}\b',
    re.I,
)


def _extract_date_from_el(el: "BeautifulSoup") -> str:
    """Extract a date string from a BS4 element using several strategies.

    1. <time datetime="..."> (most reliable)
    2. Element with a date/time/published CSS class
    3. Regex scan of element's full text (catches 'March 26, 2026 by ...' patterns)
    """
    # Strategy 1 — <time>
    time_el = el.find("time")
    if time_el:
        raw = time_el.get("datetime", "") or time_el.get_text(strip=True)
        if raw:
            return raw[:10] if "T" in raw else raw[:40]

    # Strategy 2 — class containing date/time/published/meta/bio
    date_el = el.find(class_=re.compile(r"date|time|published|post-date|entry-date", re.I))
    if date_el:
        inner = date_el.find("time")
        if inner:
            raw = inner.get("datetime", "") or inner.get_text(strip=True)
            if raw:
                return raw[:10] if "T" in raw else raw[:40]
        text = date_el.get_text(" ", strip=True)
        m = _DATE_RE.search(text)
        if m:
            return m.group(0)
        if text:
            return text[:40]

    # Strategy 3 — regex scan of full element text (e.g. "March 26, 2026 by Author")
    full_text = el.get_text(" ", strip=True)
    m = _DATE_RE.search(full_text)
    if m:
        return m.group(0)

    return ""


_IGNORE_HEADINGS = {
    "what's new", "microsoft store", "education", "business", "developer & it",
    "company", "microsoft fabric", "visit our product blogs", "explore more",
    "popular topics", "follow this blog", "stay informed", "additional links",
    "latest posts", "create the future", "archive", "related posts",
    "more articles", "trending", "most popular", "newsletter",
}

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


# ---------------------------------------------------------------------------
# NewsAgent
# ---------------------------------------------------------------------------

class NewsAgent:
    """
    A news-fetching agent that retrieves and parses content from a given URL.
    Automatically handles both index/listing pages and single article pages.
    """

    def __init__(
        self,
        name: str,
        url: Union[str, List[str]] = "",
        category: str = "",
        description: str = "",
        icon: str = "📰",
        color: str = "#0078D4",
    ) -> None:
        self.name = name
        # Accept a single URL string or a list of URLs
        self.urls: List[str] = [url] if isinstance(url, str) else list(url)
        self.url = self.urls[0] if self.urls else ""  # primary URL (backward compat)
        self.category = category
        self.description = description
        self.icon = icon
        self.color = color

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, timeout: int = 20) -> FetchResult:
        """Fetch and parse all agent URLs, merging and deduplicating results."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Fast path: single URL — original behaviour
        if len(self.urls) == 1:
            return self._fetch_single(self.urls[0], timestamp, timeout)

        # Multi-URL: fetch in parallel then merge
        partial: Dict[str, "FetchResult"] = {}
        with ThreadPoolExecutor(max_workers=min(len(self.urls), 8)) as pool:
            future_map = {
                pool.submit(self._fetch_single, u, timestamp, timeout): u
                for u in self.urls
            }
            for future in as_completed(future_map):
                u = future_map[future]
                try:
                    partial[u] = future.result()
                except Exception as exc:
                    partial[u] = FetchResult(
                        agent_name=self.name, agent_icon=self.icon,
                        agent_color=self.color, category=self.category,
                        source_url=u, resolved_url=u,
                        items=[], is_listing_page=False,
                        fetch_timestamp=timestamp, error=str(exc),
                        source_urls=[u],
                    )

        # Merge in original URL order; deduplicate articles by URL
        all_items: List[NewsItem] = []
        seen: set = set()
        errors: List[str] = []
        any_listing = False
        first_resolved = self.urls[0]

        for u in self.urls:
            r = partial.get(u)
            if r is None:
                continue
            if r.error:
                errors.append(r.error)
                continue
            if not any_listing:
                first_resolved = r.resolved_url
            any_listing = any_listing or r.is_listing_page
            for item in r.items:
                if item.url not in seen:
                    seen.add(item.url)
                    all_items.append(item)

        if not all_items and errors:
            return FetchResult(
                agent_name=self.name, agent_icon=self.icon,
                agent_color=self.color, category=self.category,
                source_url=self.urls[0], resolved_url=self.urls[0],
                items=[], is_listing_page=False,
                fetch_timestamp=timestamp,
                error=f"{len(errors)} source(s) failed: " + "; ".join(errors[:2]),
                source_urls=list(self.urls),
            )

        return FetchResult(
            agent_name=self.name, agent_icon=self.icon,
            agent_color=self.color, category=self.category,
            source_url=self.urls[0], resolved_url=first_resolved,
            items=all_items[:_MAX_ITEMS],
            is_listing_page=any_listing,
            fetch_timestamp=timestamp,
            source_urls=list(self.urls),
        )

    def _fetch_single(self, url: str, timestamp: str, timeout: int) -> "FetchResult":
        """Fetch and parse a single URL, returning a FetchResult."""
        try:
            resp = requests.get(
                url,
                headers=_REQUEST_HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()

            resolved_url = resp.url
            try:
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                soup = BeautifulSoup(resp.text, "html.parser")

            is_listing = self._is_listing_page(soup, resolved_url)
            items = (
                self._parse_listing_paginated(soup, resolved_url, timeout)
                if is_listing
                else self._parse_article(soup, resolved_url, resp.text)
            )

            return FetchResult(
                agent_name=self.name, agent_icon=self.icon,
                agent_color=self.color, category=self.category,
                source_url=url, resolved_url=resolved_url,
                items=items, is_listing_page=is_listing,
                fetch_timestamp=timestamp, source_urls=[url],
            )

        except Exception as exc:
            logger.error("Agent [%s] URL [%s] failed: %s", self.name, url, exc)
            return FetchResult(
                agent_name=self.name, agent_icon=self.icon,
                agent_color=self.color, category=self.category,
                source_url=url, resolved_url=url,
                items=[], is_listing_page=False,
                fetch_timestamp=timestamp, error=str(exc),
                source_urls=[url],
            )

    def _next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Find the URL of the next pagination page, or None if not found."""
        # 1. <link rel="next"> in <head>
        link = soup.find("link", rel="next")
        if link and link.get("href"):
            href = link["href"]
            return href if href.startswith("http") else urljoin(current_url, href)

        # 2. <a rel="next">
        a = soup.find("a", rel="next")
        if a and a.get("href"):
            href = a["href"]
            return href if href.startswith("http") else urljoin(current_url, href)

        # 3. WordPress .next / .page-numbers links
        for a in soup.find_all("a", class_=re.compile(r"\bnext\b", re.I)):
            href = a.get("href", "")
            if href and href != current_url:
                return href if href.startswith("http") else urljoin(current_url, href)

        # 4. Text-based navigation links
        for text_pat in [r"^next\b", r"older posts", r"^[»›]$"]:
            a = soup.find("a", string=re.compile(text_pat, re.I))
            if a and a.get("href"):
                href = a["href"]
                return href if href.startswith("http") else urljoin(current_url, href)

        return None

    def _parse_listing_paginated(
        self,
        soup: BeautifulSoup,
        base_url: str,
        timeout: int,
    ) -> List[NewsItem]:
        """Extract items from a listing page, following pagination until items
        fall outside the 3-month window or we reach _MAX_PAGES."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_CUTOFF_DAYS)
        all_items: List[NewsItem] = []
        seen_urls: set = set()
        current_soup = soup
        current_url = base_url

        for page_num in range(_MAX_PAGES):
            page_items = self._parse_listing(current_soup, current_url)

            any_too_old = False
            for item in page_items:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                if not _is_recent(item.date, cutoff):
                    any_too_old = True
                    continue  # skip items older than 3 months
                all_items.append(item)
                if len(all_items) >= _MAX_ITEMS:
                    return all_items

            # Stop paginating if we've gone past the 3-month window
            if any_too_old:
                break

            # If first page had no datable items at all, don't paginate (avoid infinite loops)
            has_any_dated = any(_parse_item_date(i.date) is not None for i in page_items)
            if not has_any_dated:
                break

            next_url = self._next_page_url(current_soup, current_url)
            if not next_url or next_url == current_url:
                break

            try:
                resp = requests.get(
                    next_url, headers=_REQUEST_HEADERS,
                    timeout=timeout, allow_redirects=True,
                )
                resp.raise_for_status()
                current_url = resp.url
                try:
                    current_soup = BeautifulSoup(resp.text, "lxml")
                except Exception:
                    current_soup = BeautifulSoup(resp.text, "html.parser")
            except Exception as exc:
                logger.warning(
                    "Agent [%s] pagination stopped at page %d: %s",
                    self.name, page_num + 2, exc,
                )
                break

        return all_items

    # ------------------------------------------------------------------
    # Page-type detection
    # ------------------------------------------------------------------

    def _is_listing_page(self, soup: BeautifulSoup, url: str) -> bool:
        # Multiple <article> elements → listing
        if len(soup.find_all("article")) >= 3:
            return True
        # URL pattern matching for index pages
        clean = url.rstrip("/").split("?")[0]
        if re.search(
            r"/(blog|foundry|search|gadgets|news|category|tag|feed|latest)(/[^/]+)?$",
            clean,
            re.I,
        ):
            return True
        # Multiple linked headings → listing
        linked_h = sum(bool(h.find("a")) for h in soup.find_all(["h2", "h3"]))
        return linked_h >= 5

    # ------------------------------------------------------------------
    # Listing-page parser
    # ------------------------------------------------------------------

    def _parse_listing(self, soup: BeautifulSoup, base_url: str) -> List[NewsItem]:
        items: List[NewsItem] = []

        # Strategy 1 – semantic <article> tags
        for article in soup.find_all("article")[:18]:
            item = self._item_from_element(article, base_url)
            if item:
                items.append(item)
        if items:
            return items[:15]

        # Strategy 2 – heading-based cards
        for heading in soup.find_all(["h2", "h3"])[:30]:
            a_tag = heading.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            title = heading.get_text(strip=True)
            if len(title) < 10 or title.lower() in _IGNORE_HEADINGS:
                continue
            href = a_tag["href"]
            if not href.startswith("http"):
                href = urljoin(base_url, href)

            # Look for an excerpt and date near the heading
            container = heading.find_parent(["div", "li", "section"]) or heading.parent
            excerpt = ""
            date = ""
            if container:
                for p in container.find_all("p"):
                    t = p.get_text(strip=True)
                    if len(t) > 40:
                        excerpt = t[:280]
                        break
                date = _extract_date_from_el(container)

            items.append(NewsItem(title=title, url=href, excerpt=excerpt, date=date))

        return items[:15]

    def _item_from_element(
        self, el: BeautifulSoup, base_url: str
    ) -> Optional[NewsItem]:
        heading = el.find(["h1", "h2", "h3", "h4"])
        if not heading:
            return None
        title = heading.get_text(strip=True)
        if not title or len(title) < 5:
            return None

        # URL
        a_tag = heading.find("a") or el.find("a")
        url = base_url
        if a_tag and a_tag.get("href"):
            href = a_tag["href"]
            url = href if href.startswith("http") else urljoin(base_url, href)

        # Excerpt
        excerpt = ""
        for p in el.find_all("p"):
            t = p.get_text(strip=True)
            if len(t) > 30:
                excerpt = t[:300]
                break

        # Date
        date = _extract_date_from_el(el)

        # Author — class-based then aria-label fallback
        author = ""
        for pat in [r"author", r"byline", r"post-author", r"post-bio"]:
            author_el = el.find(class_=re.compile(pat, re.I))
            if author_el:
                # Prefer a nested link (e.g. <a href="/author/name">Name</a>)
                a_el = author_el.find("a", href=re.compile(r"/author/", re.I))
                if a_el:
                    author = a_el.get_text(strip=True)[:80]
                else:
                    raw_auth = author_el.get_text(" ", strip=True)
                    # Strip leading date + "by" from strings like "March 26, 2026 by Name"
                    raw_auth = re.sub(r'^.*?\bby\b\s*', '', raw_auth, flags=re.I).strip()
                    # Remove trailing view counts e.g. "955 Views"
                    raw_auth = re.sub(r'\s*\d+\s*views?\s*$', '', raw_auth, flags=re.I).strip()
                    if raw_auth:
                        author = raw_auth[:80]
                if author:
                    break
        if not author:
            a_el = el.find("a", attrs={"aria-label": re.compile(r"post by", re.I)})
            if a_el:
                author = re.sub(r'^post by\s*', '', a_el.get("aria-label", ""), flags=re.I).strip()[:80]

        return NewsItem(title=title, url=url, excerpt=excerpt, date=date, author=author)

    # ------------------------------------------------------------------
    # Single-article parser
    # ------------------------------------------------------------------

    def _parse_article(
        self, soup: BeautifulSoup, url: str, html: str
    ) -> List[NewsItem]:
        # Title
        title = ""
        for tag in ["h1", "title"]:
            el = soup.find(tag)
            if el:
                title = el.get_text(strip=True)
                if title:
                    break

        # Date
        date = ""
        for tag, attrs in [
            ("meta", {"property": "article:published_time"}),
            ("meta", {"name": "date"}),
            ("meta", {"name": "publish_date"}),
            ("time", {}),
        ]:
            el = soup.find(tag, attrs or {})
            if el:
                raw = (
                    el.get("content", "")
                    or el.get("datetime", "")
                    or el.get_text(strip=True)
                )
                if raw:
                    # Trim ISO datetime to date only
                    date = raw[:10] if "T" in raw else raw[:40]
                    break

        # Author
        author = ""
        for pat in [r"author", r"byline"]:
            el = soup.find(class_=re.compile(pat, re.I))
            if el:
                author = el.get_text(strip=True)[:80]
                break
        if not author:
            el = soup.find(rel="author")
            if el:
                author = el.get_text(strip=True)[:80]

        # Key section headings (clean, meaningful ones)
        key_points: List[str] = []
        for h in soup.find_all(["h2", "h3"]):
            text = h.get_text(strip=True)
            if text and len(text) > 8 and text.lower() not in _IGNORE_HEADINGS:
                key_points.append(text)
            if len(key_points) >= 8:
                break

        # Excerpt: first substantial paragraphs, up to ~600 chars
        try:
            import trafilatura  # optional dependency

            clean_text = trafilatura.extract(
                html, include_comments=False, include_tables=False, no_fallback=False
            )
            if clean_text and len(clean_text) > 100:
                excerpt = clean_text[:600].rstrip() + ("…" if len(clean_text) > 600 else "")
            else:
                raise ValueError("trafilatura returned empty")
        except Exception:
            # Fallback: concatenate leading paragraphs
            parts: List[str] = []
            budget = 600
            for p in soup.find_all("p"):
                t = p.get_text(strip=True)
                if len(t) > 60:
                    parts.append(t)
                    budget -= len(t)
                    if budget <= 0:
                        break
            excerpt = " ".join(parts)
            if len(excerpt) > 600:
                excerpt = excerpt[:597] + "…"

        return [
            NewsItem(
                title=title,
                url=url,
                excerpt=excerpt,
                date=date,
                author=author,
                key_points=key_points,
            )
        ]



# ---------------------------------------------------------------------------
# Agent registry — loaded from agents_config.json["builtin_agents"]
# ---------------------------------------------------------------------------

def _load_builtin_agents() -> List[NewsAgent]:
    """Build NewsAgent objects from the ``builtin_agents`` list in config."""
    raw = _load_raw_config().get("builtin_agents", [])
    agents = []
    for entry in raw:
        urls = entry.get("urls") or entry.get("url") or ""
        agents.append(NewsAgent(
            name=entry["name"],
            url=urls,
            category=entry.get("category", ""),
            description=entry.get("description", ""),
            icon=entry.get("icon", "📰"),
            color=entry.get("color", "#0078D4"),
        ))
    return agents


# Module-level list — loaded from JSON at import time.
# The Admin page uses this as the canonical built-in reference.
# Changes to builtin_agents in config take effect on next server start.
AGENTS: List[NewsAgent] = _load_builtin_agents()
CATEGORIES: List[str] = sorted({a.category for a in AGENTS})


def get_active_agents() -> List[NewsAgent]:
    """Return the full list of agents (built-in + custom) excluding disabled ones.

    Built-in agents are sourced fresh from JSON so overrides always apply.
    Custom agents live in ``custom_agents``.
    """
    config = _load_raw_config()
    disabled: set = set(config.get("disabled_agents", []))
    overrides: dict = config.get("overrides", {})

    active: List[NewsAgent] = []
    for a in _load_builtin_agents():
        if a.name in disabled:
            continue
        ov = overrides.get(a.name)
        if ov:
            urls = ov.get("urls") or a.urls
            active.append(NewsAgent(
                name=a.name,
                url=urls,
                category=ov.get("category", a.category),
                description=ov.get("description", a.description),
                icon=ov.get("icon", a.icon),
                color=ov.get("color", a.color),
            ))
        else:
            active.append(a)

    for ca in config.get("custom_agents", []):
        if not ca.get("enabled", True):
            continue
        urls = ca.get("urls") or ca.get("url") or ""
        active.append(NewsAgent(
            name=ca["name"],
            url=urls,
            category=ca.get("category", "Custom"),
            description=ca.get("description", ""),
            icon=ca.get("icon", "📰"),
            color=ca.get("color", "#0078D4"),
        ))

    return active


def get_active_categories() -> List[str]:
    """Sorted unique categories derived from all active agents."""
    return sorted({a.category for a in get_active_agents()})
