"""Identités : service principal de l'App (configuration) et utilisateur connecté (outils, modèles).

Règle : les outils et les modèles s'exécutent TOUJOURS avec le jeton de l'utilisateur
(autorisation « on-behalf-of-user » de Databricks Apps), afin que les droits Unity Catalog
de l'utilisateur s'appliquent. Sans jeton utilisateur dans une App, l'exécution est refusée :
on ne se replie jamais sur le service principal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from databricks.sdk import WorkspaceClient

from backend.config import running_in_databricks_app


class UserAuthMissing(RuntimeError):
    """Le jeton utilisateur n'est pas transmis (autorisation utilisateur non configurée)."""


@dataclass
class UserIdentity:
    email: str
    mode: str  # "utilisateur" (jeton transmis) | "developpement" (hors App)


def app_client() -> WorkspaceClient:
    """Client du service principal de l'App (variables d'environnement injectées par Databricks Apps)."""
    return WorkspaceClient()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    if not headers:
        return None
    for k in (name, name.lower()):
        v = headers.get(k)
        if v:
            return v
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def resolve_user(headers: Mapping[str, str], host: str) -> tuple[WorkspaceClient, UserIdentity]:
    """Construit le client de l'utilisateur à partir des en-têtes transmis par Databricks Apps."""
    token = _header(headers, "X-Forwarded-Access-Token")
    email = _header(headers, "X-Forwarded-Email") or _header(headers, "X-Forwarded-Preferred-Username")
    if token:
        w = WorkspaceClient(host=host, token=token, auth_type="pat")
        return w, UserIdentity(email=email or "inconnu", mode="utilisateur")
    if running_in_databricks_app():
        raise UserAuthMissing(
            "Le jeton utilisateur n'est pas transmis à l'App. Activez l'autorisation utilisateur "
            "(user_api_scopes : sql, serving.serving-endpoints) puis redémarrez l'App.")
    w = WorkspaceClient()  # exécution locale : identité du développeur
    return w, UserIdentity(email=w.current_user.me().user_name, mode="developpement")
