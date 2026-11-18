"""Tenant Manager : création, consultation, autorisations et isolation entre organisations."""
import dataclasses
import json
import os
import re

import pytest

from backend.saas.models import (ACCESS_DENIED, DEFAULT_ROLES, AccessDenied, Conflict, Identity, Role,
                                 TenantContext, ValidationError)
from backend.saas.store import MemoryStore, SqlStore
from backend.saas.tenant_service import TenantService, verified_identity

PLATFORM = Identity("plateforme@discovery.io", "test")
ALICE = Identity("alice@alpha.com", "test")
BOB = Identity("bob@beta.com", "test")
CAROL = Identity("carol@beta.com", "test")
MALLORY = Identity("mallory@evil.com", "test")


def roles():
    return {k: Role(k, k, rank, frozenset(p)) for k, (rank, p) in DEFAULT_ROLES.items()}


@pytest.fixture
def env():
    store = MemoryStore(roles())
    svc = TenantService(store, [PLATFORM.email], "dataops_dev", "app-sp-id")
    a = svc.create_tenant(PLATFORM, "Alpha SA", "alpha", ALICE.email)
    b = svc.create_tenant(PLATFORM, "Beta SAS", "beta", BOB.email, plan="standard")
    return svc, store, a, b


# -- Création -------------------------------------------------------------------------------------------
def test_create_and_read(env):
    svc, store, a, b = env
    assert a.status == "actif" and a.data_schema == "dataops_dev.saas_t_alpha" and a.data_schema_status == "a_provisionner"
    assert store.get_membership(a.tenant_id, ALICE.email).role_id == "owner"
    assert svc.get_tenant(svc.resolve(ALICE, a.tenant_id)).name == "Alpha SA"
    assert [t.slug for t in svc.list_all_tenants(PLATFORM)] == ["alpha", "beta"]
    assert svc.platform_counts(PLATFORM) == {"organisations": 2, "actives": 2, "membres": 2}


def test_only_platform_admin_creates_or_lists(env):
    svc, store, a, b = env
    for call in (lambda: svc.create_tenant(ALICE, "X", "xxx", ALICE.email), lambda: svc.list_all_tenants(ALICE),
                 lambda: svc.provisioning_sql(ALICE, a.tenant_id), lambda: svc.set_tenant_status(ALICE, b.tenant_id, "suspendu")):
        with pytest.raises(AccessDenied):
            call()
    assert sum(x["outcome"] == "refuse" and x["actor_email"] == ALICE.email for x in store.audits) == 4


@pytest.mark.parametrize("name,slug,admin,plan", [("A", "ok_slug", "a@b.fr", "essai"), ("Nom", "1abc", "a@b.fr", "essai"),
                                                  ("Nom", "AB", "a@b.fr", "essai"), ("Nom", "abc; drop", "a@b.fr", "essai"),
                                                  ("Nom", "abcd", "pas-un-mail", "essai"), ("Nom", "abcd", "a@b.fr", "gratuit")])
def test_create_validation(env, name, slug, admin, plan):
    with pytest.raises(ValidationError):
        env[0].create_tenant(PLATFORM, name, slug, admin, plan)


def test_duplicate_slug(env):
    with pytest.raises(Conflict):
        env[0].create_tenant(PLATFORM, "Alpha bis", "alpha", "x@alpha.com")


# -- Isolation entre organisations ----------------------------------------------------------------------
def test_cross_tenant_access_denied_same_message(env):
    svc, store, a, b = env
    with pytest.raises(AccessDenied) as e1:
        svc.resolve(ALICE, b.tenant_id)
    with pytest.raises(AccessDenied) as e2:
        svc.resolve(ALICE, "0" * 32)            # organisation inexistante : même message (pas de fuite)
    with pytest.raises(AccessDenied):
        svc.resolve(ALICE, "' OR 1=1 --")
    assert str(e1.value) == str(e2.value) == ACCESS_DENIED
    assert svc.resolve(BOB, b.tenant_id).role.role_id == "owner"


def test_platform_admin_is_not_implicit_member(env):
    svc, store, a, b = env
    with pytest.raises(AccessDenied):
        svc.resolve(PLATFORM, a.tenant_id)


