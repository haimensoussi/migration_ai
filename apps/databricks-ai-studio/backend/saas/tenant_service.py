"""Tenant Manager : organisations, membres, rôles, paramètres et audit, avec autorisation côté serveur.

Principes de sécurité (isolation hybride) :
- L'identité est vérifiée (verified_identity) ; l'organisation courante n'est jamais déduite d'une saisie seule :
  resolve() contrôle l'adhésion active et le statut de l'organisation, puis émet un TenantContext scellé.
- Chaque opération reçoit ce contexte, vérifie le sceau, RELIT l'adhésion (droits révoqués pris en compte
  immédiatement) et la permission, puis n'accède qu'aux lignes de ctx.tenant_id.
- Refus = même message, que l'organisation existe ou non ; chaque refus est journalisé.
- Les données métier d'une organisation vont dans son schéma dédié, provisionné par un administrateur de la
  plateforme avec des droits Unity Catalog propres à l'organisation (provisioning_sql).
"""
from __future__ import annotations

import json
import uuid
from typing import Iterable

from backend.saas.models import (ACCESS_DENIED, IDENT, MEMBER_STATUSES, PLANS, SETTING_KEY, SLUG, TENANT_ID,
                                 TENANT_STATUSES, AccessDenied, Conflict, Identity, Membership, Role, Tenant,
                                 TenantContext, ValidationError, norm_email)

MAX_SETTING_CHARS = 10_000


def verified_identity(user_client, source: str = "jeton_utilisateur") -> Identity:
    """Identité confirmée par Databricks (API current-user appelée avec le jeton de l'utilisateur)."""
    me = user_client.current_user.me()
    try:
        return Identity(norm_email(getattr(me, "user_name", "")), source)
    except ValidationError as e:
        raise AccessDenied("Identité non vérifiable : accès refusé.") from e


