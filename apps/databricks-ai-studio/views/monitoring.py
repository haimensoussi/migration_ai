import pandas as pd
import streamlit as st

from ui import state

st.title("Monitoring")
repo = state.repository()
try:
    stats = repo.tool_call_stats()
    lat = repo.turn_latency_stats()
    recent = repo.recent_tool_calls(50)
except Exception as e:  # noqa: BLE001
    st.error(f"Lecture impossible : {e}")
    st.stop()

st.subheader("Appels d'outils par outil")
if stats:
    st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)
else:
    st.info("Aucun appel.")
st.subheader("Temps de réponse des agents")
if lat:
    st.dataframe(pd.DataFrame(lat), use_container_width=True, hide_index=True)
else:
    st.info("Aucune réponse journalisée.")
st.subheader("Derniers appels et erreurs")
if recent:
    df = pd.DataFrame(recent)
    only_err = st.toggle("Erreurs et refus uniquement")
    st.dataframe(df[df["status"] != "succes"] if only_err else df, use_container_width=True, hide_index=True)
st.caption("Consommation des modèles (tokens, coûts) : prévue en phase 3 via les tables d'inférence et "
           "system.serving, sous réserve d'accès au catalogue system.")
