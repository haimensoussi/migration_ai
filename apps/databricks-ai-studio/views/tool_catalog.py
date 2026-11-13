import json

import streamlit as st

from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from ui import state
from ui.components import badge

st.title("Tool Catalog")
tools = state.cached_tools()
if not tools:
    st.warning("Catalogue vide : initialisez-le dans Paramètres.")
    st.stop()

c1, c2, c3 = st.columns([3, 2, 2])
q = c1.text_input("Rechercher un outil").lower().strip()
cats = ["Toutes"] + sorted({t.category for t in tools})
cat = c2.selectbox("Catégorie", cats)
stat = c3.selectbox("Statut", ["Tous", "publie", "planifie", "indisponible"])
sel = [t for t in tools if (cat == "Toutes" or t.category == cat) and (stat == "Tous" or t.status == stat)
       and (not q or q in f"{t.tool_id} {t.name} {t.description}".lower())]
st.caption(f"{len(sel)} outil(s)")

cols = st.columns(2)
for i, t in enumerate(sel):
    with cols[i % 2].container(border=True):
        st.markdown(f"#### {t.name}")
        st.markdown(f"`{t.tool_id}` · {t.category} · v{t.version} {badge(t.status)}", unsafe_allow_html=True)
        st.write(t.description)
        st.caption(f"Identité : {t.identity} · lecture seule : {'oui' if t.read_only else 'non'} · "
                   f"validation humaine : {'oui' if t.requires_confirmation else 'non'}")
        with st.expander("Fiche technique"):
            st.markdown(f"Exécuteur : `{t.executor}`")
            st.caption("Schéma d'entrée")
            st.json(t.input_schema)
            st.caption("Schéma de sortie")
            st.json(t.output_schema)
        if t.status == "publie":
            with st.expander("Tester l'outil"):
                example = {k: "" for k in t.input_schema.get("required", [])}
                raw = st.text_area("Arguments JSON", json.dumps(example), key=f"args_{t.tool_id}")
                if st.button("Exécuter", key=f"run_{t.tool_id}"):
                    try:
                        w_, sql_, _ = state.user_session()
                        out = ToolRegistry([t]).run(t, ToolContext(sql_, w_, max_rows=state.settings().max_rows),
                                                    json.loads(raw or "{}"))
                        st.json(out)
                    except (ToolError, json.JSONDecodeError) as e:
                        st.error(str(e))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Erreur technique : {e}")
