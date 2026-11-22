"""Affichage des schémas SmartArt (render_smartart des agents, creer_smartart de HakimAI) : Graphviz."""
import streamlit as st

from tools.smartart_tools import KIND_LABELS


def render(sa: dict | None, key: str = "", caption: str = "") -> None:
    if not sa or not sa.get("dot"):
        return
    if caption:
        st.caption(caption)
    kind = sa.get("forme") or sa.get("type")
    st.markdown(f"**{sa['titre']}**")
    st.graphviz_chart(sa["dot"], use_container_width=True)
    label = f"{sa.get('id') + ' · ' if sa.get('id') else ''}schéma {KIND_LABELS.get(kind, kind).lower()} · " \
            f"{len(sa['elements'])} éléments"
    with st.expander(label):
        for it in sa["elements"]:
            line = f"* **{it['texte']}**" + (f" — {it['detail']}" if it.get("detail") else "")
            st.markdown(line + (f" (sous {it['parent']})" if it.get("parent") else ""))
        for ln in sa.get("liens") or []:
            st.markdown(f"* {ln['de']} → {ln['vers']}" + (f" : {ln['libelle']}" if ln.get("libelle") else ""))
