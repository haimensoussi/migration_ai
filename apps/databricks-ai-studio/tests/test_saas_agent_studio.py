"""Agent Studio : versions, publication, droits, isolation, actions autorisées et exécution journalisée."""
import itertools
import json

import pytest

from backend.saas.agent_studio import SAAS_TOOLS, AgentStudio
from backend.saas.models import DEFAULT_ROLES, AccessDenied, Identity, Role, ValidationError
from backend.saas.setup_wizard import DATA_STEPS, SetupWizard
from backend.saas.store import MemoryStore
from backend.saas.tenant_service import TenantService
from backend.tool_registry import ToolContext, ToolSpec

PLATFORM = Identity("plateforme@discovery.io", "test")
ALICE = Identity("alice@alpha.com", "test")
BOB = Identity("bob@beta.com", "test")
MODEL = "databricks-claude-sonnet-4-6"

SETUP = {
    "organisation": {"display_name": "X" * 3, "contact_email": "dpo@alpha.com", "language": "fr", "timezone": "UTC"},
    "infrastructure": {"warehouse_id": "d0642494ed2912f0", "max_rows": 200, "sql_timeout_s": 120},
    "ia": {"default_endpoint": MODEL, "allowed_endpoints": [], "temperature": 0.2, "max_tokens": 4096},
    "securite": {"default_member_role": "user", "allowed_domains": "alpha.com, beta.com", "write_approval": True},
    "modules": {"agent_studio": True},
}
Q = {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}
SPECS = [ToolSpec("execute_sql", "SQL", "SQL", "Requête", Q, {}, "tools.sql_tools:execute_sql"),
         ToolSpec("render_kpi", "KPI", "Visualisation", "KPI", {"type": "object", "properties": {}}, {},
                  "tools.report_tools:render_kpi"),
         ToolSpec("list_tables", "Tables", "UC", "Liste", {"type": "object", "properties": {}}, {},
                  "tools.uc_tools:list_tables"),
         ToolSpec("flux_smart_office_envoyer", "Flux", "Flux", "Flux", {"type": "object", "properties": {}}, {},
                  "tools.flow_tools:call_flow", requires_confirmation=True, read_only=False)]


class Checker:
    def warehouse(self, _):
        return True, "ok"

    endpoint = schema = warehouse


class FakeModel:
    """Réponses programmées ; mémorise les appels (endpoint, outils proposés)."""
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, endpoint, messages, tools=None, temperature=None):
        self.calls.append({"endpoint": endpoint, "tools": [t["function"]["name"] for t in tools or []],
                           "system": messages[0]["content"]})
        return self.replies.pop(0)


