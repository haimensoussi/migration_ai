"""Déploiement réel depuis l'App : dépôt du projet relu dans un Volume Unity Catalog,
lancement du Job de migration et déploiement (deploy=true), suivi de l'exécution.

Le Job s'exécute avec l'identité de son propriétaire : l'App n'a besoin que du droit d'écrire dans le Volume
(WRITE_VOLUME) et de lancer le Job (CAN_MANAGE_RUN). API REST appelées directement pour ne pas dépendre
de la version du SDK installée dans l'App."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

RESULT_KEYS = ("status", "attempts", "duration_s", "tests")


def deposit_dir(volume_root: str, action: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{volume_root.rstrip('/')}/{action}/{ts}"


def write_deposit(w, directory: str, action_code: str, result: dict) -> list[str]:
    """Écrit <dossier>/action.py, <dossier>/project/<fichiers relus>, <dossier>/migrator_result.json."""
    written = []

    def put(rel: str, text: str) -> None:
        path = f"{directory}/{rel}"
        w.files.upload(path, io.BytesIO(text.encode("utf-8")), overwrite=True)
        written.append(path)

    put("action.py", action_code)
    for name, content in sorted(result["files"].items()):
        put(f"project/{name}", content)
    put("migrator_result.json", json.dumps({k: result.get(k) for k in RESULT_KEYS}, ensure_ascii=False, indent=2))
    return written


def start_deploy(w, job_id: str, directory: str, uc_model: str) -> int:
    resp = w.api_client.do("POST", "/api/2.1/jobs/run-now", body={
        "job_id": int(job_id),
        "job_parameters": {"action_path": directory, "uc_model": uc_model, "deploy": "true"},
    })
    return int(resp["run_id"])


def run_status(w, run_id: int) -> dict:
    """État de l'exécution ; à la fin, résultat JSON du notebook (status, version, endpoint) ou erreur."""
    r = w.api_client.do("GET", "/api/2.1/jobs/runs/get", query={"run_id": run_id})
    state = r.get("state") or {}
    out = {
        "run_id": run_id,
        "url": r.get("run_page_url"),
        "life_cycle_state": state.get("life_cycle_state"),
        "result_state": state.get("result_state"),
        "message": state.get("state_message"),
        "start_time": r.get("start_time"),
        "end_time": r.get("end_time"),
        "result": None,
        "error": None,
    }
    tasks = r.get("tasks") or []
    if out["life_cycle_state"] in ("TERMINATED", "INTERNAL_ERROR", "SKIPPED") and tasks:
        o = w.api_client.do("GET", "/api/2.1/jobs/runs/get-output", query={"run_id": tasks[0]["run_id"]})
        raw = (o.get("notebook_output") or {}).get("result")
        if raw:
            try:
                out["result"] = json.loads(raw)
            except json.JSONDecodeError:
                out["result"] = {"raw": raw}
        out["error"] = o.get("error")
    return out


def is_finished(status: dict) -> bool:
    return status["life_cycle_state"] in ("TERMINATED", "INTERNAL_ERROR", "SKIPPED")
