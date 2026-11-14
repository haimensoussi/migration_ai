"""Databricks AI Studio - point d'entrée Streamlit (Databricks Apps)."""
import streamlit as st

st.set_page_config(page_title="Discovery — SNCF Réseau", page_icon=":material/smart_toy:", layout="wide")

from ui.theme import apply_theme  # noqa: E402

from ui.layout import render_header  # noqa: E402

apply_theme()

pages = {
    "Plateforme": [
        st.Page("views/accueil.py", title="Accueil", icon=":material/home:", default=True),
        st.Page("views/mes_agents.py", title="Mes agents", icon=":material/work:"),
        st.Page("views/agent_builder.py", title="Agent Builder", icon=":material/construction:"),
        st.Page("views/chat.py", title="Chat & Test", icon=":material/forum:"),
        st.Page("views/tool_catalog.py", title="Catalogue d'outils", icon=":material/grid_view:"),
        st.Page("views/knowledge_studio.py", title="Knowledge Studio", icon=":material/menu_book:"),
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
