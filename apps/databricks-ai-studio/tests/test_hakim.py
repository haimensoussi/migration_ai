import types

import pytest

from backend import hakim
from backend.agent_runtime import AgentConfig, ToolEvent
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, resolve_executor
from tools.hakim_tools import Platform

AG = [
    {"agent_id": "m", "name": "Margot", "handle": "margot", "status": "publie", "owner": "a@sncf.fr", "persona": "la cartographe"},
    {"agent_id": "s", "name": "Sam", "handle": "sam", "status": "brouillon", "owner": "a@sncf.fr"},
    {"agent_id": "x", "name": "Vieux", "handle": "vieux", "status": "archive", "owner": "a@sncf.fr"},
]


class Sql:
    def __init__(self, rows):
        self.rows, self.seen = rows, []

    def query(self, statement, params=None, row_limit=None):
        self.seen.append((statement, params))
        return {"rows": [dict(r) for r in self.rows], "columns": [], "truncated": False}


def ctx(user="b@sncf.fr", admin=False, rows=()):
    sql = Sql(rows)
    repo = types.SimpleNamespace(list_agents=lambda: AG, sql=sql, s=types.SimpleNamespace(table=lambda n: f"t.{n}"),
                                 get_config=lambda aid, v=None: AgentConfig(aid, v or 2, "Margot", "m", f"Instr v{v or 2}",
                                                                            ["execute_sql"] + (["render_map"] if (v or 2) == 2 else [])),
                                 list_tools=lambda: [])
    teams = types.SimpleNamespace(list_teams=lambda: [])
    return ToolContext(sql=None, workspace=None, user_email=user, platform=Platform(repo, teams, user, admin, {"page": "Équipes"})), sql


REG = ToolRegistry(hakim.TOOLS)


def run(c, tid, **a):
    return REG.run(REG.specs[tid], c, a)


def test_lot1_is_read_only_and_executors_resolve():
    assert len(hakim.TOOLS) == 12
    for t in hakim.TOOLS:
        assert t.read_only and not t.requires_confirmation and t.executor.startswith("tools.hakim_tools:")
        resolve_executor(t.executor)
    cfg = hakim.config("mod")
    assert cfg.agent_id == "hakimai" and set(cfg.tool_ids) == set(REG.specs) and "ne crées, ne modifies" in cfg.instructions


def test_visibility_of_agents():
    c, _ = ctx()
    assert [a["nom"] for a in run(c, "lister_agents")["agents"]] == ["Margot"]
    with pytest.raises(ToolError, match="non visible"):
        run(c, "decrire_agent", agent="@sam")
    owner, _ = ctx("a@sncf.fr")
    assert [a["nom"] for a in run(owner, "lister_agents")["agents"]] == ["Margot", "Sam"]   # archivé jamais listé
    adm, _ = ctx("z@sncf.fr", admin=True)
    assert run(adm, "decrire_agent", agent="Sam")["nom"] == "Sam"


def test_failure_details_hidden_from_other_users():
    rows = [{"agent_id": "m", "tool_id": "execute_sql", "status": "erreur", "error": "secret de a", "arguments": "{q}",
             "user_name": "a@sncf.fr", "created_at": "2026-11-15"}]
    c, sql = ctx("b@sncf.fr", rows=rows)
    r = run(c, "diagnostiquer_echec")
    assert r["details_masques"] == 1 and "secret" not in str(r) and r["groupes"][0]["exemple_arguments"] is None
    assert all(":a0" in s for s, _ in sql.seen)                      # identifiants d'agents passés en paramètres
    owner, _ = ctx("a@sncf.fr", rows=rows)
    assert run(owner, "diagnostiquer_echec")["groupes"][0]["message"] == "secret de a"


def test_navigation_compare_and_guards():
    c, _ = ctx()
    r = run(c, "ouvrir_page", page="equipes", raison="créer une équipe")
    ev = ToolEvent("1", "ouvrir_page", {}, "succes", r)
    assert hakim.navigation_targets([ev, ev]) == [{"path": "views/equipes.py", "title": "Équipes", "reason": "créer une équipe"}]
    with pytest.raises(ToolError):
        run(c, "ouvrir_page", page="../app.py")
    d = run(c, "comparer_versions", agent="margot")
    assert d["versions"] == [1, 2] and d["outils_ajoutes"] == ["render_map"] and d["instructions_modifiees"]
    with pytest.raises(ToolError, match="Nom invalide"):
        run(c, "explorer_donnees", action="apercu", table="a.b.c; DROP TABLE d")
    with pytest.raises(ToolError, match="réservé à HakimAI"):
        REG.run(REG.specs["lister_agents"], ToolContext(sql=None, workspace=None), {})


def test_kill_switch_and_turn_cap(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_HAKIM_ENABLED", "false")
    assert not hakim.enabled()
    monkeypatch.setenv("AI_STUDIO_HAKIM_ENABLED", "true")
    monkeypatch.setenv("AI_STUDIO_HAKIM_MAX_TURNS", "abc")
    assert hakim.enabled() and hakim.max_turns() == 30
