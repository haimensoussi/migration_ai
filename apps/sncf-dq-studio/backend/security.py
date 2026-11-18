"""Identites : service principal de l'App et utilisateur connecte.

Regles (choix techniques Databricks Apps) :
* les lectures de donnees et l'agent IA s'executent avec le jeton de l'utilisateur
  (autorisation on-behalf-of-user, scopes sql et model-serving) : les droits Unity Catalog de
  l'utilisateur s'appliquent ;
* seules les ecritures applicatives (journal des lancements) et le lancement du job passent par le
  service principal, apres controle du role de l'utilisateur ;
* sans jeton utilisateur dans une App, l'acces aux donnees est refuse (pas de repli sur le SP).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from databricks.sdk import WorkspaceClient


class UserAuthMissing(RuntimeError):
    """Le jeton utilisateur n'est pas transmis (autorisation utilisateur non configuree)."""


@dataclass(frozen=True)
class UserIdentity:
    email: str
    mode: str  # "utilisateur" (jeton transmis) | "developpement" (hors App)


def app_client() -> WorkspaceClient:
    """Client du service principal de l'App (variables d'environnement injectees par Databricks Apps)."""
    return WorkspaceClient()


def header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if not headers:
        return None
    low = name.lower()
    for k, v in headers.items():
        if k.lower() == low and v:
            return v
    return None


def resolve_user(headers: Mapping[str, str], host: str, in_app: bool) -> tuple[WorkspaceClient, UserIdentity]:
    """Client de l'utilisateur a partir des en-tetes transmis par Databricks Apps."""
    token = header(headers, "X-Forwarded-Access-Token")
    email = header(headers, "X-Forwarded-Email") or header(headers, "X-Forwarded-Preferred-Username")
    if token:
        w = WorkspaceClient(host=host, token=token, auth_type="pat")
        return w, UserIdentity(email=(email or "inconnu").lower(), mode="utilisateur")
    if in_app:
        raise UserAuthMissing(
            "Le jeton utilisateur n'est pas transmis a l'App. Verifiez l'autorisation utilisateur "
            "(user_api_scopes : sql, model-serving) puis redemarrez l'App.")
    w = WorkspaceClient()  # execution locale : identite du developpeur
    return w, UserIdentity(email=w.current_user.me().user_name.lower(), mode="developpement")
