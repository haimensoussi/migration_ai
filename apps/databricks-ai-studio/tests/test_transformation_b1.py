"""HakimAI Transformation, lot B1 (étapes 4 et 5) : traçabilité, réutilisation vérifiée, une étape par échange."""
import types

import pytest

from backend import hakim
from backend import transformation as T
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.hakim_tools import Platform

ME = "a@sncf.fr"
REG_T, GARES = "c.s.data_regularite", "c.s.data_gares"
DISC = {"perimetre": "c.s", "date": "2026-11-20", "avertissement": "", "liens_probables": [], "constats": [],
        "tables": [{"table": t, "commentaire": "", "lignes": 10, "colonnes": [], "colonnes_non_profilees": 0}
                   for t in (REG_T, GARES)]}
EXISTING = {"agent": {"ag_margot": "Margot"}, "outil": {"render_chart": "Graphique"},
            "flux": {"flux_so": "Smart Office"}, "equipe": {"tm_ter": "Équipe TER"}}
CU = {"type": "cas_usage", "nom": "Synthèse mensuelle", "processus": "suivi de la régularité",
      "tables": ["data_regularite"], "gain_attendu": "Moins d'analyses manuelles", "limites": ["Maille région"]}
CU2 = {**CU, "nom": "Alerte affluence", "processus": "Fréquentation", "tables": ["data_gares"]}


@pytest.fixture
def svc():
    return T.TransformationService(T.MemoryTransformationStore())


def _validate(svc, pid, kind=None, status="valide"):
    for i in svc.items(pid, ME, False):
        if i["status"] == "propose" and (kind is None or i["item_type"] == kind):
            svc.decide(pid, i["item_id"], ME, status)


def _item(svc, pid, name):
    return next(i for i in svc.items(pid, ME, False) if i["name"] == name)


@pytest.fixture
def pid(svc):
    """Plan aux étapes 1 à 3 faites : objectif, domaine et deux processus validés."""
    p = svc.create("P", ME)["plan_id"]
    svc.set_context(p, ME, {"secteur": "Gares", "objectifs": "Informer"})
    svc.set_discovery(p, ME, DISC)
    svc.propose(p, ME, [{"type": "objectif", "nom": "Informer"},
                        {"type": "domaine", "nom": "Régularité", "tables": [REG_T]},
                        {"type": "processus", "nom": "Suivi de la régularité", "tables": [REG_T]},
                        {"type": "processus", "nom": "Fréquentation", "tables": [GARES]}])
    _validate(svc, p)
    return p


# --- Étape 4 --------------------------------------------------------------------------------------------
def test_use_case_needs_validated_process_and_evidence(svc, pid):
    with pytest.raises(T.TransformationError, match="processus VALIDÉ"):
        svc.propose(pid, ME, [{**CU, "processus": "Inconnu"}])
    svc.propose(pid, ME, [{"type": "processus", "nom": "Maintenance", "tables": [GARES]}])   # proposé, non validé
    with pytest.raises(T.TransformationError, match="processus VALIDÉ"):
        svc.propose(pid, ME, [{**CU, "processus": "Maintenance"}])
    with pytest.raises(T.TransformationError, match="preuve"):
        svc.propose(pid, ME, [{**CU, "tables": []}])
    with pytest.raises(T.TransformationError, match="non validé"):
        svc.propose(pid, ME, [{**CU, "objectif": "Gagner du temps"}])
    res = svc.propose(pid, ME, [{**CU, "objectif": "informer"}])
    i = _item(svc, pid, "Synthèse mensuelle")
    assert res["etape"] == 4 and i["status"] == "propose"
    assert i["payload"]["processus"] == "Suivi de la régularité" and i["payload"]["objectif"] == "Informer"
    assert i["evidence"] == {"tables": [REG_T], "processus": "Suivi de la régularité"}
    assert i["payload"]["limites"] == ["Maille région"] and i["payload"]["gain_attendu"]


def test_one_step_per_proposal(svc, pid):
    with pytest.raises(T.TransformationError, match="qu'une étape"):
        svc.propose(pid, ME, [CU, {"type": "agent", "nom": "A", "cas_usage": ["x"], "mode": "creer"}],
                    existing=EXISTING)
    with pytest.raises(T.TransformationError, match="non disponible"):
        svc.propose(pid, ME, [{"type": "vague", "nom": "Vague 1"}])
    assert svc.items(pid, ME, False)[-1]["item_type"] == "processus"           # rien n'a été ajouté


