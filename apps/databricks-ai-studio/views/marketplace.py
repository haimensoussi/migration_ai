import streamlit as st

from ui import state
from ui.components import agent_card

st.title("Marketplace")
st.caption("Agents publiés. Activation, catégories et partage avancés : phase 2.")
flt = st.session_state.pop("marketplace_filter", {}) or {}
published = [a for a in state.agents() if a["status"] == "publie"]
cats = ["Toutes"] + sorted({a.get("category") or "Général" for a in published} | ({flt["category"]} if flt.get("category") else set()))
f1, f2 = st.columns([3, 2])
q = f1.text_input("Rechercher", value=flt.get("query", "")).lower().strip()
cat = f2.selectbox("Catégorie", cats, index=cats.index(flt["category"]) if flt.get("category") in cats else 0)
items = [a for a in published if (cat == "Toutes" or (a.get("category") or "Général") == cat)
         and (not q or q in f"{a['name']} {a.get('description')} {a.get('category')}".lower())]
cols = st.columns(3)
for i, a in enumerate(items):
    with cols[i % 3].container(border=True):
        agent_card(a)
        if st.button("Utiliser", key=f"m_{a['agent_id']}"):
            st.session_state["chat_agent_id"] = a["agent_id"]
            st.switch_page("views/chat.py")
if not items:
    st.info("Aucun agent publié ne correspond à ce filtre.")
