"""Setup Wizard : validation, enregistrement progressif, droits, isolation, contrôles et activation."""
import itertools

import pytest

from backend.saas.models import DEFAULT_ROLES, AccessDenied, Identity, Role, ValidationError
from backend.saas.setup_checks import DatabricksChecker
from backend.saas.setup_wizard import DATA_STEPS, SetupWizard
from backend.saas.store import MemoryStore
from backend.saas.tenant_service import TenantService

PLATFORM = Identity("plateforme@discovery.io", "test")
ALICE = Identity("alice@alpha.com", "test")
BOB = Identity("bob@beta.com", "test")

VALID = {
    "organisation": {"display_name": "Alpha SA", "contact_email": "dpo@alpha.com", "language": "fr",
                     "timezone": "Europe/Paris"},
    "infrastructure": {"warehouse_id": "d0642494ed2912f0", "max_rows": 200, "sql_timeout_s": 120},
    "ia": {"default_endpoint": "databricks-claude-sonnet-4-6", "allowed_endpoints": "autre-modele",
           "temperature": 0.2, "max_tokens": 4096},
    "securite": {"default_member_role": "user", "allowed_domains": "alpha.com, @Alpha-Group.fr", "write_approval": True},
    "modules": {"agent_studio": True, "workflow_marketplace": True},
}


class FakeChecker:
    def __init__(self, warehouse=(True, "ok"), endpoint=(True, "READY"), schema=(True, "ok")):
        self.r = {"warehouse": warehouse, "endpoint": endpoint, "schema": schema}

    def _get(self, k):
        v = self.r[k]
        if isinstance(v, Exception):
            raise v
        return v

    def warehouse(self, _):
        return self._get("warehouse")

    def endpoint(self, name):
        return (False, "absent") if name == "autre-modele" else self._get("endpoint")

    def schema(self, _):
        return self._get("schema")


@pytest.fixture
def env():
    store = MemoryStore({k: Role(k, k, r, frozenset(p)) for k, (r, p) in DEFAULT_ROLES.items()})
    svc = TenantService(store, [PLATFORM.email])
    a = svc.create_tenant(PLATFORM, "Alpha SA", "alpha", ALICE.email)
    b = svc.create_tenant(PLATFORM, "Beta SAS", "beta", BOB.email)
    clock = (f"2026-11-18T10:00:{i:02d}+00:00" for i in itertools.count())
    wiz = SetupWizard(svc, now=lambda: next(clock))
    return svc, store, wiz, svc.resolve(ALICE, a.tenant_id), svc.resolve(BOB, b.tenant_id)


def fill(wiz, ctx, upto=len(DATA_STEPS)):
    for step in DATA_STEPS[:upto]:
        wiz.save_step(ctx, step, VALID[step])


def test_progressive_save_and_normalisation(env):
    svc, store, wiz, ca, cb = env
    assert wiz.state(ca)["next"] == "organisation" and wiz.state(ca)["done"] == []
    fill(wiz, ca, 2)
    st = wiz.state(ca)
    assert st["done"] == ["organisation", "infrastructure"] and st["next"] == "ia" and not st["active"]
    fill(wiz, ca)
    s = wiz.state(ca)["steps"]
    assert s["ia"]["allowed_endpoints"] == ["databricks-claude-sonnet-4-6", "autre-modele"]
    assert s["securite"]["allowed_domains"] == ["alpha.com", "alpha-group.fr"]
    assert s["modules"]["knowledge"] is False and s["modules"]["agent_studio"] is True
    assert s["organisation"]["_saved_by"] == ALICE.email
    assert {k for (t, k) in store.settings_ if t == ca.tenant_id} == {f"setup.{k}" for k in DATA_STEPS}


def test_steps_in_order(env):
    svc, store, wiz, ca, cb = env
    with pytest.raises(ValidationError, match="Organisation"):
        wiz.save_step(ca, "ia", VALID["ia"])
    with pytest.raises(ValidationError):
        wiz.save_step(ca, "inconnue", {})


@pytest.mark.parametrize("step,patch", [
    ("organisation", {"timezone": "Mars/Olympus"}), ("organisation", {"language": "de"}),
    ("organisation", {"contact_email": "x"}), ("organisation", {"display_name": "A"}),
    ("infrastructure", {"warehouse_id": "'; DROP TABLE x"}), ("infrastructure", {"max_rows": 0}),
    ("infrastructure", {"sql_timeout_s": "abc"}), ("ia", {"default_endpoint": "../secret"}),
    ("ia", {"temperature": 3}), ("ia", {"allowed_endpoints": ["ok", "pas bien"]}), ("ia", {"max_tokens": 10}),
    ("securite", {"default_member_role": "owner"}), ("securite", {"allowed_domains": ""}),
    ("securite", {"allowed_domains": "alpha"}), ("modules", {"agent_studio": False, "workflow_marketplace": False}),
    ("modules", {"inconnu": True})])
def test_validation(env, step, patch):
    svc, store, wiz, ca, cb = env
    fill(wiz, ca, DATA_STEPS.index(step))
    with pytest.raises(ValidationError):
        wiz.save_step(ca, step, VALID[step] | patch)
    assert wiz.state(ca)["steps"][step] is None          # rien n'est enregistré en cas d'erreur


