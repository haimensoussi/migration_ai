"""En-tête commun DISCOVERY (présentation uniquement)."""
from __future__ import annotations

import streamlit as st

from ui import state
from ui.components import esc
from ui.theme import APP_NAME, APP_SUBTITLE


def _display_name() -> str:
    """Nom affiché de l'utilisateur (API current-user avec son jeton), à défaut son e-mail."""
    cached = st.session_state.get("_display_name")
    if cached:
        return cached
    name = ""
    try:
        w, _, ident = state.user_session()
        me = w.current_user.me()
        name = (me.display_name or "").strip() or ident.email
    except Exception:  # noqa: BLE001 - affichage uniquement
        name = state.current_user().email
    st.session_state["_display_name"] = name
    return name


def initials(name: str) -> str:
    base = name.split("@")[0].replace(".", " ").replace("_", " ").replace("(", " ").split()
    letters = [p[0] for p in base if p and p[0].isalpha()][:2]
    return ("".join(letters) or "?").upper()


def render_header():
    name = _display_name()
    st.markdown(
        f'<div class="dsc-top"><div><div class="dsc-top-title">{esc(APP_NAME)}</div>'
        f'<div class="dsc-top-sub">{esc(APP_SUBTITLE)}</div></div>'
        f'<div class="dsc-user"><div class="dsc-avatar">{esc(initials(name))}</div>{esc(name)}</div></div>',
        unsafe_allow_html=True)
