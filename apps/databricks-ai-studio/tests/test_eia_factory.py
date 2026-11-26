"""EIA Factory : Catalogue d'Agents (étape 2), Team Builder (étape 3), intégration (étape 4).

Tests synthétiques sans SQL, réseau, modèle ni écriture en production.
"""
import copy

import pytest

from backend.eia import agent_catalog as ac, agent_models as am, team_builder as tb
from backend.eia.contracts import ContractError
from backend.eia.store import EiaRepository, MemoryEiaStore
from backend.eia.team_config import TeamConfig
from tests.test_eia_ag01 import GapSource
from tests.test_eia_cycle import TODAY, USER, Source

SCOPE = ("dataops_dev", "ai_studio", "data_")
V = "dataops_dev.ai_studio.data_ventes"


def col(nom, type_, **kw):
    return {"nom": nom, "type": type_, "commentaire": "", "remplissage_pct": 100.0, "valeurs_distinctes": 10,
            "cle_candidate": False, **kw}


def discovery():
    return {"perimetre": "dataops_dev.ai_studio, 3 table(s)", "date": "2026-11-24", "avertissement": "Constats",
            "tables": [
                {"table": V, "lignes": 1000, "commentaire": "", "colonnes": [
                    col("vente_id", "bigint", cle_candidate=True), col("client_id", "bigint"),
                    col("date_vente", "date", min="2023-11-01", max="2026-10-28"),
                    col("montant", "decimal(12,2)"), col("quantite", "int"), col("canal", "string")]},
                {"table": "dataops_dev.ai_studio.data_plan", "lignes": 50, "commentaire": "", "colonnes": [
                    col("date_debut", "date", min="2025-01-01", max="2026-09-30", remplissage_pct=90.0),
                    col("date_fin", "date", min="2025-02-01", max="2027-06-30")]},
                {"table": "dataops_dev.ai_studio.data_ref", "lignes": 5, "commentaire": "",
                 "colonnes": [col("code", "string")]},
                {"table": "dataops_dev.ai_studio.data_ko", "erreur": "PERMISSION_DENIED"}],
            "donnees_sensibles": [{"table": V, "colonne": "quantite", "categorie": "test", "statut": "à confirmer"}],
            "liens_probables": [], "constats": []}


def cands():
    return tb.kpi_candidates(discovery(), today=TODAY)


# ---------------------------------------------------------------- étape 2 : catalogue
def test_catalog_is_derived_from_framework():
    s = ac.summary()
    assert s["categories"] == 10 and s["modeles"] == 10
    assert s["par_statut"] == {"disponible": 4, "partiel": 5, "squelette": 1}
    for code in am.CATEGORIES:
        c = ac.card(code)
        assert c["modele"] == am.MODELS[code].describe() and c["capacites"] == list(am.MODELS[code].functions)
    assert ac.card("AG02")["recoit_de"] == {"observations": ["AG01"]}
    assert ac.card("AG03")["recoit_de"]["previsions"] == ["AG02"]
    assert ac.card("AG03")["recoit_de"]["alertes"] == ["AG01"]
    with pytest.raises(KeyError):
        ac.card("AG99")


def test_team_templates_are_operational():
    states = {t["id"]: t for t in ac.templates()}
    assert {k: v["etat"] for k, v in states.items()} == {"equipe_metier": "operationnel",
                                                        "equipe_surveillance": "operationnel",
                                                        "eia_factory": "operationnel"}
    assert states["eia_factory"]["modeles"] == list(am.FACTORY_TEAM)
    assert {m["code"] for m in states["eia_factory"]["modeles_a_completer"]} == {"AG10", "AG09", "AG08"}


# ---------------------------------------------------------------- étape 3 : découverte (AG01) et contrôle
def test_kpi_candidates_follow_structure_without_business_invention():
    ids = {k["id"]: k for k in cands()}
    assert set(ids) == {"nb_ventes", "total_ventes_montant", "nb_plan"}
    v = ids["nb_ventes"]
    assert v["statut"] == "a_valider" and v["origine"] == "donnees" and v["axe_temporel"] == "date_vente"
    assert v["historique_mois"] == 36 and v["previsible"] and "current_date()" in v["sql"]
    assert "{ventes}" in v["sql"] and " AS period" in v["sql"] and " AS value" in v["sql"]
    # identifiants, clés et colonnes sensibles exclus des mesures
    assert not any(x in ids for x in ("total_ventes_vente_id", "total_ventes_client_id", "total_ventes_quantite"))
    # axe temporel sans dates futures préféré, même moins rempli ; historique court : pas de prévision
    p = ids["nb_plan"]
    assert p["axe_temporel"] == "date_debut" and p["historique_mois"] == 21 and p["previsible"]


