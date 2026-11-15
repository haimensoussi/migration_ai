"""Affichage des graphiques (render_chart des agents, creer_visuel de HakimAI) : Vega-Lite, API Streamlit 1.38."""
import streamlit as st

from tools.chart_tools import vega_spec


def render(v: dict | None, key: str = "", caption: str = "") -> None:
    if not v:
        return
    if caption:
        st.caption(caption)
    if v["type"] == "tableau":
        st.caption(v["titre"])
        st.dataframe(v["lignes"], use_container_width=True, hide_index=True)
    else:
        st.vega_lite_chart(vega_spec(v), use_container_width=True)
    label = f"{v.get('id') + ' · ' if v.get('id') else ''}requête et données ({len(v['lignes'])} lignes"
    with st.expander(label + (", tronqué)" if v.get("tronque") else ")")):
        st.code(v["requete"], language="sql")
        if v["type"] != "tableau":
            st.dataframe(v["lignes"], use_container_width=True, hide_index=True)
