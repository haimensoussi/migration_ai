"""Organigramme d'agents d'entreprise et déploiement en agents IA (EIA Factory). Sans SQL ni réseau."""
import types

import pytest

from backend import personas, teams as T
from backend.eia import agent_models as am, org_designer as od
from tests.test_eia_cycle import TODAY, USER
from tests.test_eia_factory import cands, discovery
from backend.eia import team_builder as tb


def org(**kw):
    return od.propose(discovery(), cands(), domain=kw.pop("domain", "Ventes"), owner=USER, **kw)


def test_long_domain_handles_are_readable_and_valid():
    o = org(domain="Marketing")
    e = o["equipes"][0]
    assert (e["handle"], e["chef_handle"]) == ("marketing", "chef-marketing")
    hs = {k: a["handle"] for k, a in o["agents"].items()}
    assert hs["ag02"] == "marketing-prevision" and hs["ag05"] == "marketing-progres" and hs["ag08"] == "marketing-gouv"
    allh = list(hs.values()) + [e["handle"], e["chef_handle"]]
    assert len(set(allh)) == len(allh) and all(len(h) <= 20 and personas.HANDLE.match(h) for h in allh)
    assert od._fit("Campaign results", 10) == "campaign" and od._fit("Ventes", 10) == "ventes"


class FakeAgents:
    def __init__(self, rows=()):
        self.rows, self.created = [dict(r) for r in rows], []
        self.s = types.SimpleNamespace(default_model="modele-test")

    def list_agents(self):
        return self.rows

    def create_agent(self, meta, cfg, user, status="brouillon"):
        assert status == "brouillon"
        aid = f"a{len(self.rows)}"
        self.rows.append({"agent_id": aid, "name": meta["name"], "handle": meta.get("handle"), "status": status,
                          "tool_ids": cfg["tool_ids"]})
        self.created.append((meta, cfg, user, status))
        return aid


class FakeTeams:
    def __init__(self, agents, rows=(), fail=False):
        self.a, self.rows, self.saved, self.fail = agents, [dict(r) for r in rows], [], fail

    def list_teams(self):
        return self.rows

    def create_lead(self, data, user):          # même nom d'appel que TeamRepository.create_lead
        t = T.normalize(data)
        return self.a.create_agent({"name": f"Chef {t['name']}", "handle": ("chef-" + t["handle"])[:20].rstrip("-_")},
                                   {"tool_ids": [T.AGENT_PREFIX + m for m in t["members"]]}, user)

    def save(self, data, user, note=""):
        if self.fail:
            raise RuntimeError("table teams indisponible")
        t = T.normalize(data)
        errs = T.validate(t, self.a.list_agents(), self.rows)
        assert errs == [], errs                  # règles réelles des équipes de la plateforme
        tid = f"t{len(self.rows)}"
        self.rows.append({**t, "team_id": tid})
        self.saved.append((t, user, note))
        return tid


# ---------------------------------------------------------------- proposition
def test_org_follows_data_domain_and_official_categories():
    o = org()
    [e] = o["equipes"]
    assert o["superviseur"] == "HAKIM" and o["filiere"] == "Transverse" and o["domaine"] == "Ventes"
    assert e["chef"]["categorie"] == "AG06" and e["chef_handle"] == "chef-" + e["handle"]
    cats = [o["agents"][k]["categorie"] for k in e["membres"]]
    assert cats == ["AG01", "AG01", "AG02", "AG03", "AG04", "AG05", "AG08"] and len(cats) <= T.MAX_MEMBERS
    a1, a2 = (o["agents"][k] for k in e["membres"][:2])
    assert a1["tables"] == ["dataops_dev.ai_studio.data_ventes"] and set(a1["kpis"]) == {"nb_ventes", "total_ventes_montant"}
    assert a2["tables"] == ["dataops_dev.ai_studio.data_plan"] and a2["nom"] == "Analyse Plan"
    assert set(o["agents"]["ag02"]["kpis"]) == {k["id"] for k in cands() if k["previsible"]}
    assert o["objets"] == ["dataops_dev.ai_studio.data_ventes", "dataops_dev.ai_studio.data_plan"]   # data_ref : aucun KPI
    assert [a["categorie"] for a in o["a_venir"]] == ["AG07"] and not o["a_venir"][0]["deployable"]
    assert [u["categorie"] for u in o["usine"]] == ["AG10", "AG09"]
    assert not ({"AG09", "AG10", "AG07"} & {a["categorie"] for a in o["agents"].values()})
    assert all(a["deployable"] and a["equipes"] == ["equipe-1"] for a in o["agents"].values())
    handles = [a["handle"] for a in o["agents"].values()] + [e["handle"], e["chef_handle"]]
    assert len(set(handles)) == len(handles) and all(personas.HANDLE.match(h) for h in handles)
    assert all(set(a["outils"]) <= set(od.TOOLS[a["categorie"]]) for a in o["agents"].values())
    assert any("à valider" in w for w in o["avertissements"])


def test_proposal_avoids_existing_handles_and_validates_inputs():
    o = org(taken=["ventes", "ventes-prevision", "chef-ventes-2"])
    e = o["equipes"][0]
    assert e["handle"] == "ventes-3" and e["chef_handle"] == "chef-ventes-3"     # chef-ventes-2 déjà pris
    assert o["agents"]["ag02"]["handle"] == "ventes-prevision-2"
    with pytest.raises(od.OrgError):
        org(domain="  ")
    with pytest.raises(od.OrgError):
        org(filiere="Marketing")
    with pytest.raises(od.OrgError):
        od.propose(discovery(), [], domain="Ventes")


