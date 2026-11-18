"""Contrôles réels du Setup Wizard, exécutés avec le jeton de l'utilisateur (ses droits Databricks s'appliquent).

Ressource absente ou refusée = échec du contrôle (False, détail) ; autre incident (réseau, service) = exception,
rapportée comme erreur technique par le wizard.
"""
from __future__ import annotations

from backend.saas.setup_wizard import ENDPOINT, WAREHOUSE_ID

_REFUSALS = ("NotFound", "ResourceDoesNotExist", "PermissionDenied", "Unauthenticated", "BadRequest",
             "InvalidParameterValue")
_SQL_REFUSALS = ("SCHEMA_NOT_FOUND", "PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS", "NO_SUCH_CATALOG",
                 "CATALOG_NOT_FOUND", "does not exist", "not found")


def _refused(e: Exception) -> bool:
    return type(e).__name__ in _REFUSALS or any(t in str(e) for t in ("404", "403", "does not exist"))


class DatabricksChecker:
    def __init__(self, workspace, sql):
        self.w, self.sql = workspace, sql

    def warehouse(self, warehouse_id: str) -> tuple[bool, str]:
        if not WAREHOUSE_ID.match(warehouse_id or ""):
            return False, "Identifiant invalide."
        try:
            r = self.w.api_client.do("GET", f"/api/2.0/sql/warehouses/{warehouse_id}")
        except Exception as e:  # noqa: BLE001
            if _refused(e):
                return False, "Entrepôt introuvable ou non autorisé pour votre compte."
            raise
        state = r.get("state", "inconnu")
        return state not in ("DELETED", "DELETING"), f"{r.get('name', '')} · état {state}"

    def endpoint(self, name: str) -> tuple[bool, str]:
        if not ENDPOINT.match(name or ""):
            return False, "Nom invalide."
        try:
            r = self.w.api_client.do("GET", f"/api/2.0/serving-endpoints/{name}")
        except Exception as e:  # noqa: BLE001
            if _refused(e):
                return False, "Endpoint introuvable ou non autorisé pour votre compte."
            raise
        ready = (r.get("state") or {}).get("ready")
        task = r.get("task") or ""
        if task and task != "llm/v1/chat":
            return False, f"Tâche {task} : un endpoint de conversation (llm/v1/chat) est attendu."
        return ready == "READY", f"état {ready or 'inconnu'}"

    def schema(self, full_name: str) -> tuple[bool, str]:
        try:
            self.sql.query("DESCRIBE SCHEMA IDENTIFIER(:s)", {"s": full_name}, row_limit=5)
        except Exception as e:  # noqa: BLE001
            if any(t in str(e) for t in _SQL_REFUSALS):
                return False, "Schéma introuvable ou non autorisé pour votre compte."
            raise
        return True, "accessible"
