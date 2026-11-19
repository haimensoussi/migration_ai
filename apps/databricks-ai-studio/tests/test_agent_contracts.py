import datetime as dt
from types import SimpleNamespace

import pytest

from backend import agent_contracts as ac

FULL = {"domaine": "Supply Chain", "perimetre": "Analyse des stocks et des ruptures pour les magasins",
        "donnees": "dataops_dev.sc.stocks", "limites": "Ne traite pas les commandes fournisseurs.",
        "responsable_metier": "Jean.Dupont@sncf.fr", "date_revue": "2027-05-01"}


class FakeSql:
    def __init__(self):
        self.rows, self.executed = [], []

    def query(self, statement, params=None, row_limit=None):
        if "ORDER BY version DESC LIMIT 1" in statement:
            mine = [r for r in self.rows if r["agent_id"] == params["a"]]
            return {"rows": sorted(mine, key=lambda r: -r["version"])[:1]}
        return {"rows": []}

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if "INSERT INTO" in statement and "agent_contracts" in statement:
            self.rows.append({"agent_id": params["a"], "version": params["v"], "domaine": params["d"],
                              "perimetre": params["p"], "donnees": params["don"], "actions": params["act"],
                              "limites": params["l"], "responsable_metier": params["r"],
                              "date_revue": params["dr"], "statut_validation": "a_valider"})


def repo():
    return ac.ContractRepository(FakeSql(), SimpleNamespace(table=lambda n: f"cat.sch.{n}"))


def test_complete_contract_has_no_missing_field():
    assert ac.missing(FULL) == [] and ac.completeness(FULL) == 1.0
    n = ac.normalize(FULL)
    assert n["responsable_metier"] == "jean.dupont@sncf.fr" and n["date_revue"] == dt.date(2027, 5, 1)
    assert n["statut_validation"] == "a_valider"


def test_missing_and_invalid_fields():
    bad = {**FULL, "domaine": "Inconnu", "perimetre": "court", "responsable_metier": "pas-un-mail", "date_revue": "x"}
    m = ac.missing(bad)
    assert len(m) == 4 and ac.completeness(bad) == round(1 - 4 / 6, 2)
    assert ac.completeness(None) == 0.0 and ac.completeness({}) == 0.0


def test_data_prefilled_from_knowledge_tables():
    n = ac.normalize({}, ["a.b.c", "a.b.d"])
    assert n["donnees"] == "a.b.c\na.b.d"
    assert ac.normalize({"donnees": "saisie"}, ["a.b.c"])["donnees"] == "saisie"


def test_actions_derived_from_configuration():
    specs = {"execute_sql": SimpleNamespace(read_only=True, requires_confirmation=False),
             "run_job": SimpleNamespace(read_only=False, requires_confirmation=True)}
    acts = ac.derive_actions(["execute_sql", "run_job", "agent:abc", "inconnu"], specs)
    assert acts[0] == {"id": "execute_sql", "type": "outil", "ecriture": False, "validation": False}
    assert acts[1]["ecriture"] is True and acts[1]["validation"] is True
    assert acts[2]["type"] == "agent" and acts[3]["ecriture"] is None


def test_review_date_and_overdue():
    assert ac.default_review_date(dt.date(2026, 11, 30)) == dt.date(2027, 5, 28)
    assert ac.default_review_date(dt.date(2026, 3, 10)) == dt.date(2026, 9, 10)
    assert ac.review_overdue({"date_revue": "2026-01-01"}, dt.date(2026, 6, 1))
    assert not ac.review_overdue(FULL, dt.date(2026, 6, 1)) and not ac.review_overdue(None)


def test_save_versions_only_on_change():
    r = repo()
    assert r.save("a1", FULL, "u@x.fr") == 1
    assert r.save("a1", dict(FULL), "u@x.fr") is None             # inchangé : pas de nouvelle version
    assert r.save("a1", {**FULL, "limites": "Autre limite."}, "u@x.fr") == 2
    assert r.save("a2", FULL, "u@x.fr") == 1
    assert len(r.sql.rows) == 3
    stmt = r.sql.executed[0][0]
    assert "'a_valider'" in stmt and "cat.sch.agent_contracts" in stmt   # toute version repart à valider


def test_kpi_refresh_sql_is_bounded_and_atomic():
    q = ac.kpi_refresh_sql("c.s.kpi", "c.s.conv", "c.s.calls", 35)
    assert q.strip().startswith("INSERT INTO c.s.kpi REPLACE WHERE jour >= date_sub(current_date(), 34)")
    assert "FULL OUTER JOIN" in q and "c.s.conv" in q and "c.s.calls" in q
    for bad in (0, -1, 5000, "1; DROP TABLE x"):
        with pytest.raises(ValueError):
            ac.kpi_refresh_sql("k", "c", "t", bad)


def test_summarize_kpi():
    rows = [{"conversations": "2", "questions": "3", "reponses": "2", "latence_moy_ms": "1000", "appels_outils": "4",
             "appels_succes": "3", "appels_erreur": "1", "appels_refuse": "0"},
            {"conversations": 1, "questions": 1, "reponses": 2, "latence_moy_ms": 4000, "appels_outils": 0,
             "appels_succes": 0, "appels_erreur": 0, "appels_refuse": 0}]
    s = ac.summarize_kpi(rows)
    assert s["conversations"] == 3 and s["appels_outils"] == 4 and s["taux_succes_outils"] == 0.75
    assert s["latence_moy_ms"] == 2500 and s["jours_actifs"] == 2
    assert ac.summarize_kpi([])["taux_succes_outils"] is None