def text(t):
    return {"message": {"role": "assistant", "content": t}, "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def tool_call(name, args):
    return {"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "usage": {"prompt_tokens": 50, "completion_tokens": 5}}


class Sql:
    def __init__(self):
        self.statements = []

    def query(self, statement, params=None, row_limit=None):
        self.statements.append(statement)
        return {"columns": ["n"], "rows": [{"n": "3"}], "truncated": False}


@pytest.fixture
def env():
    store = MemoryStore({k: Role(k, k, r, frozenset(p)) for k, (r, p) in DEFAULT_ROLES.items()})
    svc = TenantService(store, [PLATFORM.email])
    a = svc.create_tenant(PLATFORM, "Alpha SA", "alpha", ALICE.email)
    b = svc.create_tenant(PLATFORM, "Beta SAS", "beta", BOB.email)
    clock = (f"2026-11-18T10:{i // 60:02d}:{i % 60:02d}+00:00" for i in itertools.count())
    wiz = SetupWizard(svc, now=lambda: next(clock))
    ca, cb = svc.resolve(ALICE, a.tenant_id), svc.resolve(BOB, b.tenant_id)
    for ctx in (ca, cb):
        for step in DATA_STEPS:
            wiz.save_step(ctx, step, SETUP[step])
        wiz.activate(ctx, Checker())
    return svc, store, AgentStudio(svc, lambda: SPECS), ca, cb


def form(**kw):
    return {"name": "Analyste", "description": "Agent d'analyse", "instructions": "Tu es un analyste rigoureux et concis.",
            "model_endpoint": MODEL, "tool_ids": ["render_kpi"], "min_role": "user"} | kw


def tctx():
    return ToolContext(sql=Sql(), workspace=None, app_sql="SP", platform="PLATEFORME")


# -- Prérequis et validation ------------------------------------------------------------------------
def test_requires_activated_org_and_module(env):
    svc, store, studio, ca, cb = env
    del store.settings_[(ca.tenant_id, "setup.status")]
    with pytest.raises(ValidationError, match="non activée"):
        studio.save_draft(ca, None, form())
    store.settings_[(cb.tenant_id, "setup.modules")] = {"finops": True}
    with pytest.raises(ValidationError, match="Agent Studio désactivé"):
        studio.save_draft(cb, None, form())


def test_catalog_is_saas_whitelist(env):
    svc, store, studio, ca, cb = env
    cat = studio.tool_catalog(studio.org_setup(ca))
    assert set(cat) == {"execute_sql", "render_kpi"} and set(cat) <= set(SAAS_TOOLS)


@pytest.mark.parametrize("patch,msg", [
    ({"name": "A"}, "Nom"), ({"instructions": "court"}, "Instructions"),
    ({"model_endpoint": "autre-modele"}, "Modèle non autorisé"), ({"tool_ids": ["list_tables"]}, "non autorisées"),
    ({"tool_ids": ["flux_smart_office_envoyer"]}, "non autorisées"),
    ({"tool_ids": ["execute_sql"]}, "au moins une table"),
    ({"knowledge_tables": ["dataops_dev.saas_t_alpha.ventes"]}, "non provisionné"),
    ({"connector_ids": ["crm"]}, "Connecteurs inconnus"), ({"temperature": 2}, "Température"),
    ({"max_iterations": 50}, "itérations"), ({"min_role": "dieu"}, "Rôle minimal")])
def test_validation(env, patch, msg):
    svc, store, studio, ca, cb = env
    with pytest.raises(ValidationError, match=msg):
        studio.save_draft(ca, None, form(**patch))
    assert store.agent_versions(ca.tenant_id) == []


def test_knowledge_tables_confined_to_tenant_schema(env):
    svc, store, studio, ca, cb = env
    svc.mark_schema_provisioned(PLATFORM, ca.tenant_id)
    for t in ("dataops_dev.saas_t_beta.ventes", "dataops_dev.ai_studio.data_gares_de_voyageurs",
              "dataops_dev.saas_t_alpha.a.b", "dataops_dev.saas_t_alpha", "dataops_dev.saas_t_alphabis.x"):
        with pytest.raises(ValidationError, match="hors du schéma"):
            studio.save_draft(ca, None, form(tool_ids=["execute_sql"], knowledge_tables=[t]))
    a = studio.save_draft(ca, None, form(tool_ids=["execute_sql"], knowledge_tables="DataOps_Dev.saas_t_alpha.Ventes"))
    assert a["config"]["knowledge_tables"] == ["dataops_dev.saas_t_alpha.ventes"]


# -- Versions et publication -------------------------------------------------------------------------
def test_versioning_and_publication(env):
    svc, store, studio, ca, cb = env
    a = studio.save_draft(ca, None, form())
    aid = a["agent_id"]
    assert a["version"] == 1
    assert studio.save_draft(ca, aid, form(description="v1 corrigée"))["version"] == 1   # brouillon mis à jour
    studio.publish(ca, aid, 1)
    assert studio.save_draft(ca, aid, form(name="Analyste 2"))["version"] == 2           # publiée jamais modifiée
    v = {x["version"]: x for x in studio.versions(ca, aid)}
    assert (v[1]["status"], v[1]["name"], v[1]["config"]["description"]) == ("publie", "Analyste", "v1 corrigée")
    assert v[2]["status"] == "brouillon"
    studio.publish(ca, aid, 2)
    assert [x["status"] for x in studio.versions(ca, aid)] == ["archive", "publie"]
    item = studio.list_agents(ca)[0]
    assert (item["name"], item["published"]["version"], item["versions"]) == ("Analyste 2", 2, 2)
    studio.archive(ca, aid)
    assert [x["status"] for x in studio.versions(ca, aid)] == ["archive", "archive"]
    assert {x["action"] for x in svc.audit_log(ca)} >= {"agents.save", "agents.publish", "agents.archive"}


def test_publish_revalidates_against_current_setup(env):
    svc, store, studio, ca, cb = env
    aid = studio.save_draft(ca, None, form())["agent_id"]
    store.settings_[(ca.tenant_id, "setup.ia")] = SETUP["ia"] | {"default_endpoint": "autre", "allowed_endpoints": ["autre"]}
    with pytest.raises(ValidationError, match="Modèle non autorisé"):
        studio.publish(ca, aid, 1)


# -- Droits et isolation -----------------------------------------------------------------------------
def test_roles(env):
    svc, store, studio, ca, cb = env
    for email, role in (("builder@alpha.com", "builder"), ("user@alpha.com", "user"), ("viewer@alpha.com", "viewer")):
        svc.add_member(ca, email, role)
    builder, user, viewer = (svc.resolve(Identity(e, "test"), ca.tenant_id)
                             for e in ("builder@alpha.com", "user@alpha.com", "viewer@alpha.com"))
    aid = studio.save_draft(builder, None, form())["agent_id"]
    restricted = studio.save_draft(builder, None, form(name="Réservé", min_role="builder"))["agent_id"]
    with pytest.raises(AccessDenied):
        studio.save_draft(user, None, form())
    assert studio.list_agents(user) == []                         # brouillons invisibles
    studio.publish(builder, aid, 1)
    studio.publish(builder, restricted, 1)
    assert [a["name"] for a in studio.list_agents(user)] == ["Analyste"]   # rôle minimal respecté
    assert studio.list_agents(viewer) == []                       # lecteur : pas agents.use
    with pytest.raises(AccessDenied):
        studio.runtime_config(user, restricted)
    with pytest.raises(AccessDenied):
        studio.runtime_config(viewer, aid)
    studio.save_draft(builder, aid, form(name="v2"))
    with pytest.raises(AccessDenied):
        studio.runtime_config(user, aid, 2)                       # test d'un brouillon : concepteurs seulement
    assert studio.runtime_config(user, aid)[1].version == 1


def test_cross_tenant_isolation(env):
    svc, store, studio, ca, cb = env
    aid = studio.save_draft(ca, None, form())["agent_id"]
    studio.publish(ca, aid, 1)
    assert studio.list_agents(cb) == []
    for call in (lambda: studio.versions(cb, aid), lambda: studio.runtime_config(cb, aid),
                 lambda: studio.publish(cb, aid, 1), lambda: studio.save_draft(cb, aid, form())):
        with pytest.raises(ValidationError):
            call()
    studio.archive(cb, aid)                                       # sans effet sur Alpha
    assert store.agent_versions(ca.tenant_id, aid)[0]["status"] == "publie"
    with pytest.raises(ValidationError):
        studio.versions(ca, "agt_' OR 1=1")


# -- Exécution -----------------------------------------------------------------------------------
def test_run_turn_logs_execution_and_usage(env):
    svc, store, studio, ca, cb = env
    aid = studio.save_draft(ca, None, form())["agent_id"]
    model = FakeModel([text("Bonjour")])
    res = studio.run_turn(ca, aid, 1, [{"role": "user", "content": "Salut"}], model, tctx())
    assert res.final_text == "Bonjour"
    assert model.calls[0]["endpoint"] == MODEL and model.calls[0]["tools"] == ["render_kpi"]
    ex = store.executions[-1]
    assert (ex["tenant_id"], ex["ref_id"], ex["status"], ex["details"]["mode"]) == (ca.tenant_id, f"{aid}:v1", "succes", "test")
    assert sorted((u["metric"], u["quantity"]) for u in store.usage) == [("tokens_entree", 100), ("tokens_sortie", 20)]


def test_unlisted_tool_call_refused_and_sql_confined(env):
    svc, store, studio, ca, cb = env
    svc.mark_schema_provisioned(PLATFORM, ca.tenant_id)
    aid = studio.save_draft(ca, None, form(tool_ids=["execute_sql"],
                                           knowledge_tables=["dataops_dev.saas_t_alpha.ventes"]))["agent_id"]
    ctx_tools = tctx()
    model = FakeModel([tool_call("flux_smart_office_envoyer", {}),
                       tool_call("execute_sql", {"query": "SELECT * FROM dataops_dev.saas_t_beta.ventes"}),
                       tool_call("execute_sql", {"query": "SELECT count(*) n FROM dataops_dev.saas_t_alpha.ventes"}),
                       text("3 ventes")])
    res = studio.run_turn(ca, aid, 1, [{"role": "user", "content": "Combien ?"}], model, ctx_tools)
    statuses = [(e.tool_id, e.status) for e in res.events]
    assert statuses == [("flux_smart_office_envoyer", "erreur"), ("execute_sql", "erreur"), ("execute_sql", "succes")]
    assert "non autorisé" in res.events[0].error and "saas_t_beta" in res.events[1].error
    assert ctx_tools.sql.statements == ["SELECT count(*) n FROM dataops_dev.saas_t_alpha.ventes"]
    assert res.final_text == "3 ventes"


def test_run_turn_strips_platform_resources_and_logs_errors(env):
    svc, store, studio, ca, cb = env
    aid = studio.save_draft(ca, None, form())["agent_id"]
    seen = {}

    class Spy(FakeModel):
        def chat(self, *a, **kw):
            raise RuntimeError("endpoint indisponible")

    import backend.saas.agent_studio as mod
    orig = mod.AgentRuntime

    class Capture(orig):
        def __init__(self, model, registry, ctx, **kw):
            seen["ctx"] = ctx
            super().__init__(model, registry, ctx, **kw)

    mod.AgentRuntime = Capture
    try:
        with pytest.raises(RuntimeError):
            studio.run_turn(ca, aid, 1, [{"role": "user", "content": "x"}], Spy([]), tctx())
    finally:
        mod.AgentRuntime = orig
    assert seen["ctx"].app_sql is None and seen["ctx"].platform is None and seen["ctx"].user_email == ALICE.email
    assert store.executions[-1]["status"] == "erreur" and "indisponible" in store.executions[-1]["error"]
