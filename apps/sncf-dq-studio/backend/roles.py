"""Roles applicatifs et permissions (gouvernance DAMA : qui peut lancer, valider, administrer).

Source des roles : table <catalog>.sncf_dqv3_app.app_roles (en attendant les groupes Entra ID)
+ variable DQ_ADMINS (role admin_dq). Un utilisateur sans role est lecteur.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

ROLES = ("lanceur", "steward", "resp_metier", "admin_dq")
ROLE_LABELS = {
    "lanceur": "Lanceur de controles",
    "steward": "Data Steward",
    "resp_metier": "Responsable metier",
    "admin_dq": "Administrateur Data Quality",
}
PERMISSIONS = {
    "lancer": {"lanceur", "steward", "admin_dq"},
    "valider_regle": {"resp_metier", "admin_dq"},
    "gerer_anomalies": {"steward", "resp_metier", "admin_dq"},
    "gerer_sources": {"admin_dq"},
}


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "oui")


@dataclass(frozen=True)
class UserRoles:
    email: str
    roles: frozenset

    def can(self, action: str) -> bool:
        return bool(self.roles & PERMISSIONS.get(action, set()))

    def labels(self) -> list[str]:
        return [ROLE_LABELS[r] for r in ROLES if r in self.roles] or ["Lecteur"]


def resolve_roles(email: str, rows: Iterable[dict], admins: Iterable[str] = ()) -> UserRoles:
    e = (email or "").strip().lower()
    roles = {
        r.get("role") for r in rows
        if (r.get("principal") or "").strip().lower() == e and truthy(r.get("actif")) and r.get("role") in ROLES
    }
    if e and e in {a.strip().lower() for a in admins}:
        roles.add("admin_dq")
    return UserRoles(email=e, roles=frozenset(roles))


def required_roles(action: str) -> list[str]:
    return [ROLE_LABELS[r] for r in ROLES if r in PERMISSIONS.get(action, set())]
