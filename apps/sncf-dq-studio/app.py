"""SNCF DQ Studio : pilotage de la qualite des donnees (chaine DQ v3, cadre DAMA-DMBOK)."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SNCF DQ Studio", layout="wide")

from ui import state  # noqa: E402

try:
    ident = state.current_user()
except state.UserAuthMissing as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"Initialisation impossible : {e}")
    st.stop()

st.sidebar.markdown("### SNCF DQ Studio")
st.sidebar.caption("SNCF Reseau - Qualite des donnees")
source = state.select_source_sidebar()
if source:
    st.sidebar.caption(f"Schemas produits : {source['dq_prefix']}_*")
roles = state.user_roles()
st.sidebar.divider()
st.sidebar.caption(f"Connecte : {ident.email}")
st.sidebar.caption("Profil : " + ", ".join(roles.labels()))

pages = {
    "Pilotage": [
        st.Page("views/accueil.py", title="Accueil", default=True),
        st.Page("views/suivi.py", title="Suivi des executions"),
    ],
    "Actions": [
        st.Page("views/lancer.py", title="Lancer un controle"),
    ],
    "Analyse": [
        st.Page("views/agent.py", title="Analyste IA"),
    ],
}
st.navigation(pages).run()
