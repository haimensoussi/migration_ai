import streamlit as st

from ui import state
from ui.components import agent_card

st.title("Mes agents")
user = state.current_user()

f1, f2, f3 = st.columns([3, 2, 1])
query = f1.text_input("Rechercher", placeholder="Nom, description, catégorie")
status = f2.selectbox("Statut", ["Tous", "publie", "brouillon"],
                      format_func=lambda s: {"Tous": "Tous", "publie": "Publié", "brouillon": "Brouillon"}[s])
if f3.button("Actualiser", icon=":material/refresh:"):
    state.refresh_data()

try:
    items = state.agents()
except Exception as e:  # noqa: BLE001
    st.error(f"Lecture impossible : {e}")
    st.stop()

q = query.lower().strip()
items = [a for a in items if (status == "Tous" or a["status"] == status)
         and (not q or q in f"{a['name']} {a.get('description')} {a.get('category')}".lower())]
if not items:
    st.info("Aucun agent. Créez-en un avec l'Agent Builder.")

cols = st.columns(3)
for i, a in enumerate(items):
    with cols[i % 3].container(border=True):
        agent_card(a)
        st.caption(f"Modèle : {a.get('model_endpoint')} · outils : {len(a.get('tool_ids') or [])}")
        b1, b2, b3 = st.columns(3)
        if b1.button("Tester", key=f"t_{a['agent_id']}", icon=":material/forum:"):
            st.session_state["chat_agent_id"] = a["agent_id"]
            st.switch_page("views/chat.py")
        mine = a["owner"] == user.email
        if b2.button("Modifier", key=f"e_{a['agent_id']}", icon=":material/edit:", disabled=not mine):
            st.session_state["builder_edit_id"] = a["agent_id"]
            st.session_state.pop("builder", None)
            st.switch_page("views/agent_builder.py")
        target = "brouillon" if a["status"] == "publie" else "publie"
        label = "Dépublier" if target == "brouillon" else "Publier"
        if b3.button(label, key=f"p_{a['agent_id']}", disabled=not mine):
            state.repository().set_status(a["agent_id"], target)
            state.refresh_data()
            st.rerun()