class TenantService:
    def __init__(self, store, platform_admins: Iterable[str], tenant_catalog: str = "dataops_dev",
                 app_principal: str = ""):
        if not IDENT.match(tenant_catalog or ""):
            raise ValueError(f"Catalogue des organisations invalide : {tenant_catalog!r}")
        self.store = store
        self.platform_admins = frozenset(norm_email(e) for e in platform_admins if str(e).strip())
        self.tenant_catalog = tenant_catalog
        self.app_principal = app_principal
        self._seal = object()   # propre à cette instance : un contexte fabriqué ailleurs est refusé
        self._roles: dict[str, Role] | None = None

    # -- Outils internes ---------------------------------------------------------------------------
    def roles(self) -> dict[str, Role]:
        if self._roles is None:
            self._roles = self.store.roles()
        return self._roles

    def _audit(self, tenant_id, actor: str, action: str, outcome: str, target_type=None, target_id=None, **details):
        try:
            self.store.audit(tenant_id, actor, action, target_type, target_id, outcome, details)
        except Exception:  # noqa: BLE001 - l'audit ne doit pas masquer l'erreur métier
            pass

    def _deny(self, identity: Identity, action: str, tenant_id=None, msg: str = ACCESS_DENIED, **details):
        self._audit(tenant_id, identity.email, action, "refuse", **details)
        raise AccessDenied(msg)

    def is_platform_admin(self, identity: Identity) -> bool:
        return identity.email in self.platform_admins

    def _require_platform_admin(self, identity: Identity, action: str, tenant_id=None) -> None:
        if not self.is_platform_admin(identity):
            self._deny(identity, action, tenant_id, "Réservé aux administrateurs de la plateforme.")

    def _authorize(self, ctx: TenantContext, permission: str, action: str) -> TenantContext:
        """Vérifie le sceau, relit adhésion et organisation, puis la permission. Renvoie un contexte frais."""
        if not isinstance(ctx, TenantContext) or ctx.seal is not self._seal:
            ident = ctx.identity if isinstance(ctx, TenantContext) else Identity("inconnu", "inconnu")
            self._deny(ident, action, None, reason="contexte non emis par le service")
        fresh = self.resolve(ctx.identity, ctx.tenant_id, _action=action)
        if not fresh.can(permission):
            self._deny(ctx.identity, action, ctx.tenant_id, "Votre rôle ne permet pas cette action.",
                       permission=permission, role=fresh.role.role_id)
        return fresh

    # -- Plateforme --------------------------------------------------------------------------------
    def data_schema_for(self, slug: str) -> str:
        return f"{self.tenant_catalog}.saas_t_{slug}"

    def create_tenant(self, identity: Identity, name: str, slug: str, admin_email: str,
                      plan: str = "essai") -> Tenant:
        """Crée l'organisation puis son propriétaire. Rejouable : si le propriétaire manque, il est ajouté."""
        self._require_platform_admin(identity, "tenant.create")
        name, slug = str(name or "").strip(), str(slug or "").strip().lower()
        if not 2 <= len(name) <= 120:
            raise ValidationError("Le nom doit contenir de 2 à 120 caractères.")
        if not SLUG.match(slug):
            raise ValidationError("Code invalide : 3 à 31 caractères, minuscule en tête, puis a-z, 0-9 ou _.")
        if plan not in PLANS:
            raise ValidationError(f"Offre inconnue : {plan}")
        admin = norm_email(admin_email)
        t = Tenant(uuid.uuid4().hex, slug, name, "actif", plan, admin, self.data_schema_for(slug), "a_provisionner",
                   identity.email)
        if not self.store.insert_tenant(t):
            self._audit(None, identity.email, "tenant.create", "erreur", "tenant", slug, reason="code deja utilise")
            raise Conflict(f"Le code « {slug} » est déjà utilisé.")
        self.store.upsert_membership(Membership(t.tenant_id, admin, "owner", "actif", identity.email))
        self._audit(t.tenant_id, identity.email, "tenant.create", "succes", "tenant", t.tenant_id,
                    slug=slug, admin=admin, plan=plan)
        return self.store.get_tenant(t.tenant_id) or t

    def list_all_tenants(self, identity: Identity) -> list[Tenant]:
        self._require_platform_admin(identity, "tenant.list_all")
        return self.store.list_tenants()

    def platform_counts(self, identity: Identity) -> dict:
        self._require_platform_admin(identity, "tenant.counts")
        return self.store.counts()

    def set_tenant_status(self, identity: Identity, tenant_id: str, status: str) -> None:
        self._require_platform_admin(identity, "tenant.status", tenant_id)
        if status not in TENANT_STATUSES:
            raise ValidationError(f"Statut inconnu : {status}")
        if not self.store.get_tenant(tenant_id):
            raise ValidationError("Organisation introuvable.")
        self.store.update_tenant(tenant_id, status=status)
        self._audit(tenant_id, identity.email, "tenant.status", "succes", "tenant", tenant_id, status=status)

    def ensure_owner(self, identity: Identity, tenant_id: str) -> None:
        """Reprise après une création interrompue : rétablit le propriétaire initial s'il manque."""
        self._require_platform_admin(identity, "tenant.ensure_owner", tenant_id)
        t = self.store.get_tenant(tenant_id)
        if not t:
            raise ValidationError("Organisation introuvable.")
        if not any(m.role_id == "owner" and m.status == "actif" for m in self.store.members(tenant_id)):
            self.store.upsert_membership(Membership(tenant_id, t.admin_email, "owner", "actif", identity.email))
            self._audit(tenant_id, identity.email, "tenant.ensure_owner", "succes", "user", t.admin_email)

    def provisioning_sql(self, identity: Identity, tenant_id: str) -> str:
        """Script à exécuter par un administrateur Unity Catalog (le service principal n'a pas CREATE SCHEMA)."""
        self._require_platform_admin(identity, "tenant.provisioning_sql", tenant_id)
        t = self.store.get_tenant(tenant_id)
        if not t or not SLUG.match(t.slug):
            raise ValidationError("Organisation introuvable.")
        cat, sch, grp = self.tenant_catalog, f"saas_t_{t.slug}", f"discovery_t_{t.slug}"
        lines = [
            f"-- Provisionnement de l'organisation {t.name} ({t.slug}) - a executer par un administrateur UC",
            f"-- 1. Creer le groupe de COMPTE `{grp}` (console du compte) et y ajouter les membres de l'organisation.",
            f"-- 2. Verifier qu'aucun groupe tiers n'herite de droits sur le catalogue {cat} (SHOW GRANTS ON CATALOG {cat}) :",
            "--    un privilege au niveau catalogue donne acces a TOUS les schemas d'organisation.",
            f"CREATE SCHEMA IF NOT EXISTS {cat}.{sch} COMMENT 'Donnees de l organisation {t.slug} (DISCOVERY SaaS)';",
            f"GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE ON SCHEMA {cat}.{sch} TO `{grp}`;",
        ]
        if self.app_principal:
            lines.append(f"GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE ON SCHEMA {cat}.{sch} TO `{self.app_principal}`;")
        lines.append("-- 3. Puis dans DISCOVERY : Organisations > marquer le schema comme provisionne.")
        return "\n".join(lines)

    def mark_schema_provisioned(self, identity: Identity, tenant_id: str) -> None:
        self._require_platform_admin(identity, "tenant.schema_provisioned", tenant_id)
        if not self.store.get_tenant(tenant_id):
            raise ValidationError("Organisation introuvable.")
        self.store.update_tenant(tenant_id, data_schema_status="provisionne")
        self._audit(tenant_id, identity.email, "tenant.schema_provisioned", "succes", "tenant", tenant_id)

    # -- Utilisateur -------------------------------------------------------------------------------
    def my_tenants(self, identity: Identity) -> list[tuple[Tenant, Membership]]:
        """Organisations où l'utilisateur est membre actif (organisations suspendues incluses, signalées)."""
        ms = {m.tenant_id: m for m in self.store.memberships_of(identity.email) if m.status == "actif"}
        return [(t, ms[t.tenant_id]) for t in self.store.list_tenants(list(ms))]

    def resolve(self, identity: Identity, tenant_id: str, _action: str = "tenant.open") -> TenantContext:
        if not TENANT_ID.match(str(tenant_id or "")):
            self._deny(identity, _action, None, reason="identifiant invalide")
        m = self.store.get_membership(tenant_id, identity.email)
        t = self.store.get_tenant(tenant_id) if m else None
        if not m or m.status != "actif" or not t:
            self._deny(identity, _action, tenant_id, reason="non membre")
        if t.status != "actif":
            self._deny(identity, _action, tenant_id, "Organisation suspendue : accès refusé.", reason="suspendue")
        role = self.roles().get(m.role_id)
        if role is None:
            self._deny(identity, _action, tenant_id, reason=f"role inconnu {m.role_id}")
        return TenantContext(t, identity, role, self._seal)

    def get_tenant(self, ctx: TenantContext) -> Tenant:
        return self._authorize(ctx, "tenant.read", "tenant.read").tenant

    def list_members(self, ctx: TenantContext) -> list[Membership]:
        c = self._authorize(ctx, "users.read", "users.list")
        return self.store.members(c.tenant_id)

    def add_member(self, ctx: TenantContext, email: str, role_id: str) -> Membership:
        """Ajoute ou modifie un membre. On ne peut attribuer qu'un rôle de rang inférieur ou égal au sien."""
        c = self._authorize(ctx, "users.manage", "users.add")
        e = norm_email(email)
        role = self.roles().get(role_id)
        if role is None:
            raise ValidationError(f"Rôle inconnu : {role_id}")
        sec = self.store.settings(c.tenant_id).get("setup.securite") or {}
        domains = sec.get("allowed_domains") or []
        if domains and e.split("@")[-1] not in domains:   # règle posée par le Setup Wizard (étape Sécurité)
            raise ValidationError(f"Domaine non autorisé pour cette organisation (autorisés : {', '.join(domains)}).")
        if role.rank > c.role.rank:
            self._deny(c.identity, "users.add", c.tenant_id, "Vous ne pouvez pas attribuer un rôle supérieur au vôtre.",
                       target=e, role=role_id)
        current = self.store.get_membership(c.tenant_id, e)
        if current and self.roles().get(current.role_id) and self.roles()[current.role_id].rank > c.role.rank:
            self._deny(c.identity, "users.add", c.tenant_id, "Ce membre a un rôle supérieur au vôtre.", target=e)
        if current and current.role_id == "owner" and role_id != "owner":
            self._check_not_last_owner(c, e)
        self.store.upsert_membership(Membership(c.tenant_id, e, role_id, "actif", c.identity.email))
        self._audit(c.tenant_id, c.identity.email, "users.add", "succes", "user", e, role=role_id)
        return self.store.get_membership(c.tenant_id, e)

    def set_member_status(self, ctx: TenantContext, email: str, status: str) -> None:
        c = self._authorize(ctx, "users.manage", "users.status")
        if status not in MEMBER_STATUSES:
            raise ValidationError(f"Statut inconnu : {status}")
        e = norm_email(email)
        current = self.store.get_membership(c.tenant_id, e)
        if not current:
            raise ValidationError("Ce membre n'appartient pas à l'organisation.")
        if self.roles()[current.role_id].rank > c.role.rank:
            self._deny(c.identity, "users.status", c.tenant_id, "Ce membre a un rôle supérieur au vôtre.", target=e)
        if status != "actif" and current.role_id == "owner":
            self._check_not_last_owner(c, e)
        self.store.upsert_membership(Membership(c.tenant_id, e, current.role_id, status, c.identity.email))
        self._audit(c.tenant_id, c.identity.email, "users.status", "succes", "user", e, status=status)

    def _check_not_last_owner(self, c: TenantContext, email: str) -> None:
        owners = [m for m in self.store.members(c.tenant_id) if m.role_id == "owner" and m.status == "actif"]
        if [m.user_email for m in owners] == [email]:
            raise ValidationError("Impossible : l'organisation doit garder au moins un propriétaire actif.")

    def get_settings(self, ctx: TenantContext) -> dict:
        c = self._authorize(ctx, "settings.read", "settings.read")
        return self.store.settings(c.tenant_id)

    def put_setting(self, ctx: TenantContext, key: str, value) -> None:
        c = self._authorize(ctx, "settings.manage", "settings.put")
        if not SETTING_KEY.match(str(key or "")):
            raise ValidationError("Clé de paramètre invalide (a-z, 0-9, _ et . ; 2 à 61 caractères).")
        try:
            raw = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise ValidationError("Valeur non sérialisable en JSON.") from e
        if len(raw) > MAX_SETTING_CHARS:
            raise ValidationError(f"Valeur trop longue ({len(raw)} caractères, maximum {MAX_SETTING_CHARS}).")
        self.store.put_setting(c.tenant_id, key, value, c.identity.email)
        self._audit(c.tenant_id, c.identity.email, "settings.put", "succes", "setting", key)

    def audit_log(self, ctx: TenantContext, limit: int = 100) -> list[dict]:
        c = self._authorize(ctx, "audit.read", "audit.read")
        return self.store.audit_log(c.tenant_id, max(1, min(int(limit), 500)))
