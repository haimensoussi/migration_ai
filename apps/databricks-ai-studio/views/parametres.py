import streamlit as st

from database.seed_data import seed_example_agents, seed_tools
from ui import state

st.title("Paramètres")
s = state.settings()
user = state.current_user()
st.markdown(f"""
| Paramètre | Valeur |
| --- | --- |
| Schéma de configuration | `{s.catalog}.{s.schema}` |
| SQL warehouse | `{s.warehouse_id or "non configuré"}` |
| Modèle par défaut | `{s.default_model}` |
| Lignes maximum (execute_sql) | {s.max_rows} |
| Timeout SQL | {s.sql_timeout_s} s |
| Utilisateur | {user.email} |
| Mode d'identité des outils | {user.mode} |
""")
if user.mode == "jeton absent":
    st.error("Le jeton utilisateur n'est pas transmis : les outils et les modèles sont bloqués. "
             "Activez l'autorisation utilisateur de l'App (scopes sql et serving.serving-endpoints).")

st.subheader("Initialisation")
c1, c2 = st.columns(2)
if c1.button("Synchroniser le catalogue d'outils", icon=":material/sync:"):
    try:
        n = seed_tools(state.repository())
        state.refresh_data()
        st.success(f"{n} outils synchronisés.")
    except Exception as e:  # noqa: BLE001
        st.error(str(e))
if c2.button("Créer les agents d'exemple", icon=":material/auto_awesome:"):
    try:
        ids = seed_example_agents(state.repository(), user.email, s.default_model)
        state.refresh_data()
        st.success(f"{len(ids)} agent(s) créé(s).")
    except Exception as e:  # noqa: BLE001
        st.error(str(e))
