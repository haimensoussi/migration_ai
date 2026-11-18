"""Lancer un controle : formulaire guide (liste blanche, prefixe calcule), controle du role, trace du lancement."""
import streamlit as st

from backend import jobs_service as J
from backend.naming import FILIERES, NamingError
from backend.roles import required_roles
from ui import components as C
from ui import state

C.header("Lancer un controle Data Quality",
         "La chaine DQ v3 lit le Bronze en lecture seule, profile les objets, applique la couche DAMA et les regles "
         "metier, separe donnees conformes et quarantaine, puis calcule les KPI Gold.")

settings = state.settings()
roles = state.user_roles()
ident = state.current_user()
try:
    srcs = state.sources()
except Exception as e:  # noqa: BLE001
    C.sql_error("Liste des sources autorisees indisponible", e)
    st.stop()
if not srcs:
    st.warning("Aucune source active dans la liste blanche (app_sources).")
    st.stop()

codes = [s["code_source"] for s in srcs]
current = st.session_state.get("source_code")
code = st.selectbox("Source Bronze (liste blanche)", codes, index=codes.index(current) if current in codes else 0,
                    format_func=lambda c: next(f"{s.get('libelle') or c} - {s['bronze_catalog']}.{s['bronze_schema']}"
                                               for s in srcs if s["code_source"] == c))
source = next(s for s in srcs if s["code_source"] == code)

col1, col2 = st.columns(2)
with col1:
    inc = st.text_input("Tables incluses (motifs LIKE separes par des virgules)", value=source.get("tables_incluses") or "%",
                        key=f"inc_{code}")
    fil_default = source.get("filiere") if source.get("filiere") in FILIERES else "a_qualifier"
    filiere = st.selectbox("Filiere par defaut des objets decouverts", FILIERES, index=FILIERES.index(fil_default),
                           key=f"fil_{code}")
with col2:
    exc = st.text_input("Tables exclues (motifs LIKE)", value=source.get("tables_exclues") or "", key=f"exc_{code}")
    st.caption("Les tables techniques (dq_%, rapport_%, slv_%, qrt_%) restent toujours exclues.")

try:
    params = J.build_job_parameters(source, settings.catalog, inc, exc, filiere)
except NamingError as e:
    st.error(str(e))
    st.stop()

st.subheader("Parametres transmis au job")
st.dataframe([{"parametre": k, "valeur": params[k]} for k in J.JOB_PARAM_KEYS], hide_index=True,
             use_container_width=True)
st.caption(f"Prefixe calcule automatiquement : {params['dq_prefix']} (resultats isoles par source). "
           f"Job : {settings.job_id}. Un seul run a la fois : un nouveau lancement est mis en file d'attente.")

if not roles.can("lancer"):
    st.info("Votre profil (" + ", ".join(roles.labels()) + ") ne permet pas de lancer la chaine. Roles requis : "
            + ", ".join(required_roles("lancer")) + ".")
    if st.session_state.get("_roles_error"):
        st.caption("Roles non lus : " + st.session_state["_roles_error"])
    st.stop()

confirm = st.checkbox("Je confirme le lancement de la chaine DQ sur cette source.", key=f"confirm_{code}")
if st.button("Lancer le controle", type="primary", disabled=not confirm):
    with st.spinner("Lancement en cours..."):
        try:
            out = J.launch(state.app_repo(), state.app_w(), settings.job_id, ident.email, roles, source, params)
        except J.AuditUnavailable as e:
            st.error("Lancement refuse : la demande ne peut pas etre tracee. Le service principal de l'App doit avoir "
                     f"MODIFY et SELECT sur {settings.app_fqn}.app_lancements.")
            st.caption(str(e)[:500])
            st.stop()
        except J.LaunchError as e:
            st.error(str(e)[:800])
            st.stop()
    st.success(f"Controle lance : run {out['run_id']}. Suivez son avancement dans la page Suivi des executions.")
    if out.get("warning"):
        st.warning(out["warning"])
    st.session_state["suivi_run_id"] = out["run_id"]

st.subheader("Derniers lancements depuis l'App")
try:
    rows = state.app_repo().lancements(20)
    if rows:
        st.dataframe(C.to_df({"rows": rows, "columns": list(rows[0].keys())}), hide_index=True, use_container_width=True)
    else:
        st.caption("Aucun lancement enregistre.")
except Exception as e:  # noqa: BLE001
    C.sql_error("Journal des lancements indisponible", e)
