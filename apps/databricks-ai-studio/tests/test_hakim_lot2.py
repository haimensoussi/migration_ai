import types

import pytest

from backend import hakim
from backend.agent_runtime import AgentConfig
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.hakim_tools import Platform

ME, OTHER = "a@sncf.fr", "b@sncf.fr"
REG = ToolRegistry(hakim.TOOLS)
WRITES = {"creer_agent", "modifier_agent", "creer_outil", "tester_appel_http", "creer_equipe", "modifier_equipe",
          "soumettre_publication",
          "archiver", "eia_cycle", "eia_preparer_mission", "eia_suivi_mission",
          "eia_team_builder_enregistrer", "eia_team_builder_decision"}


class Sql:
    def __init__(self):
        self.done = []

    def execute(self, statement, params=None):
        self.done.append((statement, params))

    def audits(self):
        return [p for s, p in self.done if "copilot_actions" in s]


class Repo:
    def __init__(self):
        self.sql, self.s = Sql(), types.SimpleNamespace(table=lambda n: f"t.{n}")
        self.agents = [
            {"agent_id": "c", "name": "Clara", "handle": "clara", "status": "publie", "owner": ME},
            {"agent_id": "d", "name": "Dora", "handle": "dora", "status": "brouillon", "owner": ME},
            {"agent_id": "o", "name": "Otto", "handle": "otto", "status": "brouillon", "owner": OTHER}]
        self.created, self.versions, self.status = [], [], {}

    def list_agents(self):
        return self.agents

    def list_tools(self):
        return [types.SimpleNamespace(tool_id="execute_sql", status="publie", name="SQL", owner="")]

    def get_config(self, aid, v=None):
        return AgentConfig(aid, 1, "x", "mod", "Instructions actuelles", ["execute_sql"], [])

    def create_agent(self, meta, cfg, user, status="brouillon"):
        self.created.append((meta, cfg, user, status))
        return "new"

    def save_version(self, aid, meta, cfg, user, status=None):
        self.versions.append((aid, cfg, status))
        return 2

    def set_status(self, aid, status):
        self.status[aid] = status


class Designer:
    def design(self, request):
        return types.SimpleNamespace(draft={"name": "Nina", "handle": "nina", "persona": "la synthétiseuse", "tagline": "",
                                            "category": "Qualité", "description": "", "icon": "smart_toy",
                                            "call_examples": [], "model_endpoint": "mod",
                                            "instructions": "Résume les anomalies par dimension DAMA.",
                                            "tool_ids": ["execute_sql"], "knowledge_tables": [], "temperature": 0.1,
                                            "max_iterations": 6}, warnings=[], hypotheses=[], test_questions=[])


def ctx(user=ME, admin=False):
    repo = Repo()
    teams = types.SimpleNamespace(list_teams=lambda: [], is_admin=lambda u: admin)
    plat = Platform(repo, teams, user, admin, {}, conv="conv1", designer=Designer)
    return ToolContext(sql=None, workspace=None, user_email=user, platform=plat), repo


def run(c, tid, **a):
    return REG.run(REG.specs[tid], c, a)


# Exception explicite : écritures dans le plan de transformation de l'utilisateur, sans fiche ; tout y reste
# « propose » jusqu'à sa décision sur la page Transformation (aucun agent, outil ou équipe n'est touché).
PLAN_WRITES = {"transformation_creer_plan", "transformation_cadrage", "transformation_decouvrir",
               "transformation_proposer", "transformation_feuille_route", "transformation_relier",
               "hakim_plan_travail"}   # plan de travail : annonce des étapes, tracée, sans fiche


def test_writes_need_confirmation_and_design_does_not():
    for t in hakim.TOOLS:
        assert t.requires_confirmation == (t.tool_id in WRITES), t.tool_id
        assert t.read_only == (t.tool_id not in WRITES | PLAN_WRITES), t.tool_id
    assert all(t.executor.startswith("tools.hakim_transformation_tools:") for t in hakim.TOOLS
               if t.tool_id in PLAN_WRITES)
    assert "publier" not in " ".join(t.tool_id for t in hakim.TOOLS if t.tool_id != "soumettre_publication")


def test_design_then_create_draft_only_and_audited():
    c, repo = ctx()
    d = run(c, "concevoir_agent", demande="résumer les anomalies")
    assert d["brouillon_id"] == "A1" and repo.created == []                  # conception : rien n'est écrit
    r = run(c, "creer_agent", brouillon_id="A1", nom_appel="@nina2")
    meta, cfg, user, status = repo.created[0]
    assert status == "brouillon" and user == ME and meta["handle"] == "nina2" and cfg["tool_ids"] == ["execute_sql"]
    a = repo.sql.audits()[-1]
    assert r["statut"] == "brouillon" and a["s"] == "succes" and a["t"] == "creer_agent" and a["u"] == ME and a["c"] == "conv1"
    lines = hakim.describe_action("creer_agent", {"brouillon_id": "A1"}, c.platform.drafts)
    assert "Nina" in lines[0] and "brouillon" in lines[0]


def test_unknown_draft_and_errors_are_audited():
    c, repo = ctx()
    with pytest.raises(ToolError, match="introuvable"):
        run(c, "creer_agent", brouillon_id="A9")
    assert repo.sql.audits()[-1]["s"] == "erreur"


def test_owner_rules_and_published_agents():
    c, repo = ctx()
    with pytest.raises(ToolError, match="non visible"):                      # brouillon d'un autre : invisible
        run(c, "modifier_agent", agent="otto", instructions="x" * 30)
    adm, _ = ctx("z@sncf.fr", admin=True)                                     # visible pour l'admin, mais pas à lui
    with pytest.raises(ToolError, match="propriétaire"):
        run(adm, "modifier_agent", agent="otto", instructions="x" * 30)
    with pytest.raises(ToolError, match="publié"):
        run(c, "modifier_agent", agent="clara", ajouter_outils=["execute_sql"])
    with pytest.raises(ToolError, match="non publiés"):
        run(c, "modifier_agent", agent="dora", ajouter_outils=["outil_fantome"])
    r = run(c, "modifier_agent", agent="dora", retirer_outils=["execute_sql"])
    assert r["outils"] == [] and repo.versions[-1][2] is None               # statut inchangé (brouillon)
    with pytest.raises(ToolError, match="propriétaire"):
        run(adm, "archiver", type_objet="agent", objet="otto")
    run(c, "archiver", type_objet="agent", objet="dora")
    assert repo.status == {"d": "archive"}


def test_publication_request_never_publishes():
    c, repo = ctx()
    with pytest.raises(ToolError, match="pas en brouillon"):
        run(c, "soumettre_publication", type_objet="agent", objet="clara")
    run(c, "soumettre_publication", type_objet="agent", objet="dora", message="prêt")
    st = [a["s"] for a in repo.sql.audits()]
    assert "en_attente" in st and repo.status == {} and not repo.versions and not repo.created
    with pytest.raises(ToolError, match="non visible"):
        run(ctx(OTHER)[0], "soumettre_publication", type_objet="agent", objet="dora")


def test_tool_creation_requires_successful_test():
    c, repo = ctx()
    c.platform.drafts["O1"] = {"kind": "outil", "draft": {"tool_id": "x"}}
    with pytest.raises(ToolError, match="Test réussi requis"):
        run(c, "creer_outil", brouillon_id="O1")
