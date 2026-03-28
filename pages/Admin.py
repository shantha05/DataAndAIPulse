"""
Admin.py — InsightsAgent Admin Page

Two-column layout: agent list on the left, always-visible form on the right.
Clicking Edit updates the right-hand form in the SAME Streamlit run (no rerun,
no scroll) because right_col executes after left_col in the script.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents import AGENTS, _load_raw_config, get_active_agents, save_config

st.set_page_config(
    page_title="Admin — InsightsAgent",
    page_icon="⚙️",
    layout="wide",
)

st.html("""<style>
/* ── Global font scale ───────────────────────────────────────────── */
section[data-testid="stMain"] p,
section[data-testid="stMain"] div,
section[data-testid="stMain"] label,
section[data-testid="stMain"] span,
section[data-testid="stMain"] li {
    font-size: 1rem !important;
}
section[data-testid="stMain"] h1 { font-size: 2rem    !important; }
section[data-testid="stMain"] h2 { font-size: 1.55rem !important; }
section[data-testid="stMain"] h3 { font-size: 1.25rem !important; }

/* ── Agent info block ────────────────────────────────────────────── */
.ag-row {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 4px 2px;
}
.ag-icon {
    font-size: 2rem;
    line-height: 1.1;
    min-width: 2.5rem;
    text-align: center;
    flex-shrink: 0;
}
.ag-body  { flex: 1; min-width: 0; }
.ag-name  {
    font-size: 1.05rem; font-weight: 700; color: #111;
    display: flex; align-items: center; flex-wrap: wrap;
    gap: 7px; margin-bottom: 4px; line-height: 1.3;
}
.ag-cat {
    font-size: 0.8rem; font-weight: 700;
    background: #ede8f8; color: #5C2D91;
    border-radius: 8px; padding: 2px 10px;
}
.ag-ov {
    font-size: 0.75rem; font-weight: 700;
    background: #fff3cd; color: #856404;
    border-radius: 8px; padding: 2px 8px;
}
.ag-desc {
    font-size: 0.88rem; color: #666;
    margin-bottom: 5px; line-height: 1.45;
}
.ag-urls { font-size: 0.82rem; color: #888; line-height: 1.7; word-break: break-all; }
.ag-urls a { color: #0055a5; text-decoration: none; }
.ag-urls a:hover { text-decoration: underline; }

/* ── Form panel banner ───────────────────────────────────────────── */
.fp-banner {
    background: #f0f2ff;
    border-left: 5px solid #5C2D91;
    border-radius: 8px;
    padding: 12px 16px 8px;
    margin-bottom: 14px;
}
.fp-title   { font-size: 1.15rem !important; font-weight: 800; color: #1a1a2e; }
.fp-sub     { font-size: 0.88rem !important; color: #666; margin-top: 3px; }
</style>""")


# ── Session state ─────────────────────────────────────────────────────────────
for _k, _v in [
    ("adm_mode",       "new"),   # "new" | "builtin" | "custom"
    ("adm_builtin",    None),    # str — agent name for built-in edit
    ("adm_custom_idx", None),    # int — index for custom-agent edit
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Helpers ───────────────────────────────────────────────────────────────────
def _cfg() -> dict:
    return _load_raw_config()


# ── Logo in sidebar ─────────────────────────────────────────────────────────
_logo_url = _cfg().get("app", {}).get("logo_url", "")
if _logo_url:
    st.sidebar.markdown(
        f'<div style="background:white;border-radius:8px;padding:8px 12px;'
        f'margin-bottom:6px;text-align:center;">'
        f'<img src="{_logo_url}" style="max-width:190px;width:100%;height:auto;" />'
        f'</div>',
        unsafe_allow_html=True,
    )
st.sidebar.markdown("#### ⚙️ Agent Admin")
st.sidebar.caption("Manage the agent fleet")


def _save(c: dict) -> None:
    save_config(c)
    st.cache_data.clear()


def _info_html(icon: str, name: str, cat: str, desc: str,
               urls: list, overridden: bool = False) -> str:
    url_html = (
        "".join(f'<a href="{u}" target="_blank">{u}</a><br>' for u in urls)
        or "<span style='color:#ccc'>—</span>"
    )
    desc_html = f'<div class="ag-desc">{desc}</div>' if desc else ""
    ov_badge  = '<span class="ag-ov">★ overridden</span>' if overridden else ""
    return (
        f'<div class="ag-row">'
        f'  <div class="ag-icon">{icon}</div>'
        f'  <div class="ag-body">'
        f'    <div class="ag-name">{name}'
        f'      <span class="ag-cat">{cat}</span>{ov_badge}'
        f'    </div>'
        f'    {desc_html}'
        f'    <div class="ag-urls">{url_html}</div>'
        f'  </div>'
        f'</div>'
    )


# ── Page header ───────────────────────────────────────────────────────────────
st.title("⚙️ InsightsAgent Admin")
st.caption(
    "Manage your news sources without editing code. "
    "Changes appear on the main dashboard immediately after saving."
)
st.divider()

cfg           = _cfg()
disabled      = set(cfg.get("disabled_agents", []))
overrides     = dict(cfg.get("overrides", {}))
custom_agents = list(cfg.get("custom_agents", []))


# ══════════════════════════════════════════════════════════════════════════════
#  Two-column layout
#  left_col  — agent list with Edit buttons  (set session state, NO st.rerun())
#  right_col — form panel                    (reads updated session state in
#                                             the SAME script run)
# ══════════════════════════════════════════════════════════════════════════════
left_col, right_col = st.columns([1.8, 1.0], gap="large")


# ─────────────────────────────────────────────────────────────────────────────
# LEFT — Built-in agents
# ─────────────────────────────────────────────────────────────────────────────
with left_col:

    st.subheader(f"🔧 Built-in Agents  ({len(AGENTS)})")
    st.caption(
        "Toggle to show/hide on the dashboard. "
        "Click ✏️ Edit to customise URLs, icon, color, or description "
        "without touching the code."
    )

    disable_changed = False

    for agent in AGENTS:
        ov     = overrides.get(agent.name, {})
        d_icon = ov.get("icon",        agent.icon)
        d_cat  = ov.get("category",    agent.category)
        d_desc = ov.get("description", agent.description)
        d_urls = ov.get("urls",        agent.urls)

        with st.container(border=True):
            c_info, c_edit, c_tog = st.columns([8.5, 1.3, 1.1])

            with c_info:
                st.html(_info_html(d_icon, agent.name, d_cat, d_desc, d_urls,
                                   overridden=bool(ov)))

            with c_edit:
                # ↓  No st.rerun() — right_col reads updated session state
                #    in the same script execution (runs after left_col).
                if st.button("✏️ Edit", key=f"bi_edit_{agent.name}",
                             use_container_width=True):
                    st.session_state.adm_mode       = "builtin"
                    st.session_state.adm_builtin     = agent.name
                    st.session_state.adm_custom_idx  = None

            with c_tog:
                on = agent.name not in disabled
                nv = st.toggle("on", value=on,
                               key=f"bi_tog_{agent.name}",
                               label_visibility="collapsed")
                if nv != on:
                    disabled.discard(agent.name) if nv else disabled.add(agent.name)
                    disable_changed = True

    if disable_changed:
        cfg["disabled_agents"] = sorted(disabled)
        _save(cfg)
        st.rerun()   # needed to refresh the toggle state + agent list

    # ── Custom agents ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader(f"✨ Custom Agents  ({len(custom_agents)})")

    if not custom_agents:
        st.info("No custom agents yet — use the form on the right to add one.")
    else:
        to_delete: int | None = None

        for idx, ca in enumerate(custom_agents):
            with st.container(border=True):
                c_info, c_tog, c_edit, c_del = st.columns([7.5, 1.0, 1.2, 1.0])

                with c_info:
                    st.html(_info_html(
                        ca.get("icon", "📰"), ca["name"],
                        ca.get("category", "Custom"),
                        ca.get("description", ""),
                        ca.get("urls", []),
                    ))

                with c_tog:
                    en = ca.get("enabled", True)
                    nv = st.toggle("on", value=en,
                                   key=f"cu_tog_{idx}",
                                   label_visibility="collapsed")
                    if nv != en:
                        custom_agents[idx]["enabled"] = nv
                        cfg["custom_agents"] = custom_agents
                        _save(cfg)
                        st.rerun()

                with c_edit:
                    # ↓  No st.rerun() — form in right_col updates in same run
                    if st.button("✏️ Edit", key=f"cu_edit_{idx}",
                                 use_container_width=True):
                        st.session_state.adm_mode       = "custom"
                        st.session_state.adm_custom_idx  = idx
                        st.session_state.adm_builtin     = None

                with c_del:
                    if st.button("🗑️", key=f"cu_del_{idx}",
                                 use_container_width=True):
                        to_delete = idx

        if to_delete is not None:
            cfg["custom_agents"] = [
                c for i, c in enumerate(custom_agents) if i != to_delete
            ]
            _save(cfg)
            if st.session_state.adm_custom_idx == to_delete:
                st.session_state.adm_mode       = "new"
                st.session_state.adm_custom_idx  = None
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# RIGHT — Always-visible form panel
# Session state was potentially updated by an Edit button in left_col above,
# so reading it here reflects that change without a second rerun.
# ─────────────────────────────────────────────────────────────────────────────
with right_col:

    mode    = st.session_state.adm_mode
    bi_name = st.session_state.adm_builtin
    cu_idx  = st.session_state.adm_custom_idx

    editing_bi = (
        mode == "builtin"
        and bi_name is not None
        and any(a.name == bi_name for a in AGENTS)
    )
    editing_cu = (
        mode == "custom"
        and cu_idx is not None
        and 0 <= cu_idx < len(custom_agents)
    )

    # ── Resolve defaults ──────────────────────────────────────────────────────
    if editing_bi:
        base = next(a for a in AGENTS if a.name == bi_name)
        ex = {
            "name":        base.name,
            "category":    base.category,
            "icon":        base.icon,
            "color":       base.color,
            "description": base.description,
            "urls":        list(base.urls),
        }
        ex.update(overrides.get(bi_name, {}))
        banner_title = "✏️ Editing built-in agent"
        banner_sub   = bi_name
    elif editing_cu:
        ex           = dict(custom_agents[cu_idx])
        banner_title = "✏️ Editing custom agent"
        banner_sub   = ex.get("name", "")
    else:
        ex           = {}
        banner_title = "➕ Add New Agent"
        banner_sub   = "Fill in the details and click Add Agent"

    # ── Banner ────────────────────────────────────────────────────────────────
    st.html(
        f'<div class="fp-banner">'
        f'<div class="fp-title">{banner_title}</div>'
        f'<div class="fp-sub">{banner_sub}</div>'
        f'</div>'
    )

    # ── Cancel / Reset controls ───────────────────────────────────────────────
    if editing_bi or editing_cu:
        b1, b2 = st.columns(2)
        with b1:
            if st.button("✕ Cancel", key="adm_cancel",
                         type="secondary", use_container_width=True):
                st.session_state.adm_mode       = "new"
                st.session_state.adm_builtin     = None
                st.session_state.adm_custom_idx  = None
                st.rerun()
        if editing_bi and bi_name in overrides:
            with b2:
                if st.button("↩ Reset defaults", key="adm_reset",
                             use_container_width=True,
                             help="Remove customisation and restore code defaults"):
                    c2 = _cfg()
                    c2.get("overrides", {}).pop(bi_name, None)
                    _save(c2)
                    st.session_state.adm_mode    = "new"
                    st.session_state.adm_builtin  = None
                    st.success(f"✅ {bi_name} reset to defaults.")
                    st.rerun()

    # ── Form — dynamic key forces field reset when switching edit target ───────
    form_key = f"adm_form__{mode}__{bi_name}__{cu_idx}"

    with st.form(form_key, clear_on_submit=(mode == "new")):

        name = st.text_input(
            "Agent Name *",
            value=ex.get("name", ""),
            placeholder="e.g. My Blog Feed",
            disabled=editing_bi,          # built-in names are fixed
        )
        category = st.text_input(
            "Category *",
            value=ex.get("category", ""),
            placeholder="e.g. AI, Database, News",
        )
        description = st.text_input(
            "Description",
            value=ex.get("description", ""),
            placeholder="Short description of this feed",
        )

        ic_col, co_col = st.columns(2)
        with ic_col:
            icon = st.text_input(
                "Icon (emoji)",
                value=ex.get("icon", "📰"),
                max_chars=4,
                help="Paste a single emoji, e.g. 🤖 🗞️",
            )
        with co_col:
            color = st.color_picker(
                "Accent color",
                value=ex.get("color", "#0078D4"),
            )

        urls_text = st.text_area(
            "URLs *  (one per line)",
            value="\n".join(ex.get("urls", [])),
            height=130,
            placeholder="https://example.com/blog\nhttps://example.com/blog/ai",
            help="Multiple URLs are fetched in parallel and deduplicated.",
        )

        btn_label = (
            "💾 Save Changes" if (editing_bi or editing_cu) else "➕ Add Agent"
        )
        submitted = st.form_submit_button(
            btn_label, type="primary", use_container_width=True
        )

    # ── Process submission (outside the form block) ───────────────────────────
    if submitted:
        urls   = [u.strip() for u in urls_text.splitlines() if u.strip()]
        errors: list[str] = []

        if not editing_bi and not name.strip():
            errors.append("Agent Name is required.")
        if not category.strip():
            errors.append("Category is required.")
        if not urls:
            errors.append("At least one URL is required.")
        if mode == "new" and not errors:
            taken = {a.name for a in AGENTS} | {c["name"] for c in custom_agents}
            if name.strip() in taken:
                errors.append(
                    f"An agent named '{name.strip()}' already exists. "
                    "Use ✏️ Edit on the existing entry."
                )

        if errors:
            for err in errors:
                st.error(err)
        else:
            c2 = _cfg()

            if editing_bi:
                c2.setdefault("overrides", {})[bi_name] = {
                    "category":    category.strip(),
                    "icon":        icon.strip() or ex.get("icon", "📰"),
                    "color":       color,
                    "description": description.strip(),
                    "urls":        urls,
                }
                _save(c2)
                st.success(f"✅ {bi_name} saved.")
                st.session_state.adm_mode    = "new"
                st.session_state.adm_builtin  = None

            elif editing_cu:
                cl = list(c2.get("custom_agents", []))
                cl[cu_idx] = {
                    "name":        name.strip(),
                    "category":    category.strip(),
                    "icon":        icon.strip() or "📰",
                    "color":       color,
                    "description": description.strip(),
                    "urls":        urls,
                    "enabled":     custom_agents[cu_idx].get("enabled", True),
                }
                c2["custom_agents"] = cl
                _save(c2)
                st.success(f"✅ {name.strip()} updated.")
                st.session_state.adm_mode       = "new"
                st.session_state.adm_custom_idx  = None

            else:
                cl = list(c2.get("custom_agents", []))
                cl.append({
                    "name":        name.strip(),
                    "category":    category.strip(),
                    "icon":        icon.strip() or "📰",
                    "color":       color,
                    "description": description.strip(),
                    "urls":        urls,
                    "enabled":     True,
                })
                c2["custom_agents"] = cl
                _save(c2)
                st.success(f"✅ {name.strip()} added.")

            st.rerun()


# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
active = get_active_agents()
st.caption(
    f"{len(active)} active agent{'s' if len(active) != 1 else ''}  ·  "
    f"{len(AGENTS)} built-in  ·  {len(custom_agents)} custom  ·  "
    f"{len(disabled)} disabled  ·  {len(overrides)} overridden  ·  "
    "Navigate to **Main** in the sidebar to see your changes."
)
