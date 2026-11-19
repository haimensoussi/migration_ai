import streamlit as st

from ui import state
from ui.catalog_cards import CARD_CSS, agent_footer, card_html

PER_ROW = 4

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
st.markdown(CARD_CSS, unsafe_allow_html=True)
tool_cats = {t.tool_id: t.category for t in state.cached_tools()}
st.caption(f"{len(items)} agent(s)")
for start in range(0, len(items), PER_ROW):
    cols = st.columns(PER_ROW)
    for col, a in zip(cols, items[start:start + PER_ROW]):
        with col:
            st.markdown(card_html(a["name"], a.get("description") or a.get("tagline") or "", a.get("category"),
                                  agent_footer(a.get("tool_ids"), tool_cats)), unsafe_allow_html=True)
            if st.button("Utiliser", key=f"m_{a['agent_id']}", use_container_width=True):
                st.session_state["chat_agent_id"] = a["agent_id"]
                st.switch_page("views/chat.py")
if not items:
    st.info("Aucun agent publié ne correspond à ce filtre.")
