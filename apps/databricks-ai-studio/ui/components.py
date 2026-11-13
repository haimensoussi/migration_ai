from __future__ import annotations

import html

import streamlit as st

STATUS_LABELS = {"publie": "Publié", "brouillon": "Brouillon", "planifie": "Planifié",
                 "indisponible": "Indisponible", "archive": "Archivé"}


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def badge(status: str) -> str:
    return f'<span class="ais-badge ais-{esc(status)}">{esc(STATUS_LABELS.get(status, status))}</span>'


def kpi(col, label: str, value, help_text: str = ""):
    col.markdown(f'<div class="ais-card"><div class="ais-kpi-label">{esc(label)}</div>'
                 f'<div class="ais-kpi-value">{esc(value)}</div><div class="ais-muted">{esc(help_text)}</div></div>',
                 unsafe_allow_html=True)


def hero(title: str, subtitle: str):
    st.markdown(f'<div class="ais-hero"><h2>{esc(title)}</h2><div>{esc(subtitle)}</div></div>', unsafe_allow_html=True)


ICONS = ["smart_toy", "verified", "terminal", "savings", "description", "policy", "query_stats", "support_agent"]


def agent_card(a: dict):
    """En-tête de carte (à placer dans un st.container(border=True))."""
    icon = a.get("icon") if a.get("icon") in ICONS else "smart_toy"
    st.markdown(f"#### :material/{icon}: {a['name']}")
    st.markdown(f'<div class="ais-muted">{esc(a.get("category") or "")} · v{esc(a.get("current_version"))} · '
                f'{esc(a.get("owner"))}</div>', unsafe_allow_html=True)
    st.write(a.get("description") or "")
    st.markdown(badge(a["status"]), unsafe_allow_html=True)


def error_box(prefix: str, exc: Exception):
    st.error(f"{prefix} : {exc}")