# --- Étape 5 --------------------------------------------------------------------------------------------
def _with_use_case(svc, pid):
    svc.propose(pid, ME, [CU])
    _validate(svc, pid, "cas_usage")


def test_target_rules(svc, pid):
    _with_use_case(svc, pid)
    svc.propose(pid, ME, [CU2])                                              # cas d'usage non validé
    base = {"type": "agent", "nom": "Agent synthèse", "cas_usage": ["Synthèse mensuelle"], "mode": "creer"}
    cases = [({**base, "cas_usage": []}, "au moins un cas"),
             ({**base, "cas_usage": ["Alerte affluence"]}, "non validé"),
             ({**base, "mode": None}, "mode attendu"),
             ({**base, "mode": "reutiliser", "existant": "ag_inconnu"}, "n'est pas"),
             ({**base, "mode": "reutiliser"}, "n'est pas"),
             ({**base, "existant": "ag_margot"}, "sans objet existant"),
             ({**base, "type": "outil", "nom": "Outil"}, "tables"),
             ({**base, "type": "flux", "mode": "reutiliser", "existant": "render_chart"}, "n'est pas"),
             ({**base, "outils": ["outil_fantome"]}, "ni un"),
             ({"type": "equipe", "nom": "E", "cas_usage": ["Synthèse mensuelle"], "mode": "creer",
               "membres": ["Agent fantôme"]}, "ni un")]
    for element, msg in cases:
        with pytest.raises(T.TransformationError, match=msg):
            svc.propose(pid, ME, [element], existing=EXISTING)
    with pytest.raises(T.TransformationError, match="Catalogue"):
        svc.propose(pid, ME, [base])                                         # réutilisation non vérifiable
    res = svc.propose(pid, ME, [
        {"type": "outil", "nom": "Outil synthèse", "cas_usage": ["synthèse mensuelle"], "mode": "creer",
         "tables": ["data_regularite"]},
        {**base, "outils": ["outil synthèse", "render_chart"]},
        {"type": "agent", "nom": "Margot", "cas_usage": ["Synthèse mensuelle"], "mode": "adapter", "existant": "ag_margot"},
        {"type": "flux", "nom": "Diffusion", "cas_usage": ["Synthèse mensuelle"], "mode": "reutiliser", "existant": "flux_so"},
        {"type": "equipe", "nom": "Cellule régularité", "cas_usage": ["Synthèse mensuelle"], "mode": "creer",
         "membres": ["Agent synthèse", "ag_margot"]}], existing=EXISTING)
    assert res["etape"] == 5 and len(res["ajoutes"]) == 5
    agent, margot = _item(svc, pid, "Agent synthèse"), _item(svc, pid, "Margot")
    assert agent["payload"]["outils"] == ["Outil synthèse", "render_chart"]
    assert agent["evidence"] == {"tables": [], "cas_usage": ["Synthèse mensuelle"]}
    assert margot["payload"]["existant_nom"] == "Margot" and margot["payload"]["mode"] == "adapter"
    assert _item(svc, pid, "Cellule régularité")["payload"]["membres"] == ["Agent synthèse", "ag_margot"]
    assert _item(svc, pid, "Outil synthèse")["payload"]["cas_usage"] == ["Synthèse mensuelle"]   # nom exact
    assert {i["status"] for i in svc.items(pid, ME, False) if i["item_type"] in T.TARGET_TYPES} == {"propose"}


