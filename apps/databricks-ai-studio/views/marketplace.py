import streamlit as st

from backend.agent_contracts import DOMAINES
from ui import state
from ui.agent_sheet import open_sheet
from ui.avatars import agent_avatar_uri
from ui.catalog_cards import CARD_CSS, agent_footer, card_html

PER_ROW = 4

st.title("Marketplace")
st.caption("Agents publiés, regroupés par domaine. Chaque publication est validée par le responsable du domaine.")
NO_DOMAIN = "Domaine non renseigné"
try:
    _ctr = state.contracts()
except Exception:  # noqa: BLE001 - fiches indisponibles : un seul groupe
    _ctr = {}


def dom_of(a: dict) -> str:
    return (_ctr.get(a["agent_id"]) or {}).get("domaine") or NO_DOMAIN


flt = st.session_state.pop("marketplace_filter", {}) or {}
published = [a for a in state.agents() if a["status"] == "publie"]
cats = ["Toutes"] + sorted({a.get("category") or "Général" for a in published} | ({flt["category"]} if flt.get("category") else set()))
doms = ["Tous"] + [d for d in DOMAINES + [NO_DOMAIN] if any(dom_of(a) == d for a in published)]
f1, f2, f3 = st.columns([3, 2, 2])
q = f1.text_input("Rechercher", value=flt.get("query", "")).lower().strip()
dom = f2.selectbox("Domaine", doms)
cat = f3.selectbox("Catégorie", cats, index=cats.index(flt["category"]) if flt.get("category") in cats else 0)
items = [a for a in published if (cat == "Toutes" or (a.get("category") or "Général") == cat)
         and (dom == "Tous" or dom_of(a) == dom)
         and (not q or q in f"{a['name']} {a.get('description')} {a.get('category')} {dom_of(a)}".lower())]
st.markdown(CARD_CSS, unsafe_allow_html=True)
tool_cats = {t.tool_id: t.category for t in state.cached_tools()}
st.caption(f"{len(items)} agent(s)")
groups = [(d, [a for a in items if dom_of(a) == d]) for d in DOMAINES + [NO_DOMAIN]]
rows = []
for d, group in groups:
    if group:
        rows.append((d, None))
        rows += [(d, group[i:i + PER_ROW]) for i in range(0, len(group), PER_ROW)]
for d, chunk in rows:
    if chunk is None:
        st.subheader(f"{d} · {sum(1 for a in items if dom_of(a) == d)}")
        continue
    cols = st.columns(PER_ROW)
    for col, a in zip(cols, chunk):
        with col:
            st.markdown(card_html(a["name"], a.get("description") or a.get("tagline") or "", a.get("category"),
                                  agent_footer(a.get("tool_ids"), tool_cats), avatar=agent_avatar_uri(a)),
                        unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            if b1.button("Utiliser", key=f"m_{a['agent_id']}", use_container_width=True):
                st.session_state["chat_agent_id"] = a["agent_id"]
                st.switch_page("views/chat.py")
            if b2.button("Fiche", key=f"f_{a['agent_id']}", use_container_width=True):
                open_sheet(a)
if not items:
    st.info("Aucun agent publié ne correspond à ce filtre.")
