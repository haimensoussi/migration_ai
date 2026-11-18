"""Lecture des resultats de la chaine DQ v3 pour un prefixe (identite de l'utilisateur).

S'appuie sur les vues Gold produites par la chaine (v_dq_synthese_table, v_dq_kpi_courant,
v_dq_anomalies_courantes) et sur les tables de resultats. Aucune ecriture.
"""
from __future__ import annotations

from backend.naming import check_identifier, check_prefix, schema_fqn

CRITICITE_ORDRE = "CASE {c} WHEN 'critique' THEN 0 WHEN 'majeure' THEN 1 WHEN 'mineure' THEN 2 ELSE 3 END"


class DqRepository:
    def __init__(self, sql, catalog: str, prefix: str):
        self.sql = sql
        self.catalog = check_identifier(catalog, "catalogue")
        self.prefix = check_prefix(prefix)

    def t(self, layer: str, table: str) -> str:
        return f"{schema_fqn(self.catalog, self.prefix, layer)}.{check_identifier(table, 'table')}"

    def schemas(self) -> dict[str, str]:
        return {layer: schema_fqn(self.catalog, self.prefix, layer) for layer in ("config", "results", "gold", "silver")}

    def exists(self) -> bool:
        rows = self.sql.query(f"SHOW SCHEMAS IN {self.catalog} LIKE '{self.prefix}_gold'")["rows"]
        return bool(rows)

    # ---------- Accueil ----------
    def indicateurs(self) -> dict:
        rows = self.sql.query(f"""
            SELECT count(DISTINCT table_name) AS nb_objets,
                   avg(CASE WHEN niveau = 'dama' AND colonne = '*' AND inclus_score THEN score END) AS score_dama,
                   avg(CASE WHEN niveau = 'regle' AND inclus_score THEN score END) AS score_regles,
                   count_if(niveau = 'regle') AS nb_regles_evaluees,
                   count_if(niveau = 'regle' AND statut = 'anomalie') AS nb_regles_en_echec,
                   count_if(niveau = 'regle' AND statut = 'anomalie' AND criticite = 'critique') AS nb_critiques_en_echec,
                   count_if(niveau = 'regle' AND statut = 'anomalie' AND criticite IS NULL) AS nb_echecs_criticite_a_valider,
                   count_if(niveau = 'regle' AND statut IN ('a_qualifier', 'non_evalue')) AS nb_regles_non_conclusives,
                   count_if(niveau = 'regle' AND statut = 'erreur_technique') AS nb_erreurs_techniques,
                   count_if(niveau = 'dama' AND colonne = '*' AND inclus_score AND score < seuil) AS nb_dimensions_sous_seuil,
                   max(date_kpi) AS date_kpi
            FROM {self.t('gold', 'v_dq_kpi_courant')}""")["rows"]
        return rows[0] if rows else {}

    def anomalies_ouvertes(self) -> dict:
        rows = self.sql.query(f"""
            SELECT count(*) AS nb_ouvertes, count_if(criticite = 'critique') AS nb_critiques,
                   count_if(action_en_retard) AS nb_actions_en_retard
            FROM {self.t('gold', 'v_dq_anomalies_courantes')}
            WHERE coalesce(statut_traitement, 'ouverte') IN ('ouverte', 'en_cours')""")["rows"]
        return rows[0] if rows else {}

    def regles_en_echec(self, limit: int = 100) -> dict:
        """Regles en echec, les critiques d'abord (jamais masquees par un score moyen)."""
        return self.sql.query(f"""
            SELECT k.criticite, k.table_name, k.rule_id, k.dimension, k.action, k.nb_controles, k.nb_anomalies,
                   k.score AS taux_conformite, k.seuil, c.definition_metier, c.statut_validation, k.date_kpi
            FROM {self.t('gold', 'v_dq_kpi_courant')} k
            LEFT JOIN {self.t('config', 'dq_rule_catalog')} c
              ON c.rule_id = k.rule_id AND c.table_name = k.table_name AND c.is_active
            WHERE k.niveau = 'regle' AND k.statut = 'anomalie'
            ORDER BY {CRITICITE_ORDRE.format(c='k.criticite')}, k.nb_anomalies DESC
            LIMIT {int(limit)}""")

    def synthese(self) -> dict:
        return self.sql.query(f"""
            SELECT table_name, filiere, nature, nb_critiques_en_echec, nb_bloquantes_en_echec, nb_en_echec, nb_regles,
                   score_regles, score_dama, nb_dimensions_sous_seuil, nb_a_qualifier, nb_non_evalues, nb_erreurs_techniques,
                   nb_anomalies_regles, nb_bronze, nb_silver, nb_quarantaine, taux_quarantaine, reconciliation_ok
            FROM {self.t('gold', 'v_dq_synthese_table')}
            ORDER BY nb_critiques_en_echec DESC, nb_bloquantes_en_echec DESC, score_regles ASC NULLS LAST""")

    def runs_chaine(self, limit: int = 15) -> dict:
        return self.sql.query(f"""
            SELECT job_run_id, min(debut) AS debut, max(fin) AS fin, count(DISTINCT table_name) AS nb_tables,
                   count_if(statut <> 'succes') AS nb_echecs_techniques
            FROM {self.t('results', 'dq_run')}
            GROUP BY job_run_id ORDER BY debut DESC LIMIT {int(limit)}""")

    # ---------- Suivi d'un run ----------
    def erreurs_techniques(self, job_run_id) -> dict:
        return self.sql.query(f"""
            SELECT etape, table_name, debut, duree_s, statut, message
            FROM {self.t('results', 'dq_run')}
            WHERE job_run_id = :j AND statut <> 'succes' ORDER BY debut""", {"j": str(job_run_id)})

    def etapes_run(self, job_run_id) -> dict:
        return self.sql.query(f"""
            SELECT etape, count(DISTINCT table_name) AS nb_tables, count_if(statut = 'succes') AS nb_succes,
                   count_if(statut <> 'succes') AS nb_echecs, round(sum(duree_s), 1) AS duree_totale_s
            FROM {self.t('results', 'dq_run')} WHERE job_run_id = :j GROUP BY etape ORDER BY min(debut)""",
            {"j": str(job_run_id)})

    def bilan_regles_run(self, job_run_id) -> dict:
        return self.sql.query(f"""
            SELECT r.table_name, count(*) AS nb_regles, count_if(r.statut = 'conforme') AS nb_conformes,
                   count_if(r.statut = 'anomalie') AS nb_en_echec,
                   count_if(r.statut = 'anomalie' AND r.criticite = 'critique') AS nb_critiques_en_echec,
                   count_if(r.statut IN ('a_qualifier', 'non_evalue')) AS nb_non_conclusives,
                   count_if(r.statut = 'erreur_technique') AS nb_erreurs_techniques,
                   sum(r.nb_anomalies) AS nb_anomalies
            FROM {self.t('results', 'dq_rule_results')} r
            WHERE r.run_id IN (SELECT run_id FROM {self.t('results', 'dq_run')} WHERE job_run_id = :j)
            GROUP BY r.table_name ORDER BY nb_critiques_en_echec DESC, nb_en_echec DESC""", {"j": str(job_run_id)})

    def passage_silver_run(self, job_run_id) -> dict:
        return self.sql.query(f"""
            SELECT table_name, nb_bronze, nb_silver, nb_quarantaine, nb_signalees, reconciliation_ok
            FROM {self.t('results', 'dq_passage_silver')}
            WHERE run_id IN (SELECT run_id FROM {self.t('results', 'dq_run')} WHERE job_run_id = :j)
            ORDER BY table_name""", {"j": str(job_run_id)})
