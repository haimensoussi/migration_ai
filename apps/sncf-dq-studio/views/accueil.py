"""Accueil : niveau de qualite, regles critiques en echec en premier, synthese par objet, derniers runs."""
import streamlit as st

from ui import components as C
from ui import state

source = state.current_source()
if not source:
    C.no_source()

C.header("Qualite des donnees", f"Source : {source.get('libelle') or source['code_source']} - Bronze "
         f"{source['bronze_catalog']}.{source['bronze_schema']} (lecture seule) - resultats {source['dq_prefix']}_*")
repo = state.dq_repo(source)

try:
    if not repo.exists():
        st.info(f"Aucun resultat pour cette source : les schemas {source['dq_prefix']}_* n'existent pas encore. "
                "Lancez un premier controle depuis la page Lancer un controle.")
        st.stop()
    ind = repo.indicateurs()
    ouvertes = repo.anomalies_ouvertes()
except Exception as e:  # noqa: BLE001
    C.sql_error("Lecture des indicateurs impossible (droits SELECT sur les schemas Gold requis)", e)
    st.stop()

nb_crit = int(C.num(ind.get("nb_critiques_en_echec"), 0))
nb_echec = int(C.num(ind.get("nb_regles_en_echec"), 0))
nb_crit_nv = int(C.num(ind.get("nb_echecs_criticite_a_valider"), 0))

# 1. Alertes d'abord : une anomalie critique n'est jamais masquee par un score moyen
if nb_crit:
    st.error(f"{nb_crit} regle(s) CRITIQUE(S) en echec sur la derniere execution. Voir le detail ci-dessous.")
if nb_crit_nv:
    st.warning(f"{nb_crit_nv} regle(s) en echec sans criticite validee : la qualification par le responsable metier est requise.")
if int(C.num(ind.get("nb_erreurs_techniques"), 0)):
    st.warning(f"{C.entier(ind.get('nb_erreurs_techniques'))} regle(s) en erreur technique (execution, pas anomalie metier).")

c = st.columns(6)
c[0].metric("Objets controles", C.entier(ind.get("nb_objets")))
c[1].metric("Regles en echec", f"{nb_echec} / {C.entier(ind.get('nb_regles_evaluees'))}")
c[2].metric("Dont critiques", nb_crit)
c[3].metric("Anomalies ouvertes", C.entier(ouvertes.get("nb_ouvertes")))
c[4].metric("Score regles (moyen)", C.pct(ind.get("score_regles")))
c[5].metric("Score DAMA (moyen)", C.pct(ind.get("score_dama")))
st.caption(f"Derniere mesure : {ind.get('date_kpi') or 'n.d.'}. Les scores moyens sont indicatifs : ils ne remplacent pas "
           "la lecture des regles en echec. Regles non conclusives (a qualifier / non evaluees) : "
           f"{C.entier(ind.get('nb_regles_non_conclusives'))} ; dimensions DAMA sous le seuil indicatif : "
           f"{C.entier(ind.get('nb_dimensions_sous_seuil'))}.")

st.subheader("Regles en echec (critiques d'abord)")
try:
    df = C.to_df(repo.regles_en_echec())
    if df.empty:
        st.success("Aucune regle metier en echec sur la derniere execution.")
    else:
        df["criticite"] = df["criticite"].fillna("a valider")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config={"taux_conformite": st.column_config.NumberColumn(format="%.4f"),
                                    "seuil": st.column_config.NumberColumn(format="%.2f")})
except Exception as e:  # noqa: BLE001
    C.sql_error("Lecture des regles en echec impossible", e)

st.subheader("Synthese par objet")
try:
    st.dataframe(C.to_df(repo.synthese()), hide_index=True, use_container_width=True,
                 column_config={"score_regles": st.column_config.NumberColumn(format="%.4f"),
                                "score_dama": st.column_config.NumberColumn(format="%.4f"),
                                "taux_quarantaine": st.column_config.NumberColumn(format="%.4f")})
    st.caption("Bloquantes = regles en echec dont l'action est la mise en quarantaine. "
               "Reconciliation : nb_bronze = nb_silver + nb_quarantaine.")
except Exception as e:  # noqa: BLE001
    C.sql_error("Lecture de la synthese impossible", e)

st.subheader("Dernieres executions de la chaine")
try:
    st.dataframe(C.to_df(repo.runs_chaine(10)), hide_index=True, use_container_width=True)
except Exception as e:  # noqa: BLE001
    C.sql_error("Lecture du journal des executions impossible", e)
