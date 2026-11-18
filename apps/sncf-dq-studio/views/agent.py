"""Analyste IA Data Quality : agent outille en lecture seule sur les resultats de la source choisie."""
import json

import streamlit as st

from backend.agent import DqAnalyst
from backend.model_client import ModelClient
from ui import components as C
from ui import state

source = state.current_source()
if not source:
    C.no_source()

C.header("Analyste IA Data Quality",
         f"Perimetre : {source.get('libelle') or source['code_source']} ({source['dq_prefix']}_*). L'agent lit les resultats "
         "avec vos droits, ne modifie rien et ne lance aucun job. Les regles qu'il propose sont des brouillons a valider.")

settings = state.settings()
key = f"chat_{source['code_source']}"
history = st.session_state.setdefault(key, [])

EXEMPLES = [
    "Quelles sont les regles critiques ou bloquantes en echec et que faut-il faire en priorite ?",
    "Resume les anomalies de la derniere execution et propose des causes possibles.",
    "Compare les deux dernieres executions : qu'est-ce qui a change ?",
    "A partir du profilage, propose des regles candidates pour l'objet le plus a risque.",
]

question = None
if not history:
    st.caption("Exemples de questions :")
    cols = st.columns(2)
    for i, ex in enumerate(EXEMPLES):
        if cols[i % 2].button(ex, key=f"ex_{i}"):
            question = ex

for m in history:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        for d in m.get("drafts") or []:
            st.caption("Regle candidate (brouillon, statut a_valider, non enregistree)")
            st.code(json.dumps(d, ensure_ascii=False, indent=2), language="json")
        if m.get("tools"):
            with st.expander(f"Outils utilises ({len(m['tools'])})"):
                for t in m["tools"]:
                    st.caption(f"{t['outil']} {json.dumps(t['arguments'], ensure_ascii=False)}"
                               + (f" -> erreur : {t['erreur']}" if t.get("erreur") else ""))

typed = st.chat_input("Posez votre question sur la qualite des donnees")
question = typed or question

if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        status = st.status("Analyse en cours...", expanded=False)
        w, sql, _ = state.user_session()
        agent = DqAnalyst(
            ModelClient(w), sql, settings.model_endpoint, settings.catalog, source["dq_prefix"],
            bronze_fqn=f"{source['bronze_catalog']}.{source['bronze_schema']}",
            source_label=source.get("libelle") or source["code_source"], max_rows=settings.max_rows,
            on_event=lambda ev: status.write(f"Outil {ev['outil']}" + (" (erreur)" if ev.get("erreur") else "")))
        try:
            res = agent.run(question, history)
        except Exception as e:  # noqa: BLE001
            status.update(label="Echec de l'analyse", state="error")
            st.error(f"L'agent n'a pas pu repondre : {str(e)[:500]}")
            st.stop()
        status.update(label=f"Analyse terminee ({len(res.tool_calls)} appel(s) d'outils)", state="complete")
        st.markdown(res.answer)
        for d in res.drafts:
            st.caption("Regle candidate (brouillon, statut a_valider, non enregistree)")
            st.code(json.dumps(d, ensure_ascii=False, indent=2), language="json")
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": res.answer, "drafts": res.drafts, "tools": res.tool_calls})

if history and st.button("Nouvelle conversation"):
    st.session_state[key] = []
    st.rerun()
