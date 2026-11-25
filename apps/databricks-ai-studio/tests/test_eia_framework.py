"""Framework des agents AG01-AG11 : contrat commun, interfaces, statuts et cohérence d'équipe."""
import copy
import importlib
import json
from dataclasses import replace

import pytest

from backend.eia import agent_models as am
from backend.eia.team_config import load, validate
from tests.test_eia_cycle import Source, cfg, repo, TODAY, USER
from backend.eia import engine as e


def test_ten_models_cover_eleven_categories_with_ag02_merged():
    assert sorted(am.MODELS) == [f"AG{i:02d}" for i in range(1, 12) if i != 2]
    for code, meta in am.CATEGORIES.items():
        if code == "AG02":
            assert code not in am.MODELS and meta["fusionne_dans"] == "AG01"
        else:
            assert meta["statut"] == am.MODELS[code].status, code
    status = {c: m.status for c, m in am.MODELS.items()}
    assert [c for c, s in status.items() if s == "disponible"] == ["AG01", "AG03", "AG06"]
    assert [c for c, s in status.items() if s == "partiel"] == ["AG04", "AG05", "AG08", "AG09", "AG10"]
    assert [c for c, s in status.items() if s == "squelette"] == ["AG07", "AG11"]


@pytest.mark.parametrize("code", sorted(am.MODELS))
def test_every_model_follows_common_contract(code):
    m = am.MODELS[code]
    assert m.status in am.MODEL_STATUSES and m.version and m.functions and m.params and m.usage and m.outputs
    assert all(p.origin in am.ORIGINS and p.description for p in m.params)
    assert all(i in am.INTERFACES for i in (*m.inputs, *m.optional_inputs, *m.outputs))
    assert m.inputs or m.optional_inputs
    d = m.describe()
    json.dumps(d, ensure_ascii=False)
    assert d["garde_fous"][:len(am.GUARDRAILS)] == list(am.GUARDRAILS)
    if m.status == "squelette":
        assert not m.entrypoints and m.missing
    else:
        assert m.entrypoints
        if m.status == "partiel":
            assert m.missing
    for ep in m.entrypoints:                       # chaque point d'entrée déclaré existe vraiment
        module, fn = ep.split(":")
        assert callable(getattr(importlib.import_module(module), fn)), ep


def test_reference_compositions_are_coherent():
    assert am.check_composition(list(am.BUSINESS_TEAM)) == []
    assert am.check_composition(list(am.FACTORY_TEAM)) == []          # EIA Factory opérationnelle (AG09, AG10)
    assert any("squelette" in x for x in am.check_composition(["AG01", "AG03", "AG11"]))


def test_composition_errors_detected():
    issues = am.check_composition(["AG03", "AG06"])            # recommandations sans détection d'alertes
    assert issues == ["AG03 : entrée alertes produite par aucun modèle de l'équipe"]
    assert any("fusionné dans AG01" in x for x in am.check_composition(["AG01", "AG02"]))
    assert any("inconnue" in x for x in am.check_composition(["AG99"]))
    assert any("AG11 : entrée recommandations" in x for x in am.check_composition(["AG01", "AG11"], True))


def test_sales_is_built_from_framework_without_issue():
    sales = load("sales")
    assert sales.models == list(am.BUSINESS_TEAM) and am.team_models(sales) == list(am.BUSINESS_TEAM)
    assert am.check_team(sales) == []


def test_team_config_rejects_incoherent_models():
    cf = load("sales")
    data = {name: copy.deepcopy(getattr(cf, name)) for name in cf.__dataclass_fields__}
    data["models"] = ["AG03", "AG07"]
    issues = validate(data)
    assert any("entrée alertes" in x for x in issues) and any("AG07 n'est pas encore opérationnel" in x for x in issues)
    data["models"] = []
    assert any("liste non vide" in x for x in validate(data))


def test_model_parameter_checks_detect_gaps():
    base = cfg()
    no_pb = replace(base, playbooks=[])
    assert any("aucun plan d'action" in x for x in am.AG03.check(no_pb))
    bad_kpi = replace(base, playbooks=[{**base.playbooks[0], "success_kpis": ["absent"]}])
    assert any("KPI de réussite inconnu absent" in x for x in am.AG05.check(bad_kpi))
    assert any("référentiel de compétences" in x for x in am.AG06.check(replace(base, skills=[])))
    bad_policy = replace(base, validation_policy={"mission_requires_validation": False, "external_actions": "libre"})
    assert len(am.AG04.check(bad_policy)) == 2 and len(am.AG08.check(bad_policy)) == 2
    assert any("obligatoire absent : knowledge.sources" in x for x in am.AG07.check(base))


def test_derived_composition_when_models_not_declared():
    assert am.team_models(replace(cfg(), models=[])) == ["AG01", "AG03", "AG06"]


def test_cycle_traces_models_and_versions():
    r = repo()
    out = e.run_cycle(cfg(), Source(), r, today=TODAY, actor=USER)
    assert list(out["modeles"]) == list(am.BUSINESS_TEAM)
    assert out["modeles"]["AG01"] == {"version": "1.0", "statut": "disponible"}
    plan = json.loads(r.s.data["eia_runs"][0]["plan"])
    assert plan["modeles"] == out["modeles"] and plan["categories"]["staffing"] == "AG06"
