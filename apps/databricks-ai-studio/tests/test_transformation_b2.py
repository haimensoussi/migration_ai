"""HakimAI Transformation, lot B2 (étapes 6 et 7) : vagues, suivi et liens vers objets réels."""
import types

import pytest

from backend import hakim
from backend import transformation as T
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.hakim_tools import Platform

ME = "a@sncf.fr"
REG_T = "c.s.data_regularite"
DISC = {"perimetre": "c.s", "date": "2026-11-20", "avertissement": "", "liens_probables": [], "constats": [],
        "tables": [{"table": REG_T, "commentaire": "", "lignes": 10, "colonnes": [], "colonnes_non_profilees": 0}]}


@pytest.fixture
def svc():
    return T.TransformationService(T.MemoryTransformationStore(), now=lambda: "2026-11-20T10:00:00")


def _validate(svc, pid, kind=None, status="valide"):
    for i in svc.items(pid, ME, False):
        if i["status"] == "propose" and (kind is None or i["item_type"] == kind):
            svc.decide(pid, i["item_id"], ME, status)


def _item(svc, pid, name):
    return next(i for i in svc.items(pid, ME, False) if i["name"] == name)


def _catalog():
    return {
        "agent": {"ag_existing": {"nom": "Agent existant", "statut": "publie"},
                  "ag_new": {"nom": "Agent brouillon", "statut": "brouillon"}},
        "outil": {"tool_new": {"nom": "Outil brouillon", "statut": "brouillon"}},
        "flux": {"flux_so": {"nom": "Flux existant", "statut": "publie"}},
        "equipe": {"tm_ops": {"nom": "Équipe Ops", "statut": "brouillon"}},
    }


@pytest.fixture
def pid(svc):
    p = svc.create("P", ME)["plan_id"]
    svc.set_context(p, ME, {"secteur": "Gares", "objectifs": "Informer"})
    svc.set_discovery(p, ME, DISC)
    svc.propose(p, ME, [{"type": "objectif", "nom": "Informer"},
                        {"type": "domaine", "nom": "Régularité", "tables": [REG_T]},
                        {"type": "processus", "nom": "Suivi", "tables": [REG_T]}])
    _validate(svc, p)
    svc.propose(p, ME, [{"type": "cas_usage", "nom": "Synthèse", "processus": "Suivi", "tables": [REG_T],
                         "gain_attendu": "Moins de tâches manuelles"}])
    _validate(svc, p, "cas_usage")
    svc.propose(p, ME, [
        {"type": "agent", "nom": "Agent synthèse", "cas_usage": ["Synthèse"], "mode": "creer"},
        {"type": "outil", "nom": "Outil synthèse", "cas_usage": ["Synthèse"], "mode": "creer", "tables": [REG_T]},
        {"type": "flux", "nom": "Flux existant", "cas_usage": ["Synthèse"], "mode": "reutiliser", "existant": "flux_so"},
    ], existing={"agent": {}, "outil": {}, "flux": {"flux_so": "Flux existant"}, "equipe": {}})
    _validate(svc, p, "agent")
    _validate(svc, p, "outil")
    _validate(svc, p, "flux")
    return p


def test_wave_rules_and_progress(svc, pid):
    with pytest.raises(T.TransformationError, match="ordre"):
        svc.propose(pid, ME, [{"type": "vague", "nom": "V1", "elements": ["Agent synthèse"], "ordre": 0,
                               "valeur": "fort", "effort": "moyen", "justification": "Priorité"}])
    with pytest.raises(T.TransformationError, match="au moins un élément"):
        svc.propose(pid, ME, [{"type": "vague", "nom": "V1", "elements": [], "ordre": 1,
                               "valeur": "fort", "effort": "moyen", "justification": "Priorité"}])
    res = svc.propose(pid, ME, [{"type": "vague", "nom": "Vague 1", "elements": ["agent:Agent synthèse", "Outil synthèse"],
                                 "ordre": 1, "valeur": "fort", "effort": "moyen", "justification": "Démonstrateur métier"},
                                {"type": "vague", "nom": "Vague 2", "elements": ["Flux existant"], "ordre": 2,
                                 "valeur": "moyen", "effort": "faible", "justification": "Industrialisation",
                                 "dependances": ["Vague 1"]}])
    assert res["etape"] == 6 and len(res["ajoutes"]) == 2
    _validate(svc, pid, "vague")
    items = svc.items(pid, ME, False)
    assert svc.progress(svc.get(pid, ME, False), items)[5]["statut"] == "fait"
    assert [x["vague"] for x in svc.planned(items)] == ["Vague 1", "Vague 1", "Vague 2"]
    with pytest.raises(T.TransformationError, match="déjà dans la vague"):
        svc.propose(pid, ME, [{"type": "vague", "nom": "Vague 3", "elements": ["Agent synthèse"], "ordre": 3,
                               "valeur": "faible", "effort": "faible", "justification": "Doublon"}])


