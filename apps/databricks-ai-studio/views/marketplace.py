import streamlit as st

from backend.agent_contracts import DOMAINES
from ui import state
from ui.agent_sheet import open_sheet
from ui.avatars import agent_avatar_uri
from ui.catalog_cards import CARD_CSS, agent_footer, card_html, tool_footer

PER_ROW = 4

st.title("Marketplace")
st.caption("Agents, outils et flux publiés, réutilisables par toutes les équipes. Chaque publication est validée.")
st.markdown(CARD_CSS, unsafe_allow_html=True)
_all_tools = state.cached_tools()
pub_tools = [t for t in _all_tools if t.status == "publie" and t.category != "Flux"]
pub_flows = [t for t in _all_tools if t.status == "publie" and t.category == "Flux"]
published = [a for a in state.agents() if a["status"] == "publie"]
tab_ag, tab_out, tab_flux = st.tabs([f"Agents ({len(published)})", f"Outils ({len(pub_tools)})",
                                     f"Flux ({len(pub_flows)})"])


def tool_grid(items, key: str, target: str, label: str):
    """Cartes des outils ou flux publiés, avec recherche ; le bouton ouvre la page de construction."""
    c1, c2 = st.columns([3, 2])
    q = c1.text_input("Rechercher", key=f"mk_q_{key}").lower().strip()
    cats = ["Toutes"] + sorted({t.category for t in items})
    cat = c2.selectbox("Catégorie", cats, key=f"mk_c_{key}")
    sel = [t for t in items if (cat == "Toutes" or t.category == cat)
           and (not q or q in f"{t.tool_id} {t.name} {t.description} {t.category}".lower())]
    st.caption(f"{len(sel)} élément(s)")
    for i in range(0, len(sel), PER_ROW):
        for col, t in zip(st.columns(PER_ROW), sel[i:i + PER_ROW]):
            with col:
                st.markdown(card_html(t.name, t.description, t.category,
                                      tool_footer(t.executor, t.read_only, t.requires_confirmation)),
                            unsafe_allow_html=True)
                if st.button(label, key=f"mk_{key}_{t.tool_id}", use_container_width=True):
                    st.switch_page(target)
    if not sel:
        st.info("Aucun élément publié ne correspond à ce filtre.")


with tab_out:
    st.caption("Les outils s'ajoutent à un agent dans Agent Builder ; ils se créent dans le Tool Builder.")
    tool_grid(pub_tools, "out", "views/tool_catalog.py", "Tool Builder")
with tab_flux:
    st.caption("Les flux s'ajoutent à un agent dans Agent Builder ; ils se créent dans le Flux Builder.")
    tool_grid(pub_flows, "flux", "views/flux.py", "Flux Builder")


NO_DOMAIN = "Domaine non renseigné"
try:
    _ctr = state.contracts()
except Exception:  # noqa: BLE001 - fiches indisponibles : un seul groupe
    _ctr = {}


def dom_of(a: dict) -> str:
    return (_ctr.get(a["agent_id"]) or {}).get("domaine") or NO_DOMAIN


def agents_tab():
    """Agents publiés, regroupés par domaine ; chaque publication est validée par le responsable du domaine."""
    flt = st.session_state.pop("marketplace_filter", {}) or {}
    cats = ["Toutes"] + sorted({a.get("category") or "Général" for a in published} | ({flt["category"]} if flt.get("category") else set()))
    doms = ["Tous"] + [d for d in DOMAINES + [NO_DOMAIN] if any(dom_of(a) == d for a in published)]
    f1, f2, f3 = st.columns([3, 2, 2])
    q = f1.text_input("Rechercher", value=flt.get("query", ""), key="mk_q_ag").lower().strip()
    dom = f2.selectbox("Domaine", doms, key="mk_d_ag")
    cat = f3.selectbox("Catégorie", cats, index=cats.index(flt["category"]) if flt.get("category") in cats else 0,
                       key="mk_c_ag")
    items = [a for a in published if (cat == "Toutes" or (a.get("category") or "Général") == cat)
             and (dom == "Tous" or dom_of(a) == dom)
             and (not q or q in f"{a['name']} {a.get('description')} {a.get('category')} {dom_of(a)}".lower())]
    tool_cats = {t.tool_id: t.category for t in _all_tools}
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


with tab_ag:
    agents_tab()