def test_permissions(env):
    svc, store, wiz, ca, cb = env
    svc.add_member(ca, "builder@alpha.com", "builder")
    svc.add_member(ca, "user@alpha.com", "user")
    builder = svc.resolve(Identity("builder@alpha.com", "test"), ca.tenant_id)
    user = svc.resolve(Identity("user@alpha.com", "test"), ca.tenant_id)
    assert wiz.state(builder)["done"] == []                 # lecture autorisée (settings.read)
    with pytest.raises(AccessDenied):
        wiz.save_step(builder, "organisation", VALID["organisation"])
    with pytest.raises(AccessDenied):
        wiz.state(user)
    fill(wiz, ca)
    with pytest.raises(AccessDenied):
        wiz.activate(builder, FakeChecker())
    assert not wiz.state(ca)["active"]


def test_isolation_between_tenants(env):
    svc, store, wiz, ca, cb = env
    fill(wiz, ca)
    wiz.activate(ca, FakeChecker())
    st_b = wiz.state(cb)
    assert st_b["done"] == [] and not st_b["active"]


def test_activation_blocked_then_ok(env):
    svc, store, wiz, ca, cb = env
    with pytest.raises(ValidationError, match="complétées"):
        wiz.activate(ca, FakeChecker())
    fill(wiz, ca)
    with pytest.raises(ValidationError, match="Entrepôt"):
        wiz.activate(ca, FakeChecker(warehouse=(False, "introuvable")))
    with pytest.raises(ValidationError, match="Erreur technique"):
        wiz.activate(ca, FakeChecker(endpoint=RuntimeError("réseau")))
    assert not wiz.state(ca)["active"]
    checks = {c.check_id: c for c in wiz.activate(ca, FakeChecker())}
    assert checks["modele:autre-modele"].status == "avertissement"          # modèle secondaire : non bloquant
    assert checks["schema"].status == "avertissement"                       # non provisionné, RAG désactivé
    assert checks["module:workflow_marketplace"].status == "avertissement"
    assert checks["domaines"].status == "ok"
    st = wiz.state(ca)
    assert st["active"] and st["activated_by"] == ALICE.email and st["changed_since_activation"] == []
    wiz.save_step(ca, "ia", VALID["ia"] | {"temperature": 0.5})
    assert wiz.state(ca)["changed_since_activation"] == ["ia"]


def test_knowledge_requires_provisioned_schema(env):
    svc, store, wiz, ca, cb = env
    fill(wiz, ca, 4)
    wiz.save_step(ca, "modules", {"knowledge": True})
    with pytest.raises(ValidationError, match="Schéma"):
        wiz.activate(ca, FakeChecker())
    svc.mark_schema_provisioned(PLATFORM, ca.tenant_id)
    with pytest.raises(ValidationError, match="Schéma"):
        wiz.activate(ca, FakeChecker(schema=(False, "absent")))
    assert {c.check_id: c.status for c in wiz.activate(ca, FakeChecker())}["schema"] == "ok"


def test_allowed_domains_enforced_on_members(env):
    svc, store, wiz, ca, cb = env
    fill(wiz, ca)
    svc.add_member(ca, "x@alpha-group.fr", "user")
    with pytest.raises(ValidationError, match="Domaine"):
        svc.add_member(ca, "intrus@gmail.com", "user")
    svc.add_member(cb, "carol@gmail.com", "user")         # règle propre à Alpha : Beta n'est pas concernée
    store.upsert_membership(store.get_membership(ca.tenant_id, "x@alpha-group.fr").__class__(
        ca.tenant_id, "ancien@autre.org", "user", "actif", "test"))   # membre antérieur hors domaine
    checks = {c.check_id: c for c in wiz.checks(ca, FakeChecker())}
    assert checks["domaines"].status == "avertissement" and "ancien@autre.org" in checks["domaines"].detail


# -- DatabricksChecker (clients simulés) -----------------------------------------------------------------
class NotFound(Exception):
    pass


class Api:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def do(self, method, path, **kw):
        self.calls.append(path)
        v = self.routes.get(path)
        if isinstance(v, Exception):
            raise v
        return v


class W:
    def __init__(self, routes):
        self.api_client = Api(routes)


class Sql:
    def __init__(self, exc=None):
        self.exc, self.calls = exc, []

    def query(self, stmt, params=None, row_limit=None):
        self.calls.append((stmt, params))
        if self.exc:
            raise self.exc
        return {"rows": []}


def test_databricks_checker():
    w = W({"/api/2.0/sql/warehouses/d0642494ed2912f0": {"name": "wh", "state": "STOPPED"},
           "/api/2.0/sql/warehouses/0000000000000000": NotFound("absent"),
           "/api/2.0/serving-endpoints/chat": {"task": "llm/v1/chat", "state": {"ready": "READY"}},
           "/api/2.0/serving-endpoints/emb": {"task": "llm/v1/embeddings", "state": {"ready": "READY"}},
           "/api/2.0/serving-endpoints/boom": ConnectionError("réseau")})
    c = DatabricksChecker(w, Sql())
    assert c.warehouse("d0642494ed2912f0")[0] is True
    assert c.warehouse("0000000000000000")[0] is False
    assert c.warehouse("../../x") == (False, "Identifiant invalide.") and len(w.api_client.calls) == 2
    assert c.endpoint("chat")[0] is True and c.endpoint("emb")[0] is False
    with pytest.raises(ConnectionError):
        c.endpoint("boom")                                  # erreur technique : remontée, pas un échec
    sql = Sql()
    assert DatabricksChecker(w, sql).schema("dataops_dev.saas_t_alpha") == (True, "accessible")
    assert sql.calls == [("DESCRIBE SCHEMA IDENTIFIER(:s)", {"s": "dataops_dev.saas_t_alpha"})]
    assert DatabricksChecker(w, Sql(RuntimeError("[SCHEMA_NOT_FOUND] x"))).schema("a.b")[0] is False
