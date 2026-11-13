import streamlit as st

from ui import state
from ui.components import agent_card

st.title("Agent Marketplace")
st.caption("Aperçu MVP : agents publiés. Activation, catégories et partage avancés : phase 2.")
q = st.text_input("Rechercher").lower().strip()
items = [a for a in state.agents() if a["status"] == "publie"
         and (not q or q in f"{a['name']} {a.get('description')} {a.get('category')}".lower())]
cols = st.columns(3)
for i, a in enumerate(items):
    with cols[i % 3].container(border=True):
        agent_card(a)
        if st.button("Utiliser", key=f"m_{a['agent_id']}", icon=":material/forum:"):
            st.session_state["chat_agent_id"] = a["agent_id"]
            st.switch_page("views/chat.py")
if not items:
    st.info("Aucun agent publié.")
