import pandas as pd
import streamlit as st

from ui import state
from ui.components import esc, hero, kpi
from ui.theme import SIGNATURE

hero("DISCOVERY — SNCF Réseau", "Créez, testez et publiez des agents IA gouvernés par Unity Catalog.")
user = state.current_user()
st.caption(f"Connecté : {user.email} · mode d'identité : {user.mode}")

try:
    stats = state.repository().dashboard_stats()
    c = st.columns(5)
    kpi(c[0], "Agents", stats["agents"])
    kpi(c[1], "Publiés", stats["publies"])
    kpi(c[2], "En développement", stats["brouillons"])
    kpi(c[3], "Outils disponibles", stats["outils"])
    kpi(c[4], "Conversations", stats["conversations"])
except Exception as e:  # noqa: BLE001
    st.error(f"Impossible de lire les tables de configuration : {e}")
    st.stop()

st.write("")
a, b, c2, d = st.columns(4)
if a.button("Créer un agent", type="primary", use_container_width=True):
    st.session_state.pop("builder", None)
    st.switch_page("views/agent_builder.py")
b.page_link("views/mes_agents.py", label="Mes agents", icon=":material/smart_toy:")
c2.page_link("views/tool_catalog.py", label="Tool Catalog", icon=":material/handyman:")
d.page_link("views/monitoring.py", label="Monitoring", icon=":material/monitoring:")

st.subheader("Dernières exécutions d'outils")
rows = state.repository().recent_tool_calls(15)
if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("Aucune exécution pour l'instant. Testez un agent dans « Chat & Test ».")

st.markdown(f'<div class="ais-signature">{esc(SIGNATURE)}</div>', unsafe_allow_html=True)
