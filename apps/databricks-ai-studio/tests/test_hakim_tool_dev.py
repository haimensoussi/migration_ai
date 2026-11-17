"""HakimAI : compétences de développement d'outils (fiche, test d'un outil existant, amélioration, cas de test)."""
import json
import types

import pytest

from backend import hakim
from backend import tool_builder as tb
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec
from tools.hakim_tools import Platform

ME, OTHER = "a@sncf.fr", "b@sncf.fr"
REG = ToolRegistry(hakim.TOOLS)
SQL = "SELECT `Nom` FROM dataops_dev.ai_studio.data_gares WHERE (:dep IS NULL OR `Departement` = :dep) ORDER BY `Nom`"


def draft(tool_id="gares_dep", sql=SQL):
    return tb.normalize({"tool_id": tool_id, "name": "Gares par département", "type": "sql_template",
                         "description": "Liste les gares d'un département ; renvoie la colonne Nom des gares.",
                         "sql": sql, "parameters": [{"name": "dep", "type": "string", "description": "Département",
                                                     "required": False, "example": "Rhône"}]})


class Sql:
    def __init__(self):
        self.done = []

    def execute(self, statement, params=None):
        self.done.append((statement, params))


class Repo:
    def __init__(self):
        self.sql, self.s = Sql(), types.SimpleNamespace(table=lambda n: f"t.{n}")
        mine = tb.build_spec(draft(), ME, status="brouillon", version="2")
        self.tools = [
            mine,
            tb.build_spec(draft("pub_tool"), ME, status="publie", version="1"),
            tb.build_spec(draft("autre_tool"), OTHER, status="brouillon", version="1"),
            ToolSpec("execute_sql", "SQL", "Données", "SQL en lecture", {"type": "object", "properties": {}},
                     {}, "tools.sql_tools:execute_sql"),
            ToolSpec("office_send", "Envoi", "Office", "Envoie", {"type": "object", "properties": {}}, {},
                     "tools.power_automate:office_send", read_only=False, requires_confirmation=True)]
        self.saved = []

    def list_tools(self):
        return self.tools

    def tool_versions(self, tid):
        return [{"version": 2, "note": "Créé", "created_by": ME, "created_at": "2026-11-16",
                 "test_result": json.dumps({"ok": False, "erreur": "colonne inconnue"})}]

    def save_custom_tool(self, spec, user, test, note=""):
        self.saved.append((spec, user, test, note))
        return 3


class ToolDesigner:
    seen = {}

    def improve(self, current, request="", test_result=None):
        ToolDesigner.seen = {"current": current, "request": request, "test": test_result}
        d = draft(current["tool_id"], SQL.replace("ORDER BY `Nom`", "ORDER BY `Nom` DESC"))
        return types.SimpleNamespace(draft=d, check=tb.Check(), hypotheses=[], changes=["Tri décroissant"],
                                     unsupported="")


def ctx(user=ME, admin=False):
    repo = Repo()
    teams = types.SimpleNamespace(list_teams=lambda: [])
    plat = Platform(repo, teams, user, admin, {}, conv="c1", tool_designer=ToolDesigner)
    return ToolContext(sql=None, workspace=None, user_email=user, platform=plat), repo


def run(c, tid, **a):
    return REG.run(REG.specs[tid], c, a)


@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def rt(spec, args, c):
        calls.append((spec.tool_id, args))
        ok = args.get("dep") != "KO"
        return {"ok": ok, "arguments": args, **({} if ok else {"erreur": "échec"})}
    monkeypatch.setattr(tb, "run_test", rt)
    return calls


def test_new_tools_are_reads_without_confirmation():
    for t in ("decrire_outil", "tester_outil", "ameliorer_outil", "verifier_outil"):
        s = REG.specs[t]
        assert s.read_only and not s.requires_confirmation, t
    assert "cas_test" in REG.specs["verifier_outil"].input_schema["properties"]
    assert "developpement_outils" in REG.specs["aide_plateforme"].input_schema["properties"]["sujet"]["enum"]


def test_decrire_outil_visibility_and_versions():
    c, _ = ctx()
    r = run(c, "decrire_outil", outil="gares_dep")
    assert r["type"] == "sql_template" and r["modifiable_par_vous"] and "ORDER BY" in r["definition"]["sql"]
    assert r["versions"][0]["test_ok"] is False and "colonne" in r["versions"][0]["test_erreur"]
    assert run(c, "decrire_outil", outil="execute_sql")["type"] == "intégré"
    with pytest.raises(ToolError, match="non visible"):
        run(c, "decrire_outil", outil="autre_tool")                     # brouillon d'un autre utilisateur
    assert "versions" not in run(ctx(OTHER)[0], "decrire_outil", outil="pub_tool")  # publié : visible, sans historique


