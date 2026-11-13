"""Outils Jobs : lecture de l'état des exécutions avec l'identité de l'utilisateur."""
from __future__ import annotations

from backend.tool_registry import ToolContext, ToolError


def _run_summary(r: dict) -> dict:
    st = r.get("state") or {}
    return {"run_id": r.get("run_id"), "job_id": r.get("job_id"), "nom": r.get("run_name"),
            "etat": st.get("life_cycle_state"), "resultat": st.get("result_state"),
            "message": st.get("state_message"), "debut_ms": r.get("start_time"), "fin_ms": r.get("end_time"),
            "url": r.get("run_page_url")}


def get_job_status(ctx: ToolContext, run_id: int | None = None, job_id: int | None = None) -> dict:
    api = ctx.workspace.api_client
    if run_id:
        return {"execution": _run_summary(api.do("GET", "/api/2.1/jobs/runs/get", query={"run_id": int(run_id)}))}
    if job_id:
        resp = api.do("GET", "/api/2.1/jobs/runs/list", query={"job_id": int(job_id), "limit": 5})
        return {"job_id": int(job_id), "dernieres_executions": [_run_summary(r) for r in resp.get("runs", [])]}
    raise ToolError("Indiquez run_id ou job_id.")