def test_discovery_gate():
    g = tb.gate("decouverte", discovery(), cands())
    assert g["reussi"] and any("profil impossible" in w for w in g["avertissements"])
    assert any("sensible" in w for w in g["avertissements"])
    d = discovery()
    d["tables"] = [d["tables"][2]]
    g = tb.gate("decouverte", d, tb.kpi_candidates(d, TODAY))
    assert not g["reussi"] and "Aucun KPI candidat" in g["bloquants"][0]
    with pytest.raises(tb.TeamBuilderError):
        tb.gate("inconnue")


# ---------------------------------------------------------------- architecture (AG10)
def test_design_without_business_rules_is_a_monitoring_team():
    d = tb.design("ventes_pilote", "Ventes", "Pilote", ["Suivre les ventes"], cands(), owner=USER)
    cfg = d["config"]
    assert d["modele_equipe"] == "equipe_surveillance" and cfg["models"] == ["AG01", "AG02", "AG08"]
    assert cfg["rules"] == [] and cfg["playbooks"] == [] and "advisor" not in cfg["agents"]
    assert "max_lag_months" not in cfg["perception"] and cfg["perception"]["status"] == "a_valider"
    assert cfg["validation_policy"]["validators"] == [USER] and cfg["validation_policy"]["external_actions"] == "interdit"
    assert set(cfg["forecast"]["kpis"]) <= {"nb_ventes", "total_ventes_montant", "nb_plan"}
    assert any("aucun seuil n'est inventé" in r for r in d["justification"])
    assert tb.gate("architecture", config=cfg, data_scope=SCOPE)["reussi"]


def test_design_rejections_and_scope_control():
    with pytest.raises(tb.TeamBuilderError):
        tb.design("sales", "x", "", [], cands())                    # équipe versionnée existante
    with pytest.raises(tb.TeamBuilderError):
        tb.design("Mauvais id", "x", "", [], cands())
    with pytest.raises(tb.TeamBuilderError):
        tb.design("t1", "x", "", [], cands(), kpi_ids=["absent"])
    d = tb.design("t1", "x", "", [], cands())
    g = tb.gate("architecture", config=d["config"], data_scope=("autre", "schema", "data_"))
    assert not g["reussi"] and any("hors zone" in b for b in g["bloquants"])


def test_design_with_rules_and_playbooks_uses_business_template():
    from tests.test_eia_cycle import cfg as sales_like
    base = sales_like()
    rule = {**base.rules[0], "kpi": "nb_ventes"}
    pb = {**base.playbooks[0], "success_kpis": ["nb_ventes"]}
    d = tb.design("ventes_metier", "Ventes", "", ["x"], cands(), rules=[rule], playbooks=[pb],
                  skills=base.skills, staffing=base.staffing, owner=USER)
    assert d["modele_equipe"] == "equipe_metier" and d["modeles"] == list(am.BUSINESS_TEAM)
    assert {"advisor", "planner", "staffing"} <= set(d["roles"])
    assert tb.gate("architecture", config=d["config"], data_scope=SCOPE)["bloquants"] == []


# ---------------------------------------------------------------- déploiement (AG09) et cycle de vie
def run(source):
    return tb.run(discovery, source, team_id="ventes_pilote", name="Ventes", objectives=["Suivre"], owner=USER,
                  data_scope=SCOPE, today=TODAY)


def test_full_run_passes_three_gates_without_writing():
    src = Source()
    out = run(src)
    assert out["phase_atteinte"] == "deploiement" and [g["phase"] for g in out["controles"]] == list(tb.PHASES)
    assert all(g["reussi"] for g in out["controles"]), out["controles"]
    r = out["recette"]
    assert r["persistant"] is False and r["kpi_exploitables"] == 3 and r["kpi_ecartes"] == {} and src.calls >= 3
    assert set(r["modeles"]) == {"AG01", "AG02", "AG08"}
    assert tb.run(discovery, src, upto="decouverte", today=TODAY)["phase_atteinte"] == "decouverte"


