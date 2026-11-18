"""Databricks AI Studio - point d'entrée Streamlit (Databricks Apps)."""
import streamlit as st

st.set_page_config(page_title="Discovery — SNCF Réseau", page_icon=":material/smart_toy:", layout="wide")

from ui.theme import apply_theme  # noqa: E402

from ui.layout import render_header  # noqa: E402

apply_theme()

pages = {
    "SaaS": [
        st.Page("views/saas_accueil.py", title="Dashboard SaaS", icon=":material/space_dashboard:"),
        st.Page("views/organisations.py", title="Organisations", icon=":material/domain:"),
        st.Page("views/setup_wizard.py", title="Setup Wizard", icon=":material/checklist:"),
        st.Page("views/agent_studio.py", title="Agent Studio", icon=":material/smart_toy:"),
    ],
    "Plateforme": [
        st.Page("views/accueil.py", title="Accueil", icon=":material/home:", default=True),
        st.Page("views/hakim.py", title="HakimAI", icon=":material/assistant:"),
        st.Page("views/mes_agents.py", title="Mes agents", icon=":material/work:"),
        st.Page("views/equipes.py", title="Équipes", icon=":material/groups:"),
        st.Page("views/agent_builder.py", title="Agent Builder", icon=":material/construction:"),
        st.Page("views/chat.py", title="Chat & Test", icon=":material/forum:"),
        st.Page("views/tool_catalog.py", title="Catalogue d'outils", icon=":material/grid_view:"),
        st.Page("views/flux.py", title="Flux", icon=":material/account_tree:"),
        st.Page("views/marketplace.py", title="Marketplace", icon=":material/storefront:"),
        st.Page("views/assessment.py", title="Assessment Center", icon=":material/fact_check:"),
        st.Page("views/monitoring.py", title="Monitoring", icon=":material/monitoring:"),
    ],
    "Administration": [
        st.Page("views/parametres.py", title="Paramètres", icon=":material/settings:"),
    ],
}
pg = st.navigation(pages)
render_header()
pg.run()
