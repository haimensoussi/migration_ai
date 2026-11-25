"""Databricks AI Studio - point d'entrée Streamlit (Databricks Apps)."""
import streamlit as st

st.set_page_config(page_title="Discovery — SNCF Réseau", page_icon=":material/smart_toy:", layout="wide")

from ui.theme import apply_theme  # noqa: E402

from ui.layout import render_header  # noqa: E402

apply_theme()

pages = {
    "Plateforme": [
        st.Page("views/accueil.py", title="Accueil", icon=":material/home:", default=True),
        st.Page("views/hakim.py", title="HakimAI", icon=":material/assistant:"),
        st.Page("views/hakim_voix.py", title="HakimAI Voix", icon=":material/mic:"),
        st.Page("views/transformation.py", title="Transformation", icon=":material/route:"),
        st.Page("views/mes_agents.py", title="Mes agents", icon=":material/work:"),
        st.Page("views/equipes.py", title="Équipes", icon=":material/groups:"),
        st.Page("views/agent_mesh.py", title="Agent Mesh", icon=":material/hub:"),
        st.Page("views/agent_builder.py", title="Agent Builder", icon=":material/construction:"),
        st.Page("views/chat.py", title="Chat & Test", icon=":material/forum:"),
        st.Page("views/tool_catalog.py", title="Tool Builder", icon=":material/handyman:"),
        st.Page("views/flux.py", title="Flux Builder", icon=":material/account_tree:"),
        st.Page("views/marketplace.py", title="Marketplace", icon=":material/storefront:"),
        st.Page("views/validation.py", title="Validation", icon=":material/verified:"),
        st.Page("views/assessment.py", title="Assessment Center", icon=":material/fact_check:"),
        st.Page("views/monitoring.py", title="Monitoring", icon=":material/monitoring:"),
    ],
    "EIA Factory": [
        st.Page("views/agent_catalog.py", title="Catalogue d'agents", icon=":material/category:"),
        st.Page("views/team_builder.py", title="Team Builder", icon=":material/group_add:"),
    ],
    "Copilotage EIA": [
        st.Page("views/missions.py", title="Missions", icon=":material/task_alt:"),
        st.Page("views/notifications.py", title="Notifications", icon=":material/notifications:"),
    ],
    "Administration": [
        st.Page("views/parametres.py", title="Paramètres", icon=":material/settings:"),
    ],
}
pg = st.navigation(pages)
render_header()
pg.run()
