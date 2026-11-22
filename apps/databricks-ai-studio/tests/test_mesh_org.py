"""Agent Mesh par domaine : annuaire, recherche par capacité, carte, outils HakimAI (données du 22/11/2026)."""
import types

import pytest

from backend import hakim, mesh_org as M
from backend.agent_runtime import AgentConfig, ToolEvent, TurnResult
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, resolve_executor
from tools.hakim_tools import Platform

DOMS = ["Supply Chain", "PTE", "UDR", "Transverse"]
AG = [
    {"agent_id": "chef", "name": "Chef Analyse TER & Gares", "status": "publie", "tagline": "Coordonne régularité TER et gares"},
    {"agent_id": "rom", "name": "Romane", "status": "publie", "tagline": "Régularité des TER"},
    {"agent_id": "mar", "name": "Margot", "status": "publie", "tagline": "Carte des gares"},
    {"agent_id": "jul", "name": "Jules", "status": "publie", "tagline": "Chef qualité des données"},
    {"agent_id": "cla", "name": "Clara", "status": "publie", "tagline": "Anomalies et complétude des tables"},
    {"agent_id": "vic", "name": "Victor", "status": "publie", "tagline": "Veille fraîcheur des données"},
    {"agent_id": "hug", "name": "Hugo", "status": "publie", "tagline": "Fréquentation des gares"},
    {"agent_id": "gae", "name": "Gael", "status": "publie", "tagline": "Orchestrateur"},
    {"agent_id": "nin", "name": "Nina", "status": "en_validation"},
    {"agent_id": "pau", "name": "Paul", "status": "brouillon"},
]
TRANSVERSE = {"chef", "rom", "mar", "jul", "cla", "vic", "hug", "nin"}
CONTRACTS = {a: {"domaine": "Transverse", "perimetre": ""} for a in TRANSVERSE} | {"gae": {"domaine": ""}}
CONTRACTS["cla"]["perimetre"] = "Contrôle de complétude du schéma description_du_reseau_bronze"
TEAMS = [
    {"team_id": "ter", "name": "Analyse TER & Gares", "handle": "analyse_ter", "status": "publie", "filiere": "Transverse",
     "mission": "Analyser la régularité des TER et les gares", "lead_agent_id": "chef", "members": ["rom", "mar"]},
    {"team_id": "qua", "name": "Qualité des données", "handle": "qualite", "status": "publie", "filiere": "Transverse",
     "mission": "Surveiller la qualité des données", "lead_agent_id": "jul", "members": ["cla", "vic"]},
    {"team_id": "pre", "name": "Prévision & Anticipation", "handle": "prevision", "status": "brouillon",
     "filiere": "Transverse", "mission": "", "lead_agent_id": "nin", "members": ["pau"]},
    {"team_id": "old", "name": "Ancienne", "handle": "old", "status": "archive", "filiere": "Transverse",
     "mission": "", "lead_agent_id": "hug", "members": ["gae"]},
]


def mesh(teams=TEAMS, contracts=CONTRACTS):
    return M.build_mesh(AG, teams, contracts, DOMS)


def test_directory_matches_real_state():
    m = mesh()
    s = {r["domaine"]: r for r in M.summary(m)}
    assert [r["domaine"] for r in M.summary(m)] == DOMS
    assert s["Transverse"] == {"domaine": "Transverse", "equipes": 2, "joignables": 2, "agents_publies": 7, "en_preparation": 1}
    assert all(s[d]["equipes"] == 0 and s[d]["agents_publies"] == 0 for d in ("Supply Chain", "PTE", "UDR"))
    assert m["sans_domaine"] == ["Gael"]
    assert m["hors_equipe"] == ["Gael", "Hugo"]          # l'équipe archivée ne compte pas
    assert m["incoherences"] == [] and m["equipes_hors_domaine"] == []
    qua = M.find_team(m, "Qualité des données")
    assert qua["chef"]["nom"] == "Jules" and [x["nom"] for x in qua["membres"]] == ["Clara", "Victor"]
    assert qua["destinataire"] == "jul" and qua["joignable"]