def test_forged_and_tampered_contexts_rejected(env):
    svc, store, a, b = env
    ctx_a = svc.resolve(ALICE, a.tenant_id)
    forged = TenantContext(b, ALICE, roles()["owner"], object())                      # sceau inventé
    swapped = dataclasses.replace(ctx_a, tenant=b)                                   # vrai sceau, autre organisation
    upgraded = dataclasses.replace(svc.resolve(BOB, b.tenant_id), identity=MALLORY)  # vrai sceau, autre identité
    other_svc = TenantService(store, [PLATFORM.email])
    foreign = other_svc.resolve(ALICE, a.tenant_id)                                  # émis par une autre instance
    for ctx in (forged, swapped, upgraded, foreign, "pas un contexte"):
        with pytest.raises(AccessDenied):
            svc.list_members(ctx)
    assert [m.user_email for m in svc.list_members(ctx_a)] == [ALICE.email]


def test_settings_and_audit_isolated(env):
    svc, store, a, b = env
    ca, cb = svc.resolve(ALICE, a.tenant_id), svc.resolve(BOB, b.tenant_id)
    svc.put_setting(ca, "ia.modele_defaut", "databricks-claude-sonnet-4-6")
    svc.put_setting(cb, "ia.modele_defaut", {"nom": "autre"})
    assert svc.get_settings(ca) == {"ia.modele_defaut": "databricks-claude-sonnet-4-6"}
    assert svc.get_settings(cb) == {"ia.modele_defaut": {"nom": "autre"}}
    assert {x["tenant_id"] for x in svc.audit_log(ca)} == {a.tenant_id}
    assert all(x["actor_email"] != BOB.email for x in svc.audit_log(ca))


def test_members_isolated(env):
    svc, store, a, b = env
    svc.add_member(svc.resolve(BOB, b.tenant_id), CAROL.email, "user")
    assert [m.user_email for m in svc.list_members(svc.resolve(ALICE, a.tenant_id))] == [ALICE.email]
    assert [t.slug for t, m in svc.my_tenants(CAROL)] == ["beta"]
    assert svc.my_tenants(MALLORY) == []


# -- Rôles et autorisations -----------------------------------------------------------------------------
def test_role_permissions(env):
    svc, store, a, b = env
    cb = svc.resolve(BOB, b.tenant_id)
    for email, role in (("viewer@beta.com", "viewer"), ("user@beta.com", "user"), ("builder@beta.com", "builder")):
        svc.add_member(cb, email, role)
    viewer = svc.resolve(Identity("viewer@beta.com", "test"), b.tenant_id)
    user = svc.resolve(Identity("user@beta.com", "test"), b.tenant_id)
    builder = svc.resolve(Identity("builder@beta.com", "test"), b.tenant_id)
    assert svc.get_tenant(viewer).slug == "beta"
    for call in (lambda: svc.list_members(viewer), lambda: svc.get_settings(user), lambda: svc.put_setting(builder, "a.b", 1),
                 lambda: svc.add_member(builder, "x@beta.com", "viewer"), lambda: svc.audit_log(builder)):
        with pytest.raises(AccessDenied):
            call()
    assert len(svc.list_members(builder)) == 4 and svc.get_settings(builder) == {}


def test_no_privilege_escalation(env):
    svc, store, a, b = env
    cb = svc.resolve(BOB, b.tenant_id)
    svc.add_member(cb, CAROL.email, "admin")
    cc = svc.resolve(CAROL, b.tenant_id)
    with pytest.raises(AccessDenied):
        svc.add_member(cc, "x@beta.com", "owner")          # rôle supérieur au sien
    with pytest.raises(AccessDenied):
        svc.add_member(cc, BOB.email, "viewer")            # rétrograder un propriétaire
    with pytest.raises(AccessDenied):
        svc.set_member_status(cc, BOB.email, "desactive")
    svc.add_member(cc, "x@beta.com", "admin")              # rang égal autorisé
    assert store.get_membership(b.tenant_id, BOB.email).role_id == "owner"


def test_revocation_is_immediate(env):
    svc, store, a, b = env
    cb = svc.resolve(BOB, b.tenant_id)
    svc.add_member(cb, CAROL.email, "admin")
    cc = svc.resolve(CAROL, b.tenant_id)
    assert svc.list_members(cc)
    svc.set_member_status(cb, CAROL.email, "desactive")
    with pytest.raises(AccessDenied):
        svc.list_members(cc)                                # contexte déjà émis : relu à chaque appel
    svc.add_member(cb, CAROL.email, "viewer")
    with pytest.raises(AccessDenied):
        svc.list_members(svc.resolve(CAROL, b.tenant_id))   # réactivée en lecteur : plus users.read


