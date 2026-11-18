"""Modèle du Tenant Manager : identité, organisation, rôle, adhésion, contexte d'organisation."""
from __future__ import annotations

import re
from dataclasses import dataclass

TENANT_STATUSES = ("actif", "suspendu")
MEMBER_STATUSES = ("actif", "desactive")
PLANS = ("essai", "standard", "entreprise")
SCHEMA_STATUSES = ("a_provisionner", "provisionne")

SLUG = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
EMAIL = re.compile(r"^[^@\s'\"`]+@[^@\s'\"`]+\.[^@\s'\"`]+$")
TENANT_ID = re.compile(r"^[0-9a-f]{32}$")
SETTING_KEY = re.compile(r"^[a-z][a-z0-9_.]{1,60}$")
IDENT = re.compile(r"^[A-Za-z0-9_]+$")

# Référence des rôles (identique au MERGE de database/saas_schema.sql, contrôlé par les tests)
DEFAULT_ROLES = {
    "owner": (50, ("tenant.read", "tenant.manage", "users.read", "users.manage", "settings.read", "settings.manage",
                   "agents.read", "agents.manage", "agents.use", "audit.read")),
    "admin": (40, ("tenant.read", "users.read", "users.manage", "settings.read", "settings.manage", "agents.read",
                   "agents.manage", "agents.use", "audit.read")),
    "builder": (30, ("tenant.read", "users.read", "settings.read", "agents.read", "agents.manage", "agents.use")),
    "user": (20, ("tenant.read", "agents.read", "agents.use")),
    "viewer": (10, ("tenant.read", "agents.read")),
}

ACCESS_DENIED = "Accès refusé à cette organisation."   # même message si elle n'existe pas (pas de fuite)


class SaasError(Exception):
    """Erreur métier affichable à l'utilisateur."""


class AccessDenied(SaasError):
    pass


class ValidationError(SaasError):
    pass


class Conflict(SaasError):
    pass


def norm_email(v) -> str:
    e = str(v or "").strip().lower()
    if not EMAIL.match(e):
        raise ValidationError(f"Adresse e-mail invalide : {v!r}")
    return e


@dataclass(frozen=True)
class Identity:
    """Utilisateur authentifié. `source` : jeton_utilisateur (Databricks Apps), developpement, test."""
    email: str
    source: str


@dataclass(frozen=True)
class Role:
    role_id: str
    name: str
    rank: int
    permissions: frozenset
    description: str = ""


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    slug: str
    name: str
    status: str
    plan: str
    admin_email: str
    data_schema: str
    data_schema_status: str
    created_by: str
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Membership:
    tenant_id: str
    user_email: str
    role_id: str
    status: str
    added_by: str
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TenantContext:
    """Organisation courante d'un utilisateur. N'est valide que s'il a été émis par le TenantService (sceau)."""
    tenant: Tenant
    identity: Identity
    role: Role
    seal: object

    @property
    def tenant_id(self) -> str:
        return self.tenant.tenant_id

    def can(self, permission: str) -> bool:
        return permission in self.role.permissions