def test_several_teams_per_domain_and_agent_in_several_teams():
    extra = TEAMS + [{"team_id": "x", "name": "Gares", "handle": "gares", "status": "publie", "filiere": "Transverse",
                      "mission": "Gares", "lead_agent_id": "hug", "members": ["mar"]}]
    m = mesh(extra)
    assert len(m["domaines"][3]["equipes"]) == 3
    assert sorted(m["equipes_par_agent"]["mar"]) == ["Analyse TER & Gares", "Gares"]
    assert "Hugo" not in m["hors_equipe"]


def test_domain_mismatch_and_unpublished_lead_are_flagged():
    contracts = dict(CONTRACTS) | {"vic": {"domaine": "UDR"}}
    teams = [dict(TEAMS[1], lead_agent_id="nin")]
    m = mesh(teams, contracts)
    assert m["incoherences"] == [{"agent_id": "vic", "agent": "Victor", "equipe": "Qualité des données",
                                  "domaine_equipe": "Transverse", "domaine_agent": "UDR"}]
    assert not M.find_team(m, "qualite")["joignable"]       # chef en validation : non joignable


def test_find_team_by_name_handle_or_id_and_unknown():
    m = mesh()
    assert M.find_team(m, "@qualite")["team_id"] == "qua"
    assert M.find_team(m, "équipe QUALITE DES DONNEES")["team_id"] == "qua"
    assert M.find_team(m, "ter")["equipe"] == "Analyse TER & Gares"
    assert M.find_team(m, "prevision") is None               # brouillon : absent du mesh


def test_search_by_capability_recommends_team_with_reason():
    m = mesh()
    r = M.search(m, AG, CONTRACTS, "anomalies de complétude sur description_du_reseau_bronze")
    assert r["equipe_recommandee"] == "Qualité des données" and r["a_departager"] == []
    assert r["agents"][0]["agent"] == "Clara" and "description_du_reseau_bronze" in r["agents"][0]["motif"]
    r = M.search(m, AG, CONTRACTS, "régularité des TER")
    assert r["equipe_recommandee"] == "Analyse TER & Gares" and "regularite" in r["equipes"][0]["motif"]
    hugo = next(a for a in M.search(m, AG, CONTRACTS, "fréquentation")["agents"] if a["agent"] == "Hugo")
    assert hugo["equipes"] == [] and not hugo["joignable_par_hakim"]


def test_search_tie_empty_query_and_empty_domain():
    m = mesh()
    tie = M.search(m, AG, CONTRACTS, "données gares")          # 1 mot dans chaque mission
    assert tie["equipe_recommandee"] is None and tie["a_departager"] == ["Analyse TER & Gares", "Qualité des données"]
    allt = M.search(m, AG, CONTRACTS, "", "Transverse")
    assert len(allt["equipes"]) == 2 and allt["equipe_recommandee"] is None
    assert M.search(m, AG, CONTRACTS, "anomalies", "Supply Chain") | {} == {
        "mots_recherches": ["anomalies"], "domaine": "Supply Chain", "equipes": [], "agents": [],
        "equipe_recommandee": None, "a_departager": []}


def test_mesh_dot_structure_and_escaping():
    teams = [dict(TEAMS[1], name='Qualité "données"')]
    dot = M.mesh_dot(mesh(teams))
    assert dot.startswith("digraph G {") and dot.endswith("}")
    assert dot.count("org -> d") == 4 and '"Supply Chain\\naucune équipe"' in dot
    assert 'Qualité \\"données\\"\\nchef : Jules' in dot
    assert dot.count("-> a_") == 2                        # Clara, Victor


def test_order_domains():
    assert M.order_domains(["UDR", "Transverse", "PTE", "Supply Chain"]) == DOMS
    assert M.order_domains([]) == DOMS and M.order_domains(["Zeta", "PTE"]) == ["PTE", "Zeta"]


# --- Outils HakimAI ------------------------------------------------------------------------------------
class Sql:
    def query(self, statement, params=None, row_limit=None):
        assert "t.domains" in statement
        return {"rows": [{"name": d} for d in DOMS]}


