"""AG01 Data Intelligence : catalogue, fiche de paramètres et contrôles de passage de la perception.

Tests synthétiques sans SQL, réseau, modèle ni écriture en production.
"""
import copy
import datetime as dt
from dataclasses import replace

from backend.eia import agent_models as am, agents as a, contracts as c, engine as e, kpi as k
from backend.eia.alerting import KpiData
from backend.eia.team_config import load, validate
from tests.test_eia_cycle import TODAY, USER, Source, cfg, repo


class GapSource(Source):
    """Série à jour mais avec un mois manquant (2026-06)."""

    def fetch(self, cfg, metric, today):
        data = super().fetch(cfg, metric, today)
        data.points = [p for p in data.points if p["period"] != "2026-06"]
        return data


def cycle(source, conf=None):
    r = repo()
    return r, e.run_cycle(conf or cfg(), source, r, today=TODAY, actor=USER)


def test_catalog_ten_categories_with_predictive_separated():
    cat = {x["code"]: x for x in am.catalog()}
    assert list(cat) == [f"AG{i:02d}" for i in range(1, 11)]          # Simulation & Scenario retiré
    assert cat["AG02"]["nom"] == "Predictive Intelligence Agent" and cat["AG02"]["modele"]["version"] == "1.0"
    assert "prévisions" not in cat["AG01"]["fonctions"].lower() and "Prévisions" in cat["AG02"]["fonctions"]
    assert all(am.category_of(r) for r in e.ROLES) and set(c.AGENT_ROLES) == set(e.ROLES)
    assert am.AG01.functions == ("perception", "analyst", "alerting") and am.MODELS["AG02"].functions == ("prediction",)
    assert am.category_of("prediction") == "AG02"
    origins = {p["origine"] for p in cat["AG01"]["modele"]["parametres"]}
    assert origins == set(am.ORIGINS)


def test_param_sheet_accepts_sales_and_rejects_bad_parameters():
    assert am.AG01.check(load("sales")) == []
    bad = replace(cfg(), forecast={"kpis": ["inconnu"]}, analysis={"kpis": ["absent"]},
                  perception={"max_lag_months": -1})
    issues = am.AG01.check(bad)
    assert any("suivi inconnu" in x for x in issues) and not any("prévoir" in x for x in issues)
    assert any("max_lag_months" in x for x in issues) and all(x.startswith("AG01 : ") for x in issues)
    assert am.MODELS["AG02"].check(bad) == ["AG02 : KPI à prévoir inconnu : inconnu"]   # paramètres de prévision : AG02
    assert am.MODELS["AG02"].check(load("sales")) == []
    snap = dict(kpis=[{**cfg().kpis[0], "grain": "instantane"}])
    assert any("non mensuel" in x for x in am.MODELS["AG02"].check(replace(cfg(), **snap)))   # contrôle de prévision
    assert am.AG01.check(replace(cfg(), **snap)) == []
    assert any("obligatoire absent : rules" in x for x in am.AG01.check({"sources": {}, "kpis": []}))


def test_team_config_validates_perception_block():
    cf = load("sales")
    assert cf.perception["max_lag_months"] == 1 and cf.perception["status"] == "a_valider"
    data = {name: copy.deepcopy(getattr(cf, name)) for name in cf.__dataclass_fields__}
    data["perception"] = {"max_lag_months": "1"}
    assert any("max_lag_months" in x for x in validate(data))
    data["perception"] = {"max_lag_months": 1, "status": "officiel"}
    assert any("perception : statut" in x for x in validate(data))


def test_fresh_data_passes_gate_and_results_unchanged():
    src = Source()
    r, out = cycle(src)
    assert out["statut"] == "termine" and out["kpi_ecartes"] == {} and src.calls == 1
    [f] = out["etapes"]["perception"]["findings"]
    assert f["kind"] == "constat" and f["value"] == 36 and f["period"] == "2026-10"
    assert "retard 0 mois" in f["detail"] and f["detail"].endswith("exploitable") and f["evidence"]["tool"] == "test"
    assert out["etapes"]["analyst"]["findings"][0]["value"] == 50
    ag01 = out["categories"]["AG01"]
    assert ag01["statut"] == "reussi" and list(ag01["fonctions"]) == list(am.AG01.functions)
    assert set(out["categories"]) == {"AG01", "AG02", "AG03", "AG06"}
    assert out["categories"]["AG02"]["statut"] == "reussi"
    assert r.steps(out["run_id"])[0]["agent"] == "perception"


def test_stale_kpi_blocked_technical_only_no_business_alert():
    src = Source(last="2026-07")          # dernier mois complet : 2026-10 -> 3 mois de retard, tolérance 1
    r, out = cycle(src)
    assert out["statut"] == "partiel" and src.calls == 1
    assert "retard de 3 mois" in out["kpi_ecartes"]["x"]
    st = out["etapes"]
    assert st["perception"]["status"] == "echec" and st["perception"]["findings"][0]["detail"].endswith("écarté")
    assert st["analyst"]["status"] == "reussi" and st["analyst"]["findings"] == []
    assert "écarté(s) par la perception" in st["analyst"]["summary"]
    assert st["prediction"]["forecasts"] == [] and st["prediction"]["errors"] == []
    assert out["alerting"]["regles"]["R"]["statut"] == "non_evalue"
    alerts = r.alerts("test")
    assert alerts and all(x["kind"] == "technique" for x in alerts)
    assert [x["rule_id"] for x in alerts] == ["TECH_EIA_PERCEPTION"]
    assert st["advisor"]["recommendations"] == [] and out["missions_apercu"] == []


