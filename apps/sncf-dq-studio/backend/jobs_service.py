"""Lancement et suivi du job de la chaine DQ v3 (API Jobs 2.2).

Le lancement passe par le service principal de l'App (CAN_MANAGE_RUN sur le job uniquement),
apres controle du role de l'utilisateur. Le run s'execute avec l'identite run_as du job.
Les parametres ne sont jamais saisis librement : la source vient de la liste blanche app_sources
et le prefixe est calcule (sncf_dqv3_<code_source>).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from backend.naming import (DEFAULT_EXCLUSIONS, FILIERES, PREFIX_ROOT, NamingError, check_code_source,
                            check_identifier, parse_patterns, prefix_for)
from backend.roles import UserRoles

JOB_PARAM_KEYS = ("bronze_catalog", "bronze_schema", "tables_incluses", "tables_exclues", "filiere_defaut",
                  "dq_catalog", "dq_prefix", "ref_catalog", "ref_schema")

ETATS = {
    "SUCCESS": "Reussi", "FAILED": "Echec", "TIMEDOUT": "Delai depasse", "CANCELED": "Annule",
    "CANCELLED": "Annule", "SKIPPED": "Ignore", "UPSTREAM_FAILED": "Non execute (echec amont)",
    "UPSTREAM_CANCELED": "Non execute (amont annule)", "EXCLUDED": "Exclu", "SUCCESS_WITH_FAILURES": "Reussi avec echecs",
    "MAXIMUM_CONCURRENT_RUNS_REACHED": "Refuse (run deja en cours)", "INTERNAL_ERROR": "Erreur interne",
    "RUNNING": "En cours", "PENDING": "En attente", "QUEUED": "En file d'attente", "BLOCKED": "Bloque",
    "TERMINATING": "En cours d'arret", "TERMINATED": "Termine", "WAITING": "En attente",
    "SUCCEEDED": "Reussi",
}


class LaunchError(RuntimeError):
    pass


class LaunchRefused(LaunchError):
    pass


class AuditUnavailable(LaunchError):
    pass


def libelle_etat(code: str | None) -> str:
    return ETATS.get((code or "").upper(), code or "Inconnu")


def build_job_parameters(source: dict, dq_catalog: str, tables_incluses: str | None = None,
                         tables_exclues: str | None = None, filiere: str | None = None) -> dict[str, str]:
    """Parametres du job pour une source de la liste blanche (valides, sans saisie libre de schema)."""
    code = check_code_source(source.get("code_source"))
    prefix = prefix_for(code)
    if source.get("dq_prefix") and source["dq_prefix"] != prefix:
        raise NamingError(f"Le prefixe enregistre pour la source {code} ({source['dq_prefix']}) ne respecte pas "
                          f"la regle {PREFIX_ROOT}_<code_source> : corrigez app_sources.")
    inc = parse_patterns(source.get("tables_incluses") if tables_incluses is None else tables_incluses) or ["%"]
    exc = parse_patterns(source.get("tables_exclues") if tables_exclues is None else tables_exclues)
    for p in DEFAULT_EXCLUSIONS:  # les tables techniques restent toujours exclues
        if p not in exc:
            exc.append(p)
    fil = (filiere or source.get("filiere") or "a_qualifier").strip()
    if fil not in FILIERES:
        raise NamingError(f"Filiere inconnue : {fil!r} (valeurs : {', '.join(FILIERES)}).")
    return {
        "bronze_catalog": check_identifier(source.get("bronze_catalog"), "catalogue Bronze"),
        "bronze_schema": check_identifier(source.get("bronze_schema"), "schema Bronze"),
        "tables_incluses": ",".join(inc),
        "tables_exclues": ",".join(exc),
        "filiere_defaut": fil,
        "dq_catalog": check_identifier(dq_catalog, "catalogue DQ"),
        "dq_prefix": prefix,
        "ref_catalog": check_identifier(source.get("ref_catalog") or dq_catalog, "catalogue des referentiels"),
        "ref_schema": check_identifier(source.get("ref_schema") or f"{PREFIX_ROOT}_ref", "schema des referentiels"),
    }


def run_now(w, job_id: int, params: dict[str, str]) -> int:
    resp = w.api_client.do("POST", "/api/2.2/jobs/run-now", body={"job_id": int(job_id), "job_parameters": params})
    run_id = (resp or {}).get("run_id")
    if not run_id:
        raise LaunchError(f"Reponse inattendue de l'API Jobs : {resp}")
    return int(run_id)


def launch(app_repo, w_sp, job_id: int, user_email: str, roles: UserRoles, source: dict,
           params: dict[str, str]) -> dict:
    """Controle du role -> trace de la demande -> lancement -> mise a jour de la trace.

    Sans trace possible (droits manquants du service principal), le lancement est refuse :
    tout lancement depuis l'App doit etre trace (qui, quand, quels parametres).
    """
    if not roles.can("lancer"):
        raise LaunchRefused("Votre profil ne permet pas de lancer la chaine DQ.")
    lancement_id = str(uuid.uuid4())
    try:
        app_repo.log_launch_request(lancement_id, user_email, source["code_source"], params["dq_prefix"],
                                    int(job_id), params)
    except Exception as e:  # noqa: BLE001
        raise AuditUnavailable(f"Impossible de tracer la demande dans le journal des lancements : {e}") from e
    try:
        run_id = run_now(w_sp, job_id, params)
    except Exception as e:  # noqa: BLE001
        try:
            app_repo.mark_launch(lancement_id, "echec_lancement", None, str(e)[:900])
        except Exception:  # noqa: BLE001
            pass
        raise LaunchError(f"Le job n'a pas pu etre lance : {e}") from e
    warning = None
    try:
        app_repo.mark_launch(lancement_id, "lance", run_id, None)
    except Exception as e:  # noqa: BLE001
        warning = f"Run lance mais trace non mise a jour : {e}"
    return {"lancement_id": lancement_id, "run_id": run_id, "warning": warning}


def _dt(ms) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc) if ms else None
    except (TypeError, ValueError):
        return None


def run_params(run: dict) -> dict[str, str]:
    out = {}
    for p in run.get("job_parameters") or []:
        out[p.get("name")] = p["value"] if "value" in p else p.get("default")
    return out


def _duree_s(obj: dict) -> float | None:
    for k in ("run_duration", "execution_duration"):
        if obj.get(k):
            return round(int(obj[k]) / 1000, 1)
    start, end = obj.get("start_time"), obj.get("end_time")
    if start and end:
        return round((int(end) - int(start)) / 1000, 1)
    return None


def summarize_run(run: dict) -> dict:
    state = run.get("state") or {}
    status = run.get("status") or {}
    term = status.get("termination_details") or {}
    etat = status.get("state") or state.get("life_cycle_state")
    resultat = state.get("result_state") or (term.get("code") if etat == "TERMINATED" else None)
    params = run_params(run)
    return {
        "run_id": run.get("run_id"),
        "debut": _dt(run.get("start_time")),
        "fin": _dt(run.get("end_time")),
        "duree_s": _duree_s(run),
        "etat": libelle_etat(etat),
        "resultat": libelle_etat(resultat) if resultat else "",
        "message": state.get("state_message") or term.get("message") or "",
        "bronze_schema": params.get("bronze_schema"),
        "dq_prefix": params.get("dq_prefix"),
        "declencheur": run.get("trigger"),
        "lien": run.get("run_page_url"),
    }


def task_summary(run: dict) -> list[dict]:
    """Derniere tentative de chaque tache (les reparations creent plusieurs entrees par tache)."""
    latest: dict[str, dict] = {}
    for t in run.get("tasks") or []:
        key = t.get("task_key")
        rank = (int(t.get("attempt_number") or 0), int(t.get("start_time") or 0))
        if key not in latest or rank >= latest[key][0]:
            latest[key] = (rank, t)
    out = []
    for _, t in sorted(latest.values(), key=lambda x: (x[1].get("start_time") or 0)):
        st = t.get("state") or {}
        status = t.get("status") or {}
        code = st.get("result_state") or status.get("state") or st.get("life_cycle_state")
        out.append({
            "tache": t.get("task_key"),
            "etat": libelle_etat(code),
            "code": code,
            "debut": _dt(t.get("start_time")),
            "duree_s": _duree_s(t),
            "tentative": t.get("attempt_number"),
            "message": st.get("state_message") or "",
            "task_run_id": t.get("run_id"),
        })
    return out


def list_runs(w, job_id: int, limit: int = 25) -> list[dict]:
    resp = w.api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": int(job_id), "limit": int(limit)})
    return [summarize_run(r) for r in (resp or {}).get("runs", [])]


def get_run(w, run_id: int) -> dict:
    return w.api_client.do("GET", "/api/2.2/jobs/runs/get", query={"run_id": int(run_id)}) or {}


def task_error(w, task_run_id: int) -> str:
    try:
        out = w.api_client.do("GET", "/api/2.2/jobs/runs/get-output", query={"run_id": int(task_run_id)}) or {}
    except Exception as e:  # noqa: BLE001
        return f"Sortie indisponible : {e}"
    return (out.get("error") or "")[:2000]


def params_json(params: dict) -> str:
    return json.dumps({k: params[k] for k in JOB_PARAM_KEYS if k in params}, ensure_ascii=False)
