import streamlit as st

from ui import state

st.title("Knowledge Studio")
st.caption("Bases de connaissances documentaires interrogées par les agents avec l'outil « Rechercher des documents ».")

spec = next((t for t in state.registry().specs.values() if t.tool_id == "search_documents"), None)
bases = ((spec.config or {}).get("bases") or {}) if spec else {}
if not spec or spec.status != "publie" or not bases:
    st.info("L'outil de recherche documentaire n'est pas encore publié.")
    st.stop()

st.subheader("Bases disponibles")
st.dataframe([{"base": k, "titre": b.get("titre", k), "index AI Search": b["index"]} for k, b in bases.items()],
             use_container_width=True, hide_index=True)
st.caption("Pour qu'un agent utilise ces bases : Agent Builder, étape Outils, cocher « Rechercher des documents ».")

st.subheader("Tester une recherche")
c1, c2 = st.columns([1, 3])
base = c1.selectbox("Base", list(bases))
q = c2.text_input("Question", placeholder="Ex. : quels sont les risques d'approvisionnement ?")
if st.button("Rechercher", type="primary") and q.strip():
    from backend.tool_registry import ToolContext
    from tools.doc_tools import search_documents
    from ui import source_view
    try:
        w_, sql_, ident = state.user_session()
        res = search_documents(ToolContext(sql=sql_, workspace=w_, user_email=ident.email), spec, q, base=base)
        source_view.render(res)
    except Exception as e:  # noqa: BLE001
        st.error(str(e))

st.subheader("Prochaines étapes")
st.markdown("""
- Dépôt de documents dans un Volume Unity Catalog, lecture avec `ai_parse_document`, découpage et index par base.
- Suivi des bases, documents et ingestions (traçabilité de la source jusqu'au passage).
- Rattachement des Knowledge Assistants existants comme sources.
""")
