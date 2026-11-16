"""Affichage des sources de search_documents (fichier, page, extrait) : API Streamlit 1.38."""
import streamlit as st


def render(result: dict | None, caption: str = "") -> None:
    if not isinstance(result, dict):
        return
    sources = result.get("_ui_sources") or []
    label = f"Sources consultées : {result.get('titre_base') or result.get('base')} ({len(sources)} passage(s))"
    with st.expander(caption + label if caption else label):
        st.caption(f"Question : {result.get('question', '')}")
        if not sources:
            st.write(result.get("message") or "Aucun passage trouvé.")
        for s in sources:
            score = f" · score {s['score']}" if s.get("score") is not None else ""
            st.markdown(f"**{s.get('rang')}. {s.get('fichier') or 'fichier inconnu'}, p. {s.get('page', '?')}**{score}")
            st.text(str(s.get("texte") or "")[:3000])
