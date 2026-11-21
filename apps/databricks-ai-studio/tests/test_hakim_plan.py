"""Plan de travail HakimAI : liste « Étape N — Titre » affichée, exécution directe, seules les écritures annoncées."""
import types

import pytest

from backend import hakim, hakim_guard
from backend import hakim_plan as HP
from backend import transformation as T
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.hakim_tools import Platform

ME = "a@sncf.fr"
KNOWN = {t.tool_id for t in hakim.TOOLS}
SPECS = {t.tool_id: t for t in hakim.TOOLS}
GOOD = {"etapes": [{"titre": "Lecture des plans", "outil": "transformation_plans", "nature": "lecture"},
                   {"titre": "Création du plan", "outil": "transformation_creer_plan", "nature": "ecriture"},
                   {"titre": "Questions de cadrage", "outil": "aucun", "nature": "aucune"},
                   {"titre": "Enregistrement du cadrage", "outil": "transformation_cadrage", "nature": "ecriture"}]}


class Sql:
    def __init__(self):
        self.done = []

    def execute(self, statement, params=None):
        self.done.append((statement, params))


def _ctx(svc, store, sql, required=True):
    repo = types.SimpleNamespace(sql=sql, s=types.SimpleNamespace(table=lambda n: f"t.{n}"))
    plat = Platform(repo, None, ME, False, transformation=svc, work_plan=store, plan_required=required)
    return ToolContext(sql=sql, workspace=None, user_email=ME, platform=plat)


@pytest.fixture
def svc():
    return T.TransformationService(T.MemoryTransformationStore(), now=lambda: "2026-11-21T10:00:00")


def _step(titre="x", outil="aucun", nature="aucune"):
    return {"etapes": [{"titre": titre, "outil": outil, "nature": nature}]}


def test_plan_shape_is_steps_only():
    assert HP.issue(GOOD, KNOWN) is None
    assert "titre court" in HP.issue(_step(titre=""), KNOWN)
    assert "trop long" in HP.issue(_step(titre="x" * 61), KNOWN)
    assert HP.issue(_step(titre="x" * 60), KNOWN) is None
    assert "inconnu" in HP.issue(_step(outil="outil_invente", nature="lecture"), KNOWN)
    assert "nature « ecriture »" in HP.issue(_step(outil="transformation_proposer", nature="lecture"), KNOWN)
    assert "8 étapes" in HP.issue({"etapes": GOOD["etapes"] * 3}, KNOWN)
    assert hakim_guard.presentation_issue(HP.PLAN_TOOL, {"etapes": []}, [], {})
    assert set(SPECS[HP.PLAN_TOOL].input_schema["properties"]) == {"plan", "etapes"}


def test_plan_runs_without_confirmation_and_shows_titled_steps():
    spec = SPECS[HP.PLAN_TOOL]
    assert not spec.requires_confirmation and not spec.read_only
    assert hakim.describe_action(HP.PLAN_TOOL, GOOD) == [
        "Étape 1 — Lecture des plans", "Étape 2 — Création du plan", "Étape 3 — Questions de cadrage",
        "Étape 4 — Enregistrement du cadrage"]
    assert "hakim_plan_travail" in hakim.INSTRUCTIONS and "sans demander de validation" in hakim.INSTRUCTIONS


def test_step_states_come_from_called_tools():
    st = {}
    HP.approve(st, GOOD)
    assert [x["etat"] for x in HP.lines(st)] == ["en_cours", "a_faire", "a_faire", "a_faire"]
    # lecture avant le plan ignorée ; appels échoués ignorés ; ordre respecté
    HP.record(st, [("transformation_etat", "succes"), (HP.PLAN_TOOL, "succes"), ("transformation_plans", "succes"),
                   ("transformation_creer_plan", "erreur")])
    assert [x["etat"] for x in HP.lines(st)] == ["fait", "en_cours", "a_faire", "a_faire"]
    HP.record(st, [("transformation_creer_plan", "succes")])
    assert [x["etat"] for x in HP.lines(st)] == ["fait", "fait", "fait", "en_cours"]   # étape texte atteinte
    HP.record(st, [("transformation_cadrage", "succes")])
    lines = HP.lines(st)
    assert [x["etat"] for x in lines] == ["fait"] * 4
    assert lines[0]["libelle"] == "Étape 1 — Lecture des plans"
    HP.approve(st, _step(titre="Nouveau"))                                  # nouveau plan : état repart à zéro
    assert HP.lines(st) == [{"libelle": "Étape 1 — Nouveau", "etat": "fait"}] and st["appels"] == []