def test_recette_failure_blocks_and_adjustment_removes_bad_forecasts():
    out = run(GapSource())          # mois manquant : prévisions impossibles, KPI toujours suivis
    a = out["architecture"]
    assert a["ajustements"] and a["ajustements"][0]["previsions_retirees"]
    assert "forecast" not in a["config"] and "prediction" not in a["config"]["agents"]
    assert "AG02" not in a["config"]["models"]          # plus de prévision : plus de Predictive Intelligence
    assert len(a["config"]["kpis"]) == 3 and any("Ajustement AG09" in j for j in a["justification"])
    assert out["controles"][-1]["reussi"], out["controles"][-1]
    failing = tb.gate("deploiement", recette={"kpi_ecartes": {"x": "retard"}, "erreurs": [], "kpi_exploitables": 0})
    assert not failing["reussi"] and len(failing["bloquants"]) == 2
    assert tb.adjust(a, cands(), {"erreurs": ["analyst : erreur"]}) is None


def test_draft_service_and_retirement_are_human_decisions():
    repo = EiaRepository(MemoryEiaStore())
    out = run(Source())
    with pytest.raises(ContractError):
        tb.build(out["architecture"], out["controles"], out["recette"], "agent:team_builder")
    row = tb.build(out["architecture"], out["controles"], out["recette"], USER)
    assert row["status"] == "brouillon" and tb.deployable(row) == []
    cid = repo.save_team_config(row)
    assert repo.team_config_in_service("ventes_pilote") is None
    with pytest.raises(ContractError):
        repo.set_team_config_status(cid, "en_service", "agent:eia")
    with pytest.raises(ContractError):
        repo.set_team_config_status(cid, "en_service", USER, ["Contrôle deploiement non réussi"])
    repo.set_team_config_status(cid, "en_service", USER)
    cfg = tb.resolve("ventes_pilote", repo, SCOPE)
    assert isinstance(cfg, TeamConfig) and cfg.models == ["AG01", "AG02", "AG08"]
    assert "ventes_pilote" in tb.teams(repo) and "sales" in tb.teams(repo)
    row2 = copy.deepcopy(row)
    row2["config_id"] = "tc_v2"
    repo.save_team_config(row2)
    repo.set_team_config_status("tc_v2", "en_service", USER)
    states = {r["config_id"]: r["status"] for r in repo.team_configs("ventes_pilote")}
    assert states == {cid: "retiree", "tc_v2": "en_service"}
    with pytest.raises(ContractError):
        repo.set_team_config_status(cid, "en_service", USER)       # retirée : définitif
    assert [e["event_type"] for e in repo.events(cid)] == ["brouillon", "en_service", "retiree"]
    with pytest.raises(Exception):
        tb.resolve("inconnue", repo, SCOPE)


def test_incomplete_draft_cannot_go_live():
    repo = EiaRepository(MemoryEiaStore())
    out = tb.run(discovery, Source(), team_id="t2", name="x", upto="architecture", data_scope=SCOPE, today=TODAY)
    row = tb.build(out["architecture"], out["controles"], None, USER)
    assert tb.deployable(row) == ["Contrôle deploiement non réussi"]
    cid = repo.save_team_config(row)
    with pytest.raises(ContractError):
        repo.set_team_config_status(cid, "en_service", USER, tb.deployable(repo.team_config(cid)))


# ---------------------------------------------------------------- étape 4 : intégration HAKIM et catalogue public
def test_factory_tools_registered_with_confirmation_on_writes():
    from backend import hakim
    from tools import catalog
    from tools.eia_factory_tools import EIA_FACTORY_TOOLS, eia_catalogue_agents
    ids = {t.tool_id: t for t in EIA_FACTORY_TOOLS}
    assert set(ids) == {"eia_catalogue_agents", "eia_team_builder", "eia_team_builder_enregistrer",
                        "eia_team_builder_decision"}
    assert {t for t, s in ids.items() if s.requires_confirmation} == {"eia_team_builder_enregistrer",
                                                                      "eia_team_builder_decision"}
    assert set(ids) <= {t.tool_id for t in hakim.TOOLS} and set(ids) <= {t.tool_id for t in catalog.BUILTIN_TOOLS}
    assert "eia_team_builder" in hakim.EIA_INSTRUCTIONS
    from backend.tool_registry import ToolContext
    ctx = ToolContext(sql=None, workspace=None, user_email=USER)
    assert eia_catalogue_agents(ctx, "fiche", "AG10")["modele"]["statut"] == "partiel"
    assert len(eia_catalogue_agents(ctx, "fiches")["fiches"]) == 10
