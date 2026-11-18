"""Stockage du Tenant Manager : tables Delta saas_* (SqlStore) ou mémoire (MemoryStore, tests).

Règles : requêtes paramétrées uniquement ; toute lecture ou écriture propre à une organisation filtre sur
le tenant_id reçu du service (jamais d'une saisie de l'interface). Le stockage ne décide d'aucun droit.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import replace

from backend.saas.models import Membership, Role, Tenant

TENANT_COLS = ("tenant_id", "slug", "name", "status", "plan", "admin_email", "data_schema", "data_schema_status",
               "created_by", "created_at", "updated_at")
MEMBER_COLS = ("tenant_id", "user_email", "role_id", "status", "added_by", "created_at", "updated_at")


def _role(r: dict) -> Role:
    perms = r.get("permissions")
    perms = json.loads(perms) if isinstance(perms, str) else (perms or [])
    return Role(r["role_id"], r["name"], int(r["rank"]), frozenset(perms), r.get("description") or "")


def _tenant(r: dict) -> Tenant:
    return Tenant(**{k: (r.get(k) or "") for k in TENANT_COLS})


def _member(r: dict) -> Membership:
    return Membership(**{k: (r.get(k) or "") for k in MEMBER_COLS})


class SqlStore:
    """Tables Delta via SqlClient (service principal de l'App). `table(name)` renvoie le nom complet quoté."""

    def __init__(self, sql, table):
        self.sql, self.t = sql, table

    def _rows(self, stmt: str, params: dict | None = None, limit: int | None = None) -> list[dict]:
        return self.sql.query(stmt, params or {}, row_limit=limit)["rows"]

    # -- Rôles ---------------------------------------------------------------------------------------
    def roles(self) -> dict[str, Role]:
        return {r["role_id"]: _role(r) for r in self._rows(
            f"SELECT role_id, name, rank, permissions, description FROM {self.t('saas_roles')}")}

    # -- Organisations ---------------------------------------------------------------------------------
    def get_tenant(self, tenant_id: str) -> Tenant | None:
        r = self._rows(f"SELECT {', '.join(TENANT_COLS)} FROM {self.t('saas_tenants')} WHERE tenant_id = :id",
                       {"id": tenant_id}, 1)
        return _tenant(r[0]) if r else None

    def list_tenants(self, tenant_ids: list[str] | None = None) -> list[Tenant]:
        if tenant_ids is not None and not tenant_ids:
            return []
        where, params = "", {}
        if tenant_ids is not None:
            names = [f"t{i}" for i in range(len(tenant_ids))]
            where = f" WHERE tenant_id IN ({', '.join(':' + n for n in names)})"
            params = dict(zip(names, tenant_ids))
        return [_tenant(r) for r in self._rows(
            f"SELECT {', '.join(TENANT_COLS)} FROM {self.t('saas_tenants')}{where} ORDER BY name", params)]

    def insert_tenant(self, t: Tenant) -> bool:
        """Insère si ni l'identifiant ni le code n'existent. Renvoie False en cas de doublon de code."""
        self.sql.execute(
            f"MERGE INTO {self.t('saas_tenants')} d USING (SELECT :id AS tenant_id, :slug AS slug) s "
            "ON d.tenant_id = s.tenant_id OR d.slug = s.slug "
            "WHEN NOT MATCHED THEN INSERT (tenant_id, slug, name, status, plan, admin_email, data_schema, "
            "data_schema_status, created_by, created_at, updated_at) VALUES (:id, :slug, :name, :status, :plan, "
            ":admin, :schema, :schema_status, :by, current_timestamp(), current_timestamp())",
            {"id": t.tenant_id, "slug": t.slug, "name": t.name, "status": t.status, "plan": t.plan,
             "admin": t.admin_email, "schema": t.data_schema, "schema_status": t.data_schema_status,
             "by": t.created_by})
        got = self.get_tenant(t.tenant_id)
        return got is not None and got.slug == t.slug

    def update_tenant(self, tenant_id: str, **fields) -> None:
        allowed = {"status", "data_schema_status", "name", "plan"}
        if not fields or set(fields) - allowed:
            raise ValueError(f"Champs non modifiables : {sorted(set(fields) - allowed)}")
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        self.sql.execute(f"UPDATE {self.t('saas_tenants')} SET {sets}, updated_at = current_timestamp() "
                         "WHERE tenant_id = :id", {**fields, "id": tenant_id})

    # -- Membres -------------------------------------------------------------------------------------
    def get_membership(self, tenant_id: str, email: str) -> Membership | None:
        r = self._rows(f"SELECT {', '.join(MEMBER_COLS)} FROM {self.t('saas_users')} "
                       "WHERE tenant_id = :t AND user_email = :e", {"t": tenant_id, "e": email}, 1)
        return _member(r[0]) if r else None

    def memberships_of(self, email: str) -> list[Membership]:
        return [_member(r) for r in self._rows(
            f"SELECT {', '.join(MEMBER_COLS)} FROM {self.t('saas_users')} WHERE user_email = :e", {"e": email})]

    def members(self, tenant_id: str) -> list[Membership]:
        return [_member(r) for r in self._rows(
            f"SELECT {', '.join(MEMBER_COLS)} FROM {self.t('saas_users')} WHERE tenant_id = :t "
            "ORDER BY user_email", {"t": tenant_id})]

    def upsert_membership(self, m: Membership) -> None:
        self.sql.execute(
            f"MERGE INTO {self.t('saas_users')} d USING (SELECT :t AS tenant_id, :e AS user_email) s "
            "ON d.tenant_id = s.tenant_id AND d.user_email = s.user_email "
            "WHEN MATCHED THEN UPDATE SET role_id = :r, status = :st, updated_at = current_timestamp() "
            "WHEN NOT MATCHED THEN INSERT (tenant_id, user_email, role_id, status, added_by, created_at, updated_at) "
            "VALUES (:t, :e, :r, :st, :by, current_timestamp(), current_timestamp())",
            {"t": m.tenant_id, "e": m.user_email, "r": m.role_id, "st": m.status, "by": m.added_by})

    # -- Paramètres ----------------------------------------------------------------------------------
    def settings(self, tenant_id: str) -> dict:
        return {r["setting_key"]: json.loads(r["setting_value"]) if r.get("setting_value") else None
                for r in self._rows(f"SELECT setting_key, setting_value FROM {self.t('saas_settings')} "
                                    "WHERE tenant_id = :t", {"t": tenant_id})}

    def put_setting(self, tenant_id: str, key: str, value, by: str) -> None:
        self.sql.execute(
            f"MERGE INTO {self.t('saas_settings')} d USING (SELECT :t AS tenant_id, :k AS setting_key) s "
            "ON d.tenant_id = s.tenant_id AND d.setting_key = s.setting_key "
            "WHEN MATCHED THEN UPDATE SET setting_value = :v, updated_by = :by, updated_at = current_timestamp() "
            "WHEN NOT MATCHED THEN INSERT (tenant_id, setting_key, setting_value, updated_by, updated_at) "
            "VALUES (:t, :k, :v, :by, current_timestamp())",
            {"t": tenant_id, "k": key, "v": json.dumps(value, ensure_ascii=False), "by": by})

    # -- Audit -------------------------------------------------------------------------------------
    def audit(self, tenant_id: str | None, actor: str, action: str, target_type: str | None,
              target_id: str | None, outcome: str, details: dict | None = None) -> None:
        self.sql.execute(
            f"INSERT INTO {self.t('saas_audit_logs')} (audit_id, tenant_id, actor_email, action, target_type, "
            "target_id, outcome, details, created_at) VALUES (:id, :t, :a, :act, :tt, :ti, :o, :d, current_timestamp())",
            {"id": uuid.uuid4().hex, "t": tenant_id, "a": actor, "act": action, "tt": target_type, "ti": target_id,
             "o": outcome, "d": json.dumps(details or {}, ensure_ascii=False, default=str)})

    def audit_log(self, tenant_id: str, limit: int = 100) -> list[dict]:
        return self._rows(
            f"SELECT CAST(created_at AS STRING) AS created_at, actor_email, action, target_type, target_id, outcome, "
            f"details FROM {self.t('saas_audit_logs')} WHERE tenant_id = :t ORDER BY created_at DESC",
            {"t": tenant_id}, limit)

    def counts(self) -> dict:
        r = self._rows(
            f"SELECT (SELECT count(*) FROM {self.t('saas_tenants')}) AS organisations, "
            f"(SELECT count(*) FROM {self.t('saas_tenants')} WHERE status = 'actif') AS actives, "
            f"(SELECT count(*) FROM {self.t('saas_users')} WHERE status = 'actif') AS membres")
        return {k: int(v or 0) for k, v in (r[0] if r else {}).items()}


class MemoryStore:
    """Même interface que SqlStore, en mémoire (tests unitaires)."""

    def __init__(self, roles: dict[str, Role]):
        self._roles, self.tenants, self.users, self.settings_, self.audits = dict(roles), {}, {}, {}, []

    @staticmethod
    def _now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def roles(self):
        return dict(self._roles)

    def get_tenant(self, tenant_id):
        return self.tenants.get(tenant_id)

    def list_tenants(self, tenant_ids=None):
        ts = [t for t in self.tenants.values() if tenant_ids is None or t.tenant_id in tenant_ids]
        return sorted(ts, key=lambda t: t.name)

    def insert_tenant(self, t):
        if t.tenant_id in self.tenants or any(x.slug == t.slug for x in self.tenants.values()):
            return False
        now = self._now()
        self.tenants[t.tenant_id] = replace(t, created_at=now, updated_at=now)
        return True

    def update_tenant(self, tenant_id, **fields):
        if set(fields) - {"status", "data_schema_status", "name", "plan"}:
            raise ValueError("Champs non modifiables")
        self.tenants[tenant_id] = replace(self.tenants[tenant_id], **fields, updated_at=self._now())

    def get_membership(self, tenant_id, email):
        return self.users.get((tenant_id, email))

    def memberships_of(self, email):
        return [m for (t, e), m in self.users.items() if e == email]

    def members(self, tenant_id):
        return sorted((m for (t, e), m in self.users.items() if t == tenant_id), key=lambda m: m.user_email)

    def upsert_membership(self, m):
        old = self.users.get((m.tenant_id, m.user_email))
        now = self._now()
        self.users[(m.tenant_id, m.user_email)] = (
            replace(old, role_id=m.role_id, status=m.status, updated_at=now) if old
            else replace(m, created_at=now, updated_at=now))

    def settings(self, tenant_id):
        return {k: v for (t, k), v in self.settings_.items() if t == tenant_id}

    def put_setting(self, tenant_id, key, value, by):
        self.settings_[(tenant_id, key)] = json.loads(json.dumps(value))

    def audit(self, tenant_id, actor, action, target_type, target_id, outcome, details=None):
        self.audits.append({"tenant_id": tenant_id, "actor_email": actor, "action": action,
                            "target_type": target_type, "target_id": target_id, "outcome": outcome,
                            "details": details or {}})

    def audit_log(self, tenant_id, limit=100):
        return [a for a in reversed(self.audits) if a["tenant_id"] == tenant_id][:limit]

    def counts(self):
        return {"organisations": len(self.tenants),
                "actives": sum(t.status == "actif" for t in self.tenants.values()),
                "membres": sum(m.status == "actif" for m in self.users.values())}
