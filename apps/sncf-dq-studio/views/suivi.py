"""Suivi des executions : etat par tache, erreurs techniques separees des anomalies metier."""
import pandas as pd
import streamlit as st

from backend import jobs_service as J
from backend.dq_repository import DqRepository
from backend.naming import NamingError, check_prefix
from ui import components as C
from ui import state

C.header("Suivi des executions", "Runs du job de la chaine DQ v3 : etat technique de chaque tache, puis bilan metier.")
settings = state.settings()

if st.button("Actualiser"):
    st.rerun()

try:
    runs = J.list_runs(state.app_w(), settings.job_id, 25)
except Exception as e:  # noqa: BLE001
    C.sql_error("Liste des runs indisponible (droit CAN_MANAGE_RUN du service principal sur le job)", e)
    st.stop()
if not runs:
    st.info("Aucun run pour ce job.")
    st.stop()

lanceurs = {}
try:
    for r in state.app_repo().lancements(200):
        if r.get("job_run_id"):
            lanceurs[str(r["job_run_id"])] = r.get("demande_par")
except Exception:  # noqa: BLE001
    pass

table = pd.DataFrame([{**r, "lance_par": lanceurs.get(str(r["run_id"]), "hors App")} for r in runs])
st.dataframe(table[["run_id", "debut", "duree_s", "etat", "resultat", "bronze_schema", "dq_prefix", "lance_par", "message"]],
             hide_index=True, use_container_width=True)

ids = [r["run_id"] for r in runs]
pre = st.session_state.get("suivi_run_id")
run_id = st.selectbox("Detail du run", ids, index=ids.index(pre) if pre in ids else 0)
run = J.get_run(state.app_w(), run_id)
summary = J.summarize_run(run)
st.markdown(f"**Run {run_id}** - {summary['etat']} {summary['resultat']} - source {summary['bronze_schema']} - "
            f"prefixe {summary['dq_prefix']}")
if summary.get("lien"):
    st.caption(f"Lien Databricks : {summary['lien']}")

st.subheader("Etat technique des taches")
tasks = J.task_summary(run)
st.dataframe(pd.DataFrame(tasks).drop(columns=["code", "task_run_id"], errors="ignore"), hide_index=True,
             use_container_width=True)
for t in tasks:
    if t["code"] in ("FAILED", "TIMEDOUT", "INTERNAL_ERROR") and t.get("task_run_id"):
        with st.expander(f"Erreur technique - tache {t['tache']}"):
            st.code(J.task_error(state.app_w(), t["task_run_id"]) or t["message"] or "Pas de detail.", language="text")

try:
    prefix = check_prefix(summary.get("dq_prefix") or "")
except NamingError:
    st.stop()
_, sql, _ = state.user_session()
repo = DqRepository(sql, settings.catalog, prefix)
try:
    if not repo.exists():
        st.info(f"Les schemas {prefix}_* n'existent pas encore (initialisation non executee).")
        st.stop()
    st.subheader("Erreurs techniques consignees par la chaine")
    err = C.to_df(repo.erreurs_techniques(run_id))
    if err.empty:
        st.success("Aucune erreur technique consignee.")
    else:
        st.dataframe(err, hide_index=True, use_container_width=True)
    st.caption("Etapes executees :")
    st.dataframe(C.to_df(repo.etapes_run(run_id)), hide_index=True, use_container_width=True)

    st.subheader("Bilan metier des regles (anomalies de donnees)")
    bilan = C.to_df(repo.bilan_regles_run(run_id))
    if bilan.empty:
        st.caption("Pas encore de resultat de regles pour ce run.")
    else:
        crit = int(bilan["nb_critiques_en_echec"].fillna(0).sum())
        if crit:
            st.error(f"{crit} regle(s) critique(s) en echec sur ce run.")
        st.dataframe(bilan, hide_index=True, use_container_width=True)
    silver = C.to_df(repo.passage_silver_run(run_id))
    if not silver.empty:
        st.caption("Passage Bronze -> Silver / quarantaine :")
        st.dataframe(silver, hide_index=True, use_container_width=True)
except Exception as e:  # noqa: BLE001
    C.sql_error("Lecture des resultats du run impossible", e)
