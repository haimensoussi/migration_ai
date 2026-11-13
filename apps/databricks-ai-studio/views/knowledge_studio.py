import streamlit as st

st.title("Knowledge Studio")
st.info("Phase 2. Dans le MVP, les connaissances d'un agent sont les tables Unity Catalog choisies à l'étape 5 "
        "de l'Agent Builder.")
st.markdown("""
Prévu :
- Documents PDF déposés dans un Volume Unity Catalog, découpés avec `ai_parse_document`.
- Index Databricks Vector Search (Delta Sync) et outil `search_documents`.
- Rattachement des Knowledge Assistants existants comme sources de connaissances.
- Contrôle des droits de l'utilisateur sur chaque ressource.
""")
