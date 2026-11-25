"""Pages EIA (Missions, Notifications) : contexte utilisateur et confirmation explicite des décisions."""
from __future__ import annotations

from typing import Callable

import streamlit as st

from backend import config as app_config
from backend.eia import store as es
from backend.eia import team_config as tc
from ui import state

_PENDING, _MSG, _ERR = "_eia_pending", "_eia_msg", "_eia_err"


def context():
    """(config d'équipe, dépôt EIA, client SQL, e-mail) sous l'identité de l'utilisateur connecté."""
    try:
        _, sql, ident = state.user_session()
    except Exception as e:  # noqa: BLE001
        st.error(f"Identité utilisateur indisponible : {e}")
        st.stop()
    from backend.eia import team_builder as tb
    repo = es.EiaRepository(es.SqlEiaStore(sql, state.settings().table))
    teams = tb.teams(repo)        # versionnées + mises en service par le Team Builder
    if not teams:
        st.info("Aucune équipe EIA configurée.")
        st.stop()
    team_id = st.selectbox("Équipe", teams, key="eia_team") if len(teams) > 1 else teams[0]
    try:
        cfg = tb.resolve(team_id, repo, app_config.data_scope())
    except tc.TeamConfigError as e:
        st.error(f"Configuration d'équipe invalide : {e}")
        st.stop()
    return cfg, repo, sql, ident.email


def flash() -> None:
    if st.session_state.get(_MSG):
        st.success(st.session_state.pop(_MSG))
    if st.session_state.get(_ERR):
        st.error(st.session_state.pop(_ERR))


def confirm_button(label: str, key: str, action: Callable[[], str], *, disabled: bool = False, help: str | None = None,
                   primary: bool = False, container=None) -> None:
    """Bouton en deux temps : la décision n'est écrite qu'après le clic sur « Confirmer »."""
    box = container or st
    if st.session_state.get(_PENDING) == key:
        box.warning(f"Confirmer : {label} ? La décision sera enregistrée à votre nom.")
        # Boutons empilés : pas de colonnes ici, le bouton peut déjà être dans des colonnes imbriquées.
        if box.button("Confirmer", key=f"{key}__ok", type="primary", use_container_width=True):
            st.session_state.pop(_PENDING, None)
            try:
                with st.spinner("Enregistrement…"):
                    st.session_state[_MSG] = action()
            except Exception as e:  # noqa: BLE001 - refus du contrat ou de Unity Catalog affiché tel quel
                st.session_state[_ERR] = str(e)
            st.rerun()
        if box.button("Abandonner", key=f"{key}__no", use_container_width=True):
            st.session_state.pop(_PENDING, None)
            st.rerun()
    elif box.button(label, key=key, disabled=disabled, help=help, type="primary" if primary else "secondary",
                    use_container_width=True):
        st.session_state[_PENDING] = key
        st.rerun()


def ts(v) -> str:
    return str(v or "")[:16].replace("T", " ") or "—"