def test_tracking_and_link_rules(svc, pid):
    svc.propose(pid, ME, [{"type": "vague", "nom": "Vague 1", "elements": ["Agent synthèse", "Outil synthèse", "Flux existant"],
                           "ordre": 1, "valeur": "fort", "effort": "moyen", "justification": "Déploiement initial"}])
    _validate(svc, pid, "vague")
    items = svc.items(pid, ME, False)
    tracking = svc.tracking(items, _catalog())
    by_name = {x["nom"]: x for x in tracking}
    assert by_name["Flux existant"]["statut"] == "publie"
    assert by_name["Agent synthèse"]["statut"] == "a_faire"
    with pytest.raises(T.TransformationError, match="rien à relier"):
        svc.link(pid, ME, "Flux existant", "flux_so", _catalog())
    linked = svc.link(pid, ME, "Agent synthèse", "ag_new", _catalog())
    assert linked["statut_objet"] == "brouillon"
    with pytest.raises(T.TransformationError, match="déjà relié"):
        svc.link(pid, ME, "Agent synthèse", "ag_existing", _catalog())
    after = {x["nom"]: x for x in svc.tracking(svc.items(pid, ME, False), _catalog())}
    assert after["Agent synthèse"]["statut"] == "brouillon"
    assert svc.progress(svc.get(pid, ME, False), svc.items(pid, ME, False), _catalog())[6]["statut"] == "en_cours"


TRANSFO = {t.tool_id: t for t in hakim.TOOLS if t.executor.startswith("tools.hakim_transformation_tools:")}


class Sql:
    def __init__(self):
        self.done = []

    def execute(self, statement, params=None):
        self.done.append((statement, params))


def _ctx(svc, sql):
    tool = lambda i, n, c, s="publie": types.SimpleNamespace(tool_id=i, name=n, category=c, status=s)  # noqa: E731
    repo = types.SimpleNamespace(
        sql=sql, s=types.SimpleNamespace(table=lambda n: f"t.{n}"),
        list_agents=lambda: [{"agent_id": "ag_existing", "name": "Agent existant", "status": "publie", "owner": "x"},
                             {"agent_id": "ag_new", "name": "Agent brouillon", "status": "brouillon", "owner": ME}],
        list_tools=lambda: [tool("tool_new", "Outil brouillon", "SQL", "brouillon"),
                            tool("flux_so", "Flux existant", "Flux", "publie")])
    teams = types.SimpleNamespace(list_teams=lambda: [{"team_id": "tm_ops", "name": "Équipe Ops", "status": "brouillon",
                                                       "owner": ME}])
    plat = Platform(repo, teams, ME, False, transformation=svc)
    return ToolContext(sql=sql, workspace=None, user_email=ME, platform=plat)


def test_tool_catalog_and_b2_tools(svc, pid):
    assert {"transformation_feuille_route", "transformation_suivre", "transformation_relier"} <= set(TRANSFO)
    assert TRANSFO["transformation_suivre"].read_only is True
    reg, sql = ToolRegistry(hakim.TOOLS), Sql()
    ctx = _ctx(svc, sql)
    reg.run(TRANSFO["transformation_feuille_route"], ctx, {"plan": pid, "vagues": [{
        "nom": "Vague 1", "elements": ["Agent synthèse"], "ordre": 1, "valeur": "fort", "effort": "moyen",
        "justification": "Priorité métier"}]})
    _validate(svc, pid, "vague")
    nxt = _ctx(svc, sql)
    reg.run(TRANSFO["transformation_relier"], nxt, {"plan": pid, "element": "Agent synthèse", "objet": "ag_new"})
    newer = _ctx(svc, sql)
    suivi = reg.run(TRANSFO["transformation_suivre"], newer, {"plan": pid})
    assert suivi["suivi"][0]["statut"] == "brouillon"
    assert [p["t"] for s, p in sql.done if "copilot_actions" in s] == ["transformation_feuille_route", "transformation_relier", "transformation_suivre"]