def test_progress_and_coherence(svc, pid):
    statuses = lambda: [s["statut"] for s in svc.progress(svc.get(pid, ME, False), svc.items(pid, ME, False))]  # noqa: E731
    assert statuses() == ["fait", "fait", "fait", "en_cours", "a_faire", "lot_b2", "lot_b2"]
    svc.propose(pid, ME, [CU, CU2])
    _validate(svc, pid, "cas_usage")
    assert statuses()[3:5] == ["fait", "en_cours"]
    t = {"type": "agent", "mode": "creer"}
    svc.propose(pid, ME, [{**t, "nom": "A1", "cas_usage": ["Synthèse mensuelle"]}], existing=EXISTING)
    _validate(svc, pid, "agent")
    assert statuses()[4] == "en_cours"                                       # Alerte affluence sans cible
    svc.propose(pid, ME, [{**t, "nom": "A2", "cas_usage": ["Alerte affluence"]}], existing=EXISTING)
    _validate(svc, pid, "agent")
    assert statuses()[4] == "fait"
    assert svc.coherence(svc.items(pid, ME, False)) == []
    svc.decide(pid, _item(svc, pid, "Suivi de la régularité")["item_id"], ME, "rejete")
    svc.decide(pid, _item(svc, pid, "Alerte affluence")["item_id"], ME, "propose")     # rouvert
    issues = svc.coherence(svc.items(pid, ME, False))
    assert len(issues) == 2
    assert any("Synthèse mensuelle" in m and "Suivi de la régularité" in m for m in issues)
    assert any(m.startswith("Agent « A2 »") and "Alerte affluence" in m for m in issues)
    assert statuses()[3:5] == ["en_cours", "a_faire"]                       # plus aucun cas d'usage cohérent


# --- Outils HakimAI -------------------------------------------------------------------------------------
class Sql:
    def __init__(self):
        self.done = []

    def execute(self, statement, params=None):
        self.done.append((statement, params))


def _ctx(svc, sql):
    tool = lambda i, n, c, s="publie": types.SimpleNamespace(tool_id=i, name=n, category=c, status=s)  # noqa: E731
    repo = types.SimpleNamespace(
        sql=sql, s=types.SimpleNamespace(table=lambda n: f"t.{n}"),
        list_agents=lambda: [{"agent_id": "ag_margot", "name": "Margot", "status": "publie", "owner": "x"},
                             {"agent_id": "ag_cache", "name": "Caché", "status": "brouillon", "owner": "autre"}],
        list_tools=lambda: [tool("render_chart", "Graphique", "Visualisation"), tool("flux_so", "Smart Office", "Flux"),
                            tool("vieil_outil", "Ancien", "SQL", "archive")])
    teams = types.SimpleNamespace(list_teams=lambda: [{"team_id": "tm_ter", "name": "Équipe TER", "status": "publie",
                                                       "owner": "x"}])
    plat = Platform(repo, teams, ME, False, transformation=svc)
    return ToolContext(sql=sql, workspace=None, user_email=ME, platform=plat)


PROPOSER = next(t for t in hakim.TOOLS if t.tool_id == "transformation_proposer")


def test_tool_checks_visible_catalog_and_one_step(svc, pid):
    reg, sql = ToolRegistry(hakim.TOOLS), Sql()
    run = lambda c, els: reg.run(PROPOSER, c, {"plan": pid, "elements": els})  # noqa: E731
    c1 = _ctx(svc, sql)
    assert run(c1, [CU])["etape"] == 4
    with pytest.raises(ToolError, match="Étape 4"):                          # étape 5 dans le même échange
        run(c1, [{"type": "agent", "nom": "A", "cas_usage": ["Synthèse mensuelle"], "mode": "creer"}])
    _validate(svc, pid, "cas_usage")                                         # décision humaine sur la page
    c2 = _ctx(svc, sql)
    ag = {"type": "agent", "nom": "Copie", "cas_usage": ["Synthèse mensuelle"], "mode": "reutiliser"}
    for ref in ("ag_cache", "vieil_outil"):                                  # brouillon d'un autre, outil archivé
        with pytest.raises(ToolError, match="n'est pas"):
            run(c2, [{**ag, "existant": ref}] if ref.startswith("ag") else [{**ag, "type": "outil", "existant": ref}])
    res = run(c2, [{**ag, "existant": "ag_margot"},
                   {**ag, "type": "flux", "nom": "Diffusion", "existant": "flux_so"},
                   {**ag, "type": "equipe", "nom": "TER", "existant": "tm_ter"}])
    assert res["etape"] == 5 and len(res["ajoutes"]) == 3
    assert [p["t"] for s, p in sql.done if "copilot_actions" in s] == ["transformation_proposer"] * 2
    etat = reg.run(next(t for t in hakim.TOOLS if t.tool_id == "transformation_etat"), c2, {"plan": pid})
    assert etat["elements"]["agent"][0]["existant_nom"] == "Margot" and etat["incoherences"] == []
    assert etat["elements"]["cas_usage"][0]["processus"] == "Suivi de la régularité"