def test_writes_blocked_without_announced_plan(svc):
    reg, sql, store = ToolRegistry(hakim.TOOLS), Sql(), {}
    with pytest.raises(ToolError, match="Aucun plan de travail en cours"):
        reg.run(SPECS["transformation_creer_plan"], _ctx(svc, store, sql), {"nom": "IA Gares"})
    assert svc.list_plans(ME, False) == [] and sql.done == []         # rien d'écrit, rien de tracé
    assert reg.run(SPECS["transformation_plans"], _ctx(svc, store, sql), {})["nombre"] == 0   # lecture permise


def test_only_announced_writes_once_each(svc):
    reg, sql, store = ToolRegistry(hakim.TOOLS), Sql(), {}
    res = reg.run(SPECS[HP.PLAN_TOOL], _ctx(svc, store, sql), GOOD)              # exécution directe
    assert res["ecritures_permises"] == {"transformation_creer_plan": 1, "transformation_cadrage": 1}
    assert res["etapes"][1] == "Étape 2 — Création du plan"
    with pytest.raises(ToolError, match="titre"):                                 # plan mal formé : rien enregistré
        reg.run(SPECS[HP.PLAN_TOOL], _ctx(svc, store, sql), _step(titre=""))
    assert store["plan_travail_id"] == res["plan_travail_id"]
    pid = reg.run(SPECS["transformation_creer_plan"], _ctx(svc, store, sql), {"nom": "IA Gares"})["plan_id"]
    with pytest.raises(ToolError, match="plus\\) annoncé"):                         # deuxième création : non annoncée
        reg.run(SPECS["transformation_creer_plan"], _ctx(svc, store, sql), {"nom": "Autre"})
    with pytest.raises(ToolError, match="annoncé"):                                 # écriture absente du plan
        reg.run(SPECS["transformation_decouvrir"], _ctx(svc, store, sql), {"plan": pid})
    reg.run(SPECS["transformation_cadrage"], _ctx(svc, store, sql), {"plan": pid, "secteur": "Gares"})
    assert store["statut"] == "termine" and store["faits"] == ["transformation_creer_plan", "transformation_cadrage"]
    audits = [p for s, p in sql.done if "copilot_actions" in s]
    assert [p["t"] for p in audits] == [HP.PLAN_TOOL, "transformation_creer_plan", "transformation_cadrage"]
    assert all(store["plan_travail_id"] in p["a"] for p in audits[1:])             # chaque écriture reliée au plan
    with pytest.raises(ToolError, match="Aucun plan"):                              # plan terminé
        reg.run(SPECS["transformation_cadrage"], _ctx(svc, store, sql), {"plan": pid, "objectifs": "x"})


def test_plan_bound_to_one_transformation_plan(svc):
    reg, sql, store = ToolRegistry(hakim.TOOLS), Sql(), {}
    a = svc.create("A", ME)["plan_id"]
    b = svc.create("B", ME)["plan_id"]
    reg.run(SPECS[HP.PLAN_TOOL], _ctx(svc, store, sql), {**GOOD, "plan": a})
    with pytest.raises(ToolError, match="porte sur"):
        reg.run(SPECS["transformation_cadrage"], _ctx(svc, store, sql), {"plan": b, "secteur": "Gares"})
    assert svc.get(b, ME, False)["context"] == {}


def test_failed_write_does_not_consume_and_gate_off_elsewhere(svc):
    reg, sql, store = ToolRegistry(hakim.TOOLS), Sql(), {}
    reg.run(SPECS[HP.PLAN_TOOL], _ctx(svc, store, sql), GOOD)
    with pytest.raises(ToolError):                                                   # plan inexistant : échec métier
        reg.run(SPECS["transformation_cadrage"], _ctx(svc, store, sql), {"plan": "tp_absent", "secteur": "x"})
    assert store["restant"]["transformation_cadrage"] == 1
    # hors page HakimAI (plan_required=False) : comportement inchangé
    assert reg.run(SPECS["transformation_creer_plan"], _ctx(svc, {}, Sql(), required=False), {"nom": "P"})["plan_id"]
