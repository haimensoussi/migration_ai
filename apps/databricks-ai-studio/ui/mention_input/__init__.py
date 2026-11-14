"""Champ de saisie avec liste d'agents à la frappe de @ et complétion par Tab (composant Streamlit statique)."""
from __future__ import annotations

import os
from pathlib import Path

FRONTEND = Path(__file__).parent / "frontend"
COMPONENT_NAME = "discovery_mention_input"
_component = None


def enabled() -> bool:
    """Réglage de secours : AI_STUDIO_MENTION_INPUT=0 revient à la saisie Streamlit standard."""
    return os.environ.get("AI_STUDIO_MENTION_INPUT", "1").strip().lower() not in ("0", "false", "off", "non")


def _get_component():
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component(COMPONENT_NAME, path=str(FRONTEND))
    return _component


def agents_payload(agents: list[dict]) -> list[dict]:
    """Seules les informations utiles à l'affichage sont transmises au navigateur."""
    return [{"name": a["name"], "category": a.get("category") or ""} for a in agents if a.get("name")]


def accept(value, key: str) -> str | None:
    """Un même envoi (même id) n'est traité qu'une fois, même si la page est rejouée."""
    import streamlit as st          # import tardif : module testable sans Streamlit réel
    if not isinstance(value, dict) or not str(value.get("text", "")).strip():
        return None
    seen = f"_mention_seen_{key}"
    if st.session_state.get(seen) == value.get("id"):
        return None
    st.session_state[seen] = value.get("id")
    return str(value["text"]).strip()


def mention_input(agents: list[dict], key: str, placeholder: str, disabled: bool = False) -> str | None:
    value = _get_component()(agents=agents_payload(agents), placeholder=placeholder, disabled=disabled,
                             key=f"mi_{key}", default=None)
    return accept(value, key)


STICKY_CSS = f"""<style>
div[data-testid="stElementContainer"]:has(iframe[title*="{COMPONENT_NAME}"]),
div.element-container:has(iframe[title*="{COMPONENT_NAME}"]) {{
  position: sticky; bottom: 0; z-index: 20; background: #F6F6F8; padding-top: 6px;
}}
</style>"""
