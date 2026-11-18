"""Tables de l'App (<catalog>.sncf_dqv3_app) : sources autorisees, roles, journal des lancements.

Lectures : identite de l'utilisateur. Ecritures : service principal (apres controle du role).
"""
from __future__ import annotations

from backend.jobs_service import params_json
from backend.naming import check_identifier


class AppRepository:
    def __init__(self, read_sql, write_sql, catalog: str, schema: str):
        self.read_sql, self.write_sql = read_sql, write_sql
        self.fqn = f"{check_identifier(catalog, 'catalogue')}.{check_identifier(schema, 'schema')}"

    def sources(self, actives_only: bool = True) -> list[dict]:
        where = "WHERE actif" if actives_only else ""
        return self.read_sql.query(
            f"""SELECT code_source, libelle, bronze_catalog, bronze_schema, dq_prefix, filiere, proprietaire,
                       tables_incluses, tables_exclues, ref_catalog, ref_schema, actif, maj_par, maj_le
                FROM {self.fqn}.app_sources {where} ORDER BY code_source""")["rows"]

    def roles_rows(self, email: str) -> list[dict]:
        return self.read_sql.query(
            f"SELECT principal, role, filiere, actif FROM {self.fqn}.app_roles WHERE lower(principal) = lower(:e)",
            {"e": email})["rows"]

    def log_launch_request(self, lancement_id: str, user_email: str, code_source: str, dq_prefix: str,
                           job_id: int, params: dict) -> None:
        self.write_sql.execute(
            f"""INSERT INTO {self.fqn}.app_lancements
                (lancement_id, demande_par, demande_le, code_source, dq_prefix, job_id, job_run_id, parametres, statut, message, maj_le)
                VALUES (:id, :u, current_timestamp(), :c, :p, :j, CAST(NULL AS BIGINT),
                        from_json(:params, 'map<string,string>'), 'demande', NULL, current_timestamp())""",
            {"id": lancement_id, "u": user_email, "c": code_source, "p": dq_prefix, "j": int(job_id),
             "params": params_json(params)})

    def mark_launch(self, lancement_id: str, statut: str, job_run_id: int | None, message: str | None) -> None:
        self.write_sql.execute(
            f"""UPDATE {self.fqn}.app_lancements
                SET statut = :s, job_run_id = CAST(:r AS BIGINT), message = :m, maj_le = current_timestamp()
                WHERE lancement_id = :id""",
            {"s": statut, "r": None if job_run_id is None else str(job_run_id), "m": message, "id": lancement_id})

    def lancements(self, limit: int = 100) -> list[dict]:
        return self.read_sql.query(
            f"""SELECT lancement_id, demande_par, demande_le, code_source, dq_prefix, job_run_id, statut, message
                FROM {self.fqn}.app_lancements ORDER BY demande_le DESC LIMIT {int(limit)}""")["rows"]