def test_last_owner_protected(env):
    svc, store, a, b = env
    cb = svc.resolve(BOB, b.tenant_id)
    with pytest.raises(ValidationError):
        svc.set_member_status(cb, BOB.email, "desactive")
    with pytest.raises(ValidationError):
        svc.add_member(cb, BOB.email, "admin")
    svc.add_member(cb, CAROL.email, "owner")
    svc.add_member(cb, BOB.email, "admin")                 # un autre propriétaire existe
    assert store.get_membership(b.tenant_id, BOB.email).role_id == "admin"


def test_suspended_tenant(env):
    svc, store, a, b = env
    ca = svc.resolve(ALICE, a.tenant_id)
    svc.set_tenant_status(PLATFORM, a.tenant_id, "suspendu")
    with pytest.raises(AccessDenied, match="suspendue"):
        svc.get_tenant(ca)
    assert [t.status for t, m in svc.my_tenants(ALICE)] == ["suspendu"]
    svc.set_tenant_status(PLATFORM, a.tenant_id, "actif")
    assert svc.get_tenant(ca).status == "actif"


def test_setting_validation(env):
    svc, store, a, b = env
    ca = svc.resolve(ALICE, a.tenant_id)
    for key, value in (("Mauvaise Cle", 1), ("a", 1), ("ok.cle", "x" * 20_000), ("ok.cle", {1, 2})):
        with pytest.raises(ValidationError):
            svc.put_setting(ca, key, value)


# -- Provisionnement, identité, reprise ----------------------------------------------------------------
def test_provisioning_sql_and_mark(env):
    svc, store, a, b = env
    s = svc.provisioning_sql(PLATFORM, a.tenant_id)
    assert "CREATE SCHEMA IF NOT EXISTS dataops_dev.saas_t_alpha" in s
    assert "TO `discovery_t_alpha`" in s and "TO `app-sp-id`" in s and "SHOW GRANTS ON CATALOG dataops_dev" in s
    svc.mark_schema_provisioned(PLATFORM, a.tenant_id)
    assert store.get_tenant(a.tenant_id).data_schema_status == "provisionne"


def test_ensure_owner_after_interrupted_creation(env):
    svc, store, a, b = env
    del store.users[(a.tenant_id, ALICE.email)]           # création interrompue après l'organisation
    svc.ensure_owner(PLATFORM, a.tenant_id)
    assert store.get_membership(a.tenant_id, ALICE.email).role_id == "owner"


class _Me:
    def __init__(self, user_name):
        self.user_name = user_name


class _Client:
    def __init__(self, user_name):
        self.current_user = type("CU", (), {"me": lambda _self: _Me(user_name)})()


def test_verified_identity():
    assert verified_identity(_Client("Alice@Alpha.com")) == Identity("alice@alpha.com", "jeton_utilisateur")
    for bad in ("", None, "service-principal-1234"):
        with pytest.raises(AccessDenied):
            verified_identity(_Client(bad))


def test_roles_match_sql_seed():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "saas_schema.sql")
    seed = {m.group(1): (int(m.group(2)), tuple(json.loads(m.group(3))))
            for m in re.finditer(r"\('(\w+)', '[^']*', (\d+), '(\[[^\]]*\])'", open(path, encoding="utf-8").read())}
    assert seed == DEFAULT_ROLES


# -- SqlStore : requêtes paramétrées et filtrées par organisation ---------------------------------------
class RecordingSql:
    def __init__(self, rows=None):
        self.calls, self.rows = [], rows or []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, dict(params or {})))
        return {"rows": list(self.rows), "columns": []}

    def execute(self, statement, params=None):
        self.query(statement, params)


def test_sql_store_parameterized_and_scoped():
    sql = RecordingSql()
    st = SqlStore(sql, lambda n: f"`dataops_dev`.`ai_studio`.`{n}`")
    tid = "a" * 32
    st.members(tid)
    st.settings(tid)
    st.audit_log(tid)
    st.get_membership(tid, "o'neil@x.com")
    st.put_setting(tid, "k.v", "val'eur", "o'neil@x.com")
    st.list_tenants([tid, "b" * 32])
    assert st.list_tenants([]) == [] and len(sql.calls) == 6   # liste vide : aucune requête
    for stmt, params in sql.calls:
        assert "o'neil" not in stmt and "val'eur" not in stmt and tid not in stmt   # aucune valeur interpolée
    for stmt, params in sql.calls[:4]:
        assert re.search(r"tenant_id = :t\b", stmt) and params["t"] == tid
    assert ":t AS tenant_id" in sql.calls[4][0] and sql.calls[4][1]["t"] == tid
    assert "IN (:t0, :t1)" in sql.calls[5][0]
    with pytest.raises(ValueError):
        st.update_tenant(tid, admin_email="x@y.fr")