class Runtime:
    def __init__(self, pending=None):
        self.pending, self.calls = pending, []

    def run(self, cfg, history):
        self.calls.append((cfg, history))
        ev = ToolEvent("c1", "ask_agent", {"agent": "Clara", "question": "q"}, "succes",
                       {"agent": "Clara", "agent_affiche": "Clara, la contrôleuse", "reponse": "3 anomalies"})
        return TurnResult([], [], [ev], final_text="Synthèse : 3 anomalies (Clara).", pending=self.pending, latency_ms=42)


def ctx(runner=True, pending=None):
    rt = Runtime(pending)
    seen = []

    def team_runner(cfg):
        seen.append(cfg)
        return rt, cfg, []

    repo = types.SimpleNamespace(list_agents=lambda: AG, sql=Sql(), s=types.SimpleNamespace(table=lambda n: f"t.{n}"),
                                 get_config=lambda aid, v=None: AgentConfig(aid, 1, "Jules", "m", "Chef", ["agent:cla"]))
    teams = types.SimpleNamespace(list_teams=lambda: TEAMS)
    p = Platform(repo, teams, "u@sncf.fr", False, {}, contracts=lambda: CONTRACTS,
                 team_runner=team_runner if runner else None)
    return ToolContext(sql=None, workspace=None, user_email="u@sncf.fr", platform=p), rt, seen


REG = ToolRegistry(hakim.TOOLS)


def run(c, tid, **a):
    return REG.run(REG.specs[tid], c, a)


def test_mesh_tools_registered_read_only():
    for tid in ("trouver_agents", "demander_a_equipe"):
        spec = REG.specs[tid]
        assert spec.read_only and not spec.requires_confirmation
        assert callable(resolve_executor(spec.executor))
    assert {"trouver_agents", "demander_a_equipe"} <= set(hakim.config("m").tool_ids)
    assert "demander_a_equipe" in hakim.INSTRUCTIONS and "a_departager" in hakim.INSTRUCTIONS


def test_trouver_agents_tool():
    c, _, _ = ctx()
    r = run(c, "trouver_agents", capacite="complétude description_du_reseau_bronze", domaine="transverse")
    assert r["equipe_recommandee"] == "Qualité des données"
    assert r["agents_hors_equipe"] == ["Gael", "Hugo"] and r["agents_sans_domaine"] == ["Gael"]
    assert [d["domaine"] for d in r["domaines"]] == DOMS
    with pytest.raises(ToolError, match="Domaine inconnu"):
        run(c, "trouver_agents", domaine="Marketing")


def test_demander_a_equipe_routes_to_lead_and_reports_route():
    c, rt, seen = ctx()
    r = run(c, "demander_a_equipe", equipe="@qualite", question="Anomalies de complétude ?")
    assert seen[0].agent_id == "jul" and rt.calls[0][1] == [{"role": "user", "content": "Anomalies de complétude ?"}]
    assert r["statut"] == "succes" and r["reponse"].startswith("Synthèse")
    assert r["acheminement"] == "HakimAI → Transverse → Qualité des données → Jules (chef) → Clara, la contrôleuse"
    assert r["_ui_mesh"]["events"][0]["tool_id"] == "ask_agent"


def test_demander_a_equipe_pending_is_not_executed():
    c, _, _ = ctx(pending={"tool": "creer_ticket", "arguments": {}})
    r = run(c, "demander_a_equipe", equipe="qualite", question="Crée un ticket")
    assert r["statut"] == "validation_requise" and "Chat & Test" in r["message"] and "reponse" not in r


def test_demander_a_equipe_refusals():
    c, rt, _ = ctx()
    with pytest.raises(ToolError, match="introuvable.*Analyse TER & Gares \\(Transverse\\)"):
        run(c, "demander_a_equipe", equipe="Prévision & Anticipation", question="q")   # brouillon
    with pytest.raises(ToolError, match="Question vide"):
        run(c, "demander_a_equipe", equipe="qualite", question="  ")
    c2, _, _ = ctx(runner=False)
    with pytest.raises(ToolError, match="page HakimAI"):
        run(c2, "demander_a_equipe", equipe="qualite", question="q")
    assert rt.calls == []