def test_tester_outil_read_only_and_cases(fake_run):
    c, repo = ctx()
    r = run(c, "tester_outil", outil="gares_dep")
    assert r["test"]["ok"] and fake_run[-1] == ("gares_dep", {"dep": "Rhône"})  # exemples par défaut
    r = run(c, "tester_outil", outil="gares_dep", cas_test=[{"dep": "Ain"}, {"dep": "KO"}])
    assert r["test"]["ok"] is False and r["test"]["cas_reussis"] == 1 and r["test"]["nombre_cas"] == 2
    with pytest.raises(ToolError, match="écrit ou envoie"):
        run(c, "tester_outil", outil="office_send")
    assert repo.saved == [] and repo.sql.done == []                     # aucun enregistrement


def test_verifier_requires_all_cases(fake_run):
    c, _ = ctx()
    c.platform.drafts["O1"] = {"kind": "outil", "draft": draft("nouvel_outil")}
    r = run(c, "verifier_outil", brouillon_id="O1", cas_test=[{"dep": "Ain"}, {"dep": "KO"}, {}])
    assert r["ok"] is False and len(fake_run) == 3
    with pytest.raises(ToolError, match="Test réussi requis"):
        run(c, "creer_outil", brouillon_id="O1")
    r = run(c, "verifier_outil", brouillon_id="O1", cas_test=[{"dep": "Ain"}, {}])
    assert r["ok"] and r["test"]["cas_reussis"] == 2
    lines = hakim.describe_action("creer_outil", {"brouillon_id": "O1"}, c.platform.drafts)
    assert "Enregistrer" in lines[0] and "Cas de test réussis : 2 / 2" in lines


def test_ameliorer_then_new_version(fake_run):
    c, repo = ctx()
    r = run(c, "ameliorer_outil", outil="gares_dep", demande="trier à l'envers")
    assert r["brouillon_id"] == "O1" and "sql" in r["differences"] and repo.saved == []
    assert ToolDesigner.seen["test"]["ok"] is False and ToolDesigner.seen["current"]["tool_id"] == "gares_dep"
    run(c, "verifier_outil", brouillon_id="O1")
    assert "Nouvelle version" in hakim.describe_action("creer_outil", {"brouillon_id": "O1"}, c.platform.drafts)[0]
    out = run(c, "creer_outil", brouillon_id="O1")
    spec, user, _, note = repo.saved[0]
    assert out["nouvelle_version"] and spec.status == "brouillon" and user == ME and "Modifié" in note


def test_ameliorer_refusals():
    c, _ = ctx()
    with pytest.raises(ToolError, match="publié"):
        run(c, "ameliorer_outil", outil="pub_tool")
    with pytest.raises(ToolError, match="intégré"):
        run(c, "ameliorer_outil", outil="execute_sql")
    adm, _ = ctx("z@sncf.fr", admin=True)
    with pytest.raises(ToolError, match="propriétaire"):
        run(adm, "ameliorer_outil", outil="gares_dep")


@pytest.mark.parametrize("lit,bad", [("'Côte d''Azur'", True), ("'Côte d\\'Azur'", False), ('"Côte d\'Azur"', False),
                                     ("''", False)])
def test_doubled_apostrophe_is_rejected(lit, bad):
    sql = f"SELECT `Nom` FROM dataops_dev.ai_studio.data_gares WHERE (:dep IS NULL OR `Departement` = :dep) " \
          f"AND coalesce(`Nom`, '') <> {lit} ORDER BY `Nom`"
    c = tb.check(draft(sql=sql), {}, ME)
    assert any("Apostrophe doublée" in e for e in c.errors) == bad


def test_designer_prompt_mentions_apostrophes():
    from backend.tool_designer import designer_prompt
    p = designer_prompt([])
    assert "Jamais ''" in p and "caractères spéciaux" in p


def test_creer_outil_refuses_published_target(fake_run):
    c, repo = ctx()
    c.platform.drafts["O1"] = {"kind": "outil", "draft": draft("pub_tool")}
    run(c, "verifier_outil", brouillon_id="O1")
    with pytest.raises(ToolError, match="publié"):
        run(c, "creer_outil", brouillon_id="O1")
    assert repo.saved == []
