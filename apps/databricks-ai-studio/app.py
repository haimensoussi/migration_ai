"""Databricks AI Studio - point d'entrée Streamlit (Databricks Apps)."""
import streamlit as st

st.set_page_config(page_title="DISCOVERY — SNCF Réseau", page_icon=":material/smart_toy:", layout="wide")

from ui.theme import apply_theme  # noqa: E402

apply_theme()

pages = {
    "Studio": [
        st.Page("views/accueil.py", title="Accueil", icon=":material/home:", default=True),
        st.Page("views/mes_agents.py", title="Mes agents", icon=":material/smart_toy:"),
        st.Page("views/agent_builder.py", title="Agent Builder", icon=":material/construction:"),
        st.Page("views/chat.py", title="Chat & Test", icon=":material/forum:"),
        st.Page("views/tool_catalog.py", title="Tool Catalog", icon=":material/handyman:"),
    ],
    "Phase 2": [
        st.Page("views/knowledge_studio.py", title="Knowledge Studio", icon=":material/menu_book:"),
        st.Page("views/marketplace.py", title="Agent Marketplace", icon=":material/storefront:"),
        st.Page("views/assessment.py", title="Assessment Center", icon=":material/fact_check:"),
    ],
    "Pilotage": [
        st.Page("views/monitoring.py", title="Monitoring", icon=":material/monitoring:"),
        st.Page("views/parametres.py", title="Paramètres", icon=":material/settings:"),
    ],
}
st.navigation(pages).run()
