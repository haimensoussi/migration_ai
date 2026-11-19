import streamlit as st

from ui import state
from ui.avatars import agent_avatar_uri
from ui.catalog_cards import CARD_CSS, agent_footer, card_html
from ui.components import badge

PER_ROW = 4

st.title("Mes agents")
user = state.current_user()

f1, f2, f3 = st.columns([3, 2, 1])
query = f1.text_input("Rechercher", placeholder="Nom, description, catégorie")
status = f2.selectbox("Statut", ["Tous", "publie", "brouillon"],
                      format_func=lambda s: {"Tous": "Tous", "publie": "Publié", "brouillon": "Brouillon"}[s])
if f3.button("Actualiser"):
    state.refresh_data()

try:
    items = state.agents()
except Exception as e:  # noqa: BLE001
    st.error(f"Lecture impossible : {e}")
    st.stop()

q = query.lower().strip()
items = [a for a in items if (status == "Tous" or a["status"] == status)
         and (not q or q.lstrip("@") in f"{a['name']} {a.get('handle')} {a.get('persona')} {a.get('tagline')} {a.get('description')} {a.get('category')} {' '.join(a.get('aliases') or [])}".lower())]
if not items:
    st.info("Aucun agent. Créez-en un avec l'Agent Builder.")

st.markdown(CARD_CSS, unsafe_allow_html=True)
tool_cats = {t.tool_id: t.category for t in state.cached_tools()}
st.caption(f"{len(items)} agent(s)")
for start in range(0, len(items), PER_ROW):
    cols = st.columns(PER_ROW)
    for col, a in zip(cols, items[start:start + PER_ROW]):
        with col:
            st.markdown(card_html(a["name"], a.get("description") or a.get("tagline") or "", a.get("category"),
                                  agent_footer(a.get("tool_ids"), tool_cats), badge(a["status"]),
                                  avatar=agent_avatar_uri(a)),
                        unsafe_allow_html=True)
            mine = a["owner"] == user.email
            b1, b2 = st.columns(2)
            if b1.button("Tester", key=f"t_{a['agent_id']}", use_container_width=True):
                st.session_state["chat_agent_id"] = a["agent_id"]
                st.switch_page("views/chat.py")
            with b2.popover("Actions", use_container_width=True):
                st.caption(f"v{a.get('current_version')} · {a.get('owner')} · modèle : {a.get('model_endpoint')} · "
                           f"outils : {len(a.get('tool_ids') or [])}")
                if not mine:
                    st.caption("Actions réservées au propriétaire de l'agent.")
                if st.button("Modifier", key=f"e_{a['agent_id']}", disabled=not mine, use_container_width=True):
                    st.session_state["builder_edit_id"] = a["agent_id"]
                    st.session_state.pop("builder", None)
                    st.switch_page("views/agent_builder.py")
                target = "brouillon" if a["status"] == "publie" else "publie"
                label = "Dépublier" if target == "brouillon" else "Publier"
                if st.button(label, key=f"p_{a['agent_id']}", disabled=not mine, use_container_width=True):
                    state.repository().set_status(a["agent_id"], target)
                    state.refresh_data()
                    st.rerun()
                if st.button(":material/auto_fix_high: Améliorer avec l'IA", key=f"ai_{a['agent_id']}",
                             disabled=not mine, use_container_width=True):
                    st.session_state["builder_edit_id"] = a["agent_id"]
                    st.session_state["builder_improve"] = True
                    st.session_state.pop("builder", None)
                    st.switch_page("views/agent_builder.py")
