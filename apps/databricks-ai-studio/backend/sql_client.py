"""Exécution SQL via l'API Statement Execution (REST, compatible toutes versions du SDK).

Gère les paramètres nommés, l'attente asynchrone, le timeout (annulation) et les erreurs.
"""
from __future__ import annotations

import time
from typing import Any

from databricks.sdk import WorkspaceClient


class SqlError(RuntimeError):
    pass


class SqlTimeout(SqlError):
    pass


def _param(name: str, value: Any) -> dict:
    if value is None:
        return {"name": name, "type": "STRING"}  # valeur omise = NULL
    if isinstance(value, bool):
        return {"name": name, "value": str(value).lower(), "type": "BOOLEAN"}
    if isinstance(value, int):
        return {"name": name, "value": str(value), "type": "BIGINT"}
    if isinstance(value, float):
        return {"name": name, "value": repr(value), "type": "DOUBLE"}
    return {"name": name, "value": str(value), "type": "STRING"}


class SqlClient:
    def __init__(self, w: WorkspaceClient, warehouse_id: str, timeout_s: int = 120):
        if not warehouse_id:
            raise SqlError("Aucun SQL warehouse configuré (variable DATABRICKS_WAREHOUSE_ID).")
        self.w, self.warehouse_id, self.timeout_s = w, warehouse_id, timeout_s

    def query(self, statement: str, params: dict | None = None, row_limit: int | None = None) -> dict:
        body: dict[str, Any] = {
            "statement": statement,
            "warehouse_id": self.warehouse_id,
            "wait_timeout": "30s",
            "on_wait_timeout": "CONTINUE",
            "disposition": "INLINE",
            "format": "JSON_ARRAY",
        }
        if params:
            body["parameters"] = [_param(k, v) for k, v in params.items()]
        if row_limit:
            body["row_limit"] = int(row_limit)
        deadline = time.monotonic() + self.timeout_s
        resp = self.w.api_client.do("POST", "/api/2.0/sql/statements", body=body)
        sid = resp.get("statement_id")
        while resp.get("status", {}).get("state") in ("PENDING", "RUNNING"):
            if time.monotonic() > deadline:
                try:
                    self.w.api_client.do("POST", f"/api/2.0/sql/statements/{sid}/cancel")
                finally:
                    raise SqlTimeout(f"Requête annulée après {self.timeout_s} s (timeout).")
            time.sleep(1)
            resp = self.w.api_client.do("GET", f"/api/2.0/sql/statements/{sid}")
        status = resp.get("status", {})
        if status.get("state") != "SUCCEEDED":
            err = status.get("error") or {}
            raise SqlError(err.get("message") or f"Statut {status.get('state')}")
        manifest = resp.get("manifest") or {}
        cols = [c["name"] for c in (manifest.get("schema") or {}).get("columns", [])]
        rows = (resp.get("result") or {}).get("data_array") or []
        return {
            "columns": cols,
            "rows": [dict(zip(cols, r)) for r in rows],
            "truncated": bool(manifest.get("truncated")),
        }

    def execute(self, statement: str, params: dict | None = None) -> None:
        self.query(statement, params)