def test_no_forecastable_kpi_means_no_predictive_agent():
    c = [{**k, "previsible": False} for k in cands()]
    o = od.propose(discovery(), c, domain="Ventes")
    assert "ag02" not in o["agents"] and any("pas d'agent Prévision" in w for w in o["avertissements"])


def big_discovery(n, links=()):
    tables = [{"table": f"dataops_dev.ai_studio.data_obj{i}", "lignes": 10, "colonnes": [
        {"nom": "d", "type": "date", "min": "2023-01-01", "max": "2026-10-01", "remplissage_pct": 100.0}]}
        for i in range(1, n + 1)]
    return {"tables": tables, "donnees_sensibles": [], "liens_probables": list(links)}


def test_large_domain_gets_sister_teams_with_shared_transverse_agents():
    links = [{"de": "dataops_dev.ai_studio.data_obj1.k", "vers": "dataops_dev.ai_studio.data_obj7.k"}]
    d = big_discovery(7, links)
    o = od.propose(d, tb.kpi_candidates(d, TODAY), domain="Infra")
    assert len(o["equipes"]) == 3 and any("équipes sœurs" in w for w in o["avertissements"])
    assert all(len(e["membres"]) <= T.MAX_MEMBERS for e in o["equipes"])
    assert o["agents"]["ag08"]["equipes"] == ["equipe-1", "equipe-2", "equipe-3"]        # partagé
    team_of = {o["agents"][k]["tables"][0]: e["cle"] for e in o["equipes"] for k in e["membres"] if k.startswith("ag01")}
    assert team_of["dataops_dev.ai_studio.data_obj1"] == team_of["dataops_dev.ai_studio.data_obj7"]   # objets liés
    assert len(team_of) == 7 and len({e["handle"] for e in o["equipes"]}) == 3


def test_dot_and_instructions():
    o = org()
    g = od.dot(o, selected=["ag01-1", "ag08"])
    assert g.startswith("digraph EIA {") and g.count("{") == g.count("}")
    assert "hakim -> equipe_1_chef;" in g and "equipe_1_chef -> ag01_1;" in g
    assert "equipe_1_chef -> ag03 [style=dashed];" in g and "à venir" in g and "EIA Factory" in g
    txt = od.instructions(o["agents"]["ag03"], {**o, "eia_team_id": "ventes_pilote"})
    assert all(gf in txt for gf in am.GUARDRAILS) and "team_id = ventes_pilote" in txt and "aucun seuil" in txt


# ---------------------------------------------------------------- déploiement
def test_deploy_creates_selected_agents_lead_and_team_as_drafts():
    o = org(filiere="Supply Chain")
    agents = FakeAgents([{"agent_id": "x", "name": "Clara", "handle": "clara", "status": "publie", "tool_ids": []}])
    teams = FakeTeams(agents)
    sel = ["ag01-1", "ag01-2", "ag02", "ag08"]
    r = od.deploy(o, sel, agents, teams, USER.upper())
    assert r["statut"] == "brouillon" and len(r["agents"]) == 5 and len(r["equipes"]) == 1     # 4 membres + chef
    assert all(st == "brouillon" and u == USER for _, _, u, st in agents.created)
    meta, cfg, _, _ = agents.created[0]
    assert meta["handle"] == o["agents"]["ag01-1"]["handle"] and meta["category"] == "Data Intelligence Agent"
    assert cfg["model_endpoint"] == "modele-test" and cfg["knowledge_tables"] == ["dataops_dev.ai_studio.data_ventes"]
    assert cfg["tool_ids"] == od.TOOLS["AG01"] and "à valider" in cfg["instructions"]
    [(t, user, note)] = teams.saved
    assert t["filiere"] == "Supply Chain" and t["human_owner"] == USER and t["status"] == "brouillon"
    assert len(t["members"]) == 4 and t["lead_agent_id"] and "Team Builder" in note
    lead = next(a for a in agents.rows if a["agent_id"] == t["lead_agent_id"])
    assert lead["handle"] == o["equipes"][0]["chef_handle"] and lead["tool_ids"] == ["agent:" + m for m in t["members"]]
    assert not any(m["category"] == "Strategic Intelligence Agent" for m, *_ in agents.created if "category" in m)


def test_deploy_refusals_happen_before_any_write():
    o = org()
    for user in ("", "agent:team_builder", "pas-un-email"):
        a = FakeAgents()
        with pytest.raises(od.OrgError):
            od.deploy(o, ["ag08"], a, FakeTeams(a), user)
        assert a.created == []
    a = FakeAgents()
    for sel in ([], ["ag07"], ["inconnu"]):
        with pytest.raises(od.OrgError):
            od.deploy(o, sel, a, FakeTeams(a), USER)
    a = FakeAgents([{"agent_id": "x", "name": "X", "handle": o["agents"]["ag08"]["handle"], "status": "brouillon"}])
    with pytest.raises(od.OrgError, match="déjà utilisés"):
        od.deploy(o, ["ag08"], a, FakeTeams(a), USER)
    a = FakeAgents()
    with pytest.raises(od.OrgError, match="déjà utilisés"):
        od.deploy(o, ["ag08"], a, FakeTeams(a, [{"team_id": "t", "name": "V", "handle": o["equipes"][0]["handle"],
                                                  "status": "publie"}]), USER)
    assert a.created == []


def test_partial_failure_is_reported_not_hidden():
    o = org()
    a = FakeAgents()
    r = od.deploy(o, ["ag01-1", "ag08"], a, FakeTeams(a, fail=True), USER)
    assert r["statut"] == "echec_partiel" and "indisponible" in r["erreur"] and r["equipes"] == []
    assert [x["cle"] for x in r["agents"]] == ["ag01-1", "ag08", "equipe-1-chef"] and "Archivez" in r["suite"]