def test_without_tolerance_stale_data_is_reported_not_blocked():
    src = Source(last="2026-07")
    _, out = cycle(src, replace(cfg(), perception={}))
    assert out["kpi_ecartes"] == {} and out["etapes"]["perception"]["status"] == "reussi"
    assert "retard 3 mois" in out["etapes"]["perception"]["findings"][0]["detail"]
    assert "tolérance de retard non configurée" in out["etapes"]["perception"]["summary"]
    assert out["etapes"]["analyst"]["findings"]


def test_source_failure_blocked_once_and_technical():
    src = Source(fail=True)
    r, out = cycle(src)
    assert src.calls == 1 and "source indisponible" in out["kpi_ecartes"]["x"]
    assert all(x["kind"] == "technique" for x in r.alerts("test"))
    assert out["etapes"]["analyst"]["errors"] == [] and out["etapes"]["perception"]["findings"] == []


def test_missing_month_reported_without_blocking():
    _, out = cycle(GapSource())
    f = out["etapes"]["perception"]["findings"][0]
    assert "1 mois manquant(s)" in f["detail"] and "2026-06" in f["detail"] and f["detail"].endswith("exploitable")
    assert out["kpi_ecartes"] == {}


def test_same_model_reused_for_another_domain():
    """Même code AG01, configuration d'un autre métier : seul le paramétrage change."""
    base = cfg()
    kpi_m = {**base.kpis[0], "id": "taux_dispo", "label": "Taux de disponibilité des équipements"}
    kpi_i = {**base.kpis[0], "id": "stock", "label": "Stock de pièces", "grain": "instantane", "unit": "pièces"}
    rule = {**base.rules[0], "kpi": "taux_dispo"}
    other = replace(base, team_id="maintenance", kpis=[kpi_m, kpi_i], rules=[rule],
                    analysis={"kpis": ["taux_dispo", "stock"]}, forecast={"kpis": ["taux_dispo"]},
                    playbooks=[], perception={"max_lag_months": 2})
    assert am.AG01.check(other) == [] and am.perceived_kpis(other) == ["stock", "taux_dispo"]

    class Mixed(Source):
        def fetch(self, cfg, metric, today):
            if metric == "stock":
                self.calls += 1
                return KpiData(cfg.kpi(metric), [{"period": "2026-11-24", "dimension": "", "value": 120}],
                               c.Evidence(tool="test", source="synthetique", query="instantané"))
            return super().fetch(cfg, metric, today)

    src = Mixed()
    res, blocked = a.perception(other, a.CachedSource(src), TODAY)
    assert blocked == {} and res.status == "reussi" and src.calls == 2
    details = {f.title: f.detail for f in res.findings}
    assert "date de situation 2026-11-24, retard 0 mois" in details["Qualité de la donnée - Stock de pièces"]
    assert "retard 0 mois" in details["Qualité de la donnée - Taux de disponibilité des équipements"]
    assert c.validate_result(res) == []


def _snapshot_cfg(grain):
    base = cfg()
    kd = {**base.kpis[0], "id": "snap", "label": "Instantané", "grain": grain}
    return replace(base, kpis=[*base.kpis, kd], analysis={"kpis": ["x", "snap"]})


class SnapSource(Source):
    def __init__(self, period, **kw):
        super().__init__(**kw)
        self.period = period

    def fetch(self, cfg, metric, today):
        if metric != "snap":
            return super().fetch(cfg, metric, today)
        self.calls += 1
        return KpiData(cfg.kpi(metric), [{"period": self.period, "dimension": "", "value": 7}],
                       c.Evidence(tool="test", source="synthetique", query="instantané"))


def test_stale_snapshot_blocked_with_same_tolerance():
    _, out = cycle(SnapSource("2026-08-31"), _snapshot_cfg("instantane"))   # 2 mois de retard, tolérance 1
    assert list(out["kpi_ecartes"]) == ["snap"] and "retard de 2 mois" in out["kpi_ecartes"]["snap"]
    assert [f["value"] for f in out["etapes"]["analyst"]["findings"]] == [50]      # x reste analysé
    _, ok = cycle(SnapSource("2026-10-30"), _snapshot_cfg("instantane"))
    assert ok["kpi_ecartes"] == {}


def test_dimension_and_unreadable_snapshot_not_controlled_but_reported():
    _, out = cycle(SnapSource("Campagne A"), _snapshot_cfg("dimension"))
    det = {f["title"]: f["detail"] for f in out["etapes"]["perception"]["findings"]}
    assert "KPI par dimension" in det["Qualité de la donnée - Instantané"] and out["kpi_ecartes"] == {}
    _, out = cycle(SnapSource("inconnue"), _snapshot_cfg("instantane"))
    det = {f["title"]: f["detail"] for f in out["etapes"]["perception"]["findings"]}
    assert "date de situation illisible" in det["Qualité de la donnée - Instantané"] and out["kpi_ecartes"] == {}


def test_gated_source_only_blocks_listed_kpis():
    src = a.CachedSource(Source())
    gated = a.GatedSource(src, {"autre": "motif"})
    assert gated.fetch(cfg(), "x", TODAY).points and gated.calls == 1
    try:
        gated.fetch(cfg(), "autre", TODAY)
        raise AssertionError("KPI bloqué lu")
    except a.PerceptionBlocked as err:
        assert "motif" in str(err) and gated.calls == 1
