"""Transformation EIA, incrément 1 : existant (AS-IS) sans processus, écarts AS-IS → TO-BE."""
import pytest

from backend import transformation as T

ME = "a@sncf.fr"
CMD, FRN = "c.s.data_demo_sc_commandes", "c.s.data_demo_sc_fournisseurs"
DISC = {"perimetre": "c.s", "date": "2026-11-22", "avertissement": "", "liens_probables": [], "constats": [],
        "tables": [{"table": t, "commentaire": "", "lignes": 10, "colonnes": [], "colonnes_non_profilees": 0}
                   for t in (CMD, FRN)]}
EXISTING = {"agent": {"ag_clara": "Clara"}, "outil": {"get_table_profile": "Profiler une table"}, "flux": {},
            "equipe": {}}


@pytest.fixture
def svc():
    return T.TransformationService(T.MemoryTransformationStore())


def _validate(svc, pid, kind):
    for i in svc.items(pid, ME, False):
        if i["status"] == "propose" and i["item_type"] == kind:
            svc.decide(pid, i["item_id"], ME, "valide")


@pytest.fixture
def pid(svc):
    p = svc.create("Pilote Supply Chain Data Quality", ME)["plan_id"]
    svc.set_context(p, ME, {"secteur": "Supply Chain", "objectifs": "Fiabiliser les données"})
    svc.set_discovery(p, ME, DISC)
    svc.propose(p, ME, [{"type": "objectif", "nom": "Fiabiliser"},
                        {"type": "domaine", "nom": "Supply Chain", "tables": [CMD, FRN]}])
    return p


def test_hakim_cannot_propose_processus():
    assert "processus" not in T.PROPOSABLE_TYPES and "processus" in T.ITEM_TYPES_AVAILABLE   # anciens plans lisibles
    assert set(T.PROPOSABLE_TYPES) == set(T.ITEM_TYPES_AVAILABLE) - {"processus"}


def test_step3_done_with_objective_and_domain_without_processus(svc, pid):
    plan = svc.get(pid, ME, False)
    assert svc.progress(plan, svc.items(pid, ME, False))[2]["statut"] == "en_cours"
    _validate(svc, pid, "domaine")
    assert svc.progress(plan, svc.items(pid, ME, False))[2]["statut"] == "en_cours"   # objectif manquant
    _validate(svc, pid, "objectif")
    steps = svc.progress(plan, svc.items(pid, ME, False))
    assert [s["statut"] for s in steps[:4]] == ["fait", "fait", "fait", "en_cours"]
    assert steps[2]["libelle"] == "Existant (AS-IS)" and steps[4]["libelle"] == "Cible (TO-BE)"


def test_use_case_without_processus_counts_for_step4(svc, pid):
    _validate(svc, pid, "domaine")
    _validate(svc, pid, "objectif")
    svc.propose(pid, ME, [{"type": "cas_usage", "nom": "Complétude des commandes", "tables": ["data_demo_sc_commandes"],
                           "objectif": "Fiabiliser", "limites": ["Seuil à valider"]}])
    cu = next(i for i in svc.items(pid, ME, False) if i["item_type"] == "cas_usage")
    assert cu["payload"]["processus"] is None and cu["evidence"] == {"tables": [CMD]}
    with pytest.raises(T.TransformationError, match="processus VALIDÉ"):   # un processus cité doit être validé
        svc.propose(pid, ME, [{"type": "cas_usage", "nom": "X", "tables": [CMD], "processus": "Inconnu"}])
    _validate(svc, pid, "cas_usage")
    plan = svc.get(pid, ME, False)
    items = svc.items(pid, ME, False)
    assert svc.progress(plan, items)[3]["statut"] == "fait" and svc.coherence(items) == []


def test_gaps_lists_targets_and_cases_without_target(svc, pid):
    _validate(svc, pid, "domaine")
    _validate(svc, pid, "objectif")
    svc.propose(pid, ME, [{"type": "cas_usage", "nom": "Complétude", "tables": [CMD]},
                          {"type": "cas_usage", "nom": "Doublons fournisseurs", "tables": [FRN]},
                          {"type": "cas_usage", "nom": "Rejeté", "tables": [FRN]}])
    _validate(svc, pid, "cas_usage")
    rej = next(i for i in svc.items(pid, ME, False) if i["name"] == "Rejeté")
    svc.decide(pid, rej["item_id"], ME, "rejete")
    svc.propose(pid, ME, [{"type": "agent", "nom": "Clara", "cas_usage": ["Complétude"], "mode": "reutiliser",
                           "existant": "ag_clara"},
                          {"type": "outil", "nom": "Contrôle complétude", "cas_usage": ["Complétude"], "mode": "creer",
                           "tables": [CMD]}], existing=EXISTING)
    catalog = {"agent": {"ag_clara": {"nom": "Clara", "statut": "publie"}}, "outil": {}, "flux": {}, "equipe": {}}
    gaps = svc.gaps(svc.items(pid, ME, False), catalog)
    rows = {(g["cas_usage"], g["element"]): g for g in gaps}
    assert set(rows) == {("Complétude", "Clara"), ("Complétude", "Contrôle complétude"), ("Doublons fournisseurs", None)}
    assert rows[("Complétude", "Clara")]["changement"] == "Réutilisation"
    assert rows[("Complétude", "Clara")]["objet"] == "Clara" and rows[("Complétude", "Clara")]["statut_objet"] == "publie"
    assert rows[("Complétude", "Contrôle complétude")]["changement"] == "Création"
    assert rows[("Complétude", "Contrôle complétude")]["objet"] is None
    assert rows[("Doublons fournisseurs", None)]["changement"] == "Aucune cible"
    assert rows[("Doublons fournisseurs", None)]["tables"] == [FRN]


def test_gaps_empty_without_use_cases(svc, pid):
    assert svc.gaps(svc.items(pid, ME, False)) == []
