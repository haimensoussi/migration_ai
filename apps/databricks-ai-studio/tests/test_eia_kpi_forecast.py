"""Tests EIA étape 2 : séries KPI, prévision testée sur l'historique, outils eia_kpi et eia_forecast."""
import datetime as dt
import math
import random

import pytest

from backend.eia import contracts as c
from backend.eia import forecast as F
from backend.eia import kpi as K
from backend.eia import team_config as tc
from backend.tool_registry import ToolContext, ToolError, ToolPermissionError, ToolRegistry, resolve_executor, validate_args
from tools import eia_kpi_tools as T

SCOPE = ("dataops_dev", "ai_studio", "data_")
SEASON = [80, 85, 100, 95, 90, 105, 70, 50, 95, 110, 120, 140]     # nov. -> oct. (profil arbitraire)


def months(start, n):
    return [K.month_add(start, i) for i in range(n)]


# ---------------- séries ----------------

def test_period_normalisation_and_month_arithmetic():
    assert K.norm_period("2026-10-01T00:00:00.000Z", "mois") == "2026-10"
    assert K.norm_period("2026-10-31", "instantane") == "2026-10-31"
    assert K.norm_period("Campagne A", "dimension") == "Campagne A"
    assert K.month_add("2026-11", 2) == "2027-01" and K.month_add("2026-01", -1) == "2025-12"
    assert K.month_add("2026-03", -12) == "2025-03"


def test_points_conversion_counts_empty_values():
    rows = [{"period": "2026-02-01", "value": "10.5"}, {"period": "2026-01-01", "value": "4"},
            {"period": "2026-03-01", "value": None}, {"period": "2026-04-01", "value": "NaN"}]
    pts, empty = K.to_points(rows, "mois")
    assert [p["period"] for p in pts] == ["2026-01", "2026-02"] and pts[1]["value"] == 10.5 and empty == 2


def test_incomplete_and_missing_months():
    pts = [{"period": p, "dimension": "", "value": 1.0} for p in ("2026-09", "2026-10", "2026-11")]
    kept, dropped = K.drop_incomplete(pts, dt.date(2026, 11, 23))
    assert [p["period"] for p in kept] == ["2026-09", "2026-10"] and dropped == ["2026-11"]
    assert K.missing_months(["2026-01", "2026-04", "2026-02"]) == ["2026-03"]


def test_compare_additive_kpi():
    s = {p: 100.0 for p in months("2025-01", 12)} | {p: 110.0 for p in months("2026-01", 12)}
    s["2026-12"] = 99.0
    r = K.compare(s, window=1)
    assert r["periode"] == "2026-12" and r["variation_mensuelle_pct"] == -10.0 and r["variation_annuelle_pct"] == -1.0
    r3 = K.compare(s, window=3)
    assert r3["fenetre"] == "2026-10..2026-12" and r3["valeur_fenetre"] == 319 and r3["valeur_fenetre_n_1"] == 300
    assert r3["variation_annuelle_pct"] == pytest.approx(6.33) and r3["agregation_fenetre"] == "somme"


def test_compare_rate_kpi_uses_points_and_mean():
    s = {"2025-11": 40.0, "2025-12": 42.0, "2026-11": 37.0, "2026-12": 38.0}
    r = K.compare(s, window=2, unit="%")
    assert r["agregation_fenetre"] == "moyenne" and r["variation_annuelle_points"] == -3.5
    assert "variation_annuelle_pct" not in r and "moyenne simple" in r["note"]


def test_compare_reports_missing_history():
    r = K.compare({"2026-11": 1.0, "2026-12": 2.0}, window=1)
    assert "variation_annuelle_pct" not in r and "impossible" in r["note"]


# ---------------- prévision ----------------

def test_perfect_seasonal_series_is_predicted_exactly():
    ps, vs = months("2024-11", 24), SEASON * 2
    run = F.forecast(ps, [float(v) for v in vs], horizon=3)
    f = run.forecast
    assert f.method == "naif_saisonnier" and f.backtest_error_pct == 0 and f.reliable
    assert [(p.period, p.value) for p in f.points] == [("2026-11", 80), ("2026-12", 85), ("2027-01", 100)]
    assert all(p.lower == p.value == p.upper for p in f.points)          # erreur de test nulle -> plage nulle
    assert set(run.backtests) == set(F.METHODS)


def test_growing_seasonal_series_selects_trend_method():
    vs = [v * 1.0 for v in SEASON] + [v * 1.2 for v in SEASON]
    f = F.forecast(months("2024-11", 24), vs, horizon=2).forecast
    assert f.method == "saisonnier_tendance" and f.backtest_error_pct == 0 and f.baseline_error_pct > 10
    assert f.points[0].value == pytest.approx(80 * 1.2 * 1.2)


def test_noisy_series_is_flagged_unreliable():
    rnd = random.Random(7)
    vs = [100 * (1 + rnd.uniform(-0.6, 0.6)) for _ in range(24)]
    f = F.forecast(months("2024-11", 24), vs, horizon=3, max_error_pct=5).forecast
    assert not f.reliable and "Non fiable" in f.reliability_note and f.backtest_error_pct > 5
    assert all(p.lower <= p.value <= p.upper for p in f.points) and all(p.lower >= 0 for p in f.points)


def test_short_history_cannot_be_declared_reliable():
    f = F.forecast(months("2026-06", 5), [10.0, 11, 12, 13, 14], horizon=2).forecast
    assert f.method == "moyenne_mobile_3" and f.backtest_error_pct is None and not f.reliable
    assert "trop court" in f.reliability_note and f.points[0].lower is None


@pytest.mark.parametrize("periods, values, horizon, msg", [
    (["2026-01", "2026-03", "2026-04"], [1.0, 2, 3], 1, "discontinue"),
    (months("2025-01", 24), [1.0] * 24, 13, "Horizon invalide"),
    (months("2025-01", 2), [1.0, 2], 1, "insuffisant"),
    (months("2025-01", 3), [1.0, 2], 1, "longueurs"),
])
def test_forecast_rejects_bad_inputs(periods, values, horizon, msg):
    with pytest.raises(F.ForecastError, match=msg):
        F.forecast(periods, values, horizon=horizon)


def test_forecast_satisfies_agent_contract():
    run = F.forecast(months("2024-11", 24), [float(v) for v in SEASON * 2], horizon=3, metric="m",
                     evidence=c.Evidence(tool="eia_forecast", query="SELECT 1"))
    assert c.validate_result(c.AgentResult(agent="prediction", status="reussi", forecasts=[run.forecast])) == []


# ---------------- outils ----------------

class FakeSql:
    """Répond selon la table interrogée ; valeurs en texte comme l'API SQL."""

    def __init__(self, rows_by_kpi, truncated=False):
        self.rows_by_kpi, self.truncated, self.calls = rows_by_kpi, truncated, []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append(statement)
        for marker, rows in self.rows_by_kpi.items():
            if marker in statement:
                return {"columns": ["period", "value"], "rows": rows, "truncated": self.truncated}
        return {"columns": [], "rows": [], "truncated": False}


CFG = tc.load("sales", data_scope=SCOPE)
MONTHLY = [{"period": f"{p}-01", "value": str(float(v))} for p, v in zip(months("2024-11", 24), SEASON * 2)]
REGIONS = [{"period": f"{p}-01", "dimension": d, "value": str(v * (1.0 if p < "2025-11" else f))}
           for d, f in (("NAQ", 0.8), ("IDF", 1.1)) for p, v in zip(months("2024-11", 24), SEASON * 2)]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(T.app_config, "data_scope", lambda: SCOPE)
    monkeypatch.setattr(T, "_today", lambda: dt.date(2026, 11, 23))


def ctx(sql, allowed=None):
    return ToolContext(sql=sql, workspace=None, allowed_tables=allowed or [])


def test_eia_kpi_runs_the_configured_query_and_returns_evidence():
    sql = FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY})
    r = T.eia_kpi(ctx(sql), "sales", "ca_ht")
    assert sql.calls == [CFG.kpi_sql("ca_ht")]                         # SQL de la configuration, pas du modèle
    [res] = r["resultats"]
    assert res["periode"] == "2026-10" and res["valeur"] == 140 and res["variation_annuelle_pct"] == 0.0
    assert len(r["serie"]) == 13 and r["serie"][-1] == {"dimension": "", "periode": "2026-10", "valeur": 140.0}
    [f] = r["constats"]
    assert f["id"] == res["constat_id"] and f["evidence"]["tool"] == "eia_kpi"
    assert r["preuve"]["source"] == "dataops_dev.ai_studio.data_sales_orders" and r["definition"]["exclusions"]


def test_eia_kpi_by_dimension_and_filter():
    sql = FakeSql({"region AS dimension": REGIONS})
    r = T.eia_kpi(ctx(sql), "sales", "ca_ht_region", window_months=3, last_n=2)
    got = {x["dimension"]: x["variation_annuelle_pct"] for x in r["resultats"]}
    assert got == {"IDF": 10.0, "NAQ": -20.0} and len(r["serie"]) == 4 and len(r["constats"]) == 2
    one = T.eia_kpi(ctx(sql), "sales", "ca_ht_region", dimension="naq", window_months=3)
    assert [x["dimension"] for x in one["resultats"]] == ["NAQ"]
    with pytest.raises(ToolError, match="inconnue"):
        T.eia_kpi(ctx(sql), "sales", "ca_ht_region", dimension="Bretagne")


def test_eia_kpi_excludes_current_month():
    rows = MONTHLY + [{"period": "2026-11-01", "value": "3"}]
    r = T.eia_kpi(ctx(FakeSql({"SUM(total_amount_ht) AS value FROM": rows})), "sales", "ca_ht")
    assert r["resultats"][0]["periode"] == "2026-10" and r["notes_donnees"]["mois_exclus_incomplets"] == ["2026-11"]


def test_eia_kpi_errors():
    sql = FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY})
    with pytest.raises(ToolError, match="KPI disponibles"):
        T.eia_kpi(ctx(sql), "sales", "inconnu")
    with pytest.raises(ToolError, match="Configuration"):
        T.eia_kpi(ctx(sql), "absente", "ca_ht")
    with pytest.raises(ToolPermissionError, match="hors des connaissances"):
        T.eia_kpi(ctx(sql, allowed=["dataops_dev.ai_studio.data_customers"]), "sales", "ca_ht")
    with pytest.raises(ToolError, match="tronqu"):
        T.eia_kpi(ctx(FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY}, truncated=True)), "sales", "ca_ht")
    with pytest.raises(ToolError, match="Aucune valeur"):
        T.eia_kpi(ctx(FakeSql({})), "sales", "ca_ht")


def test_eia_forecast_end_to_end():
    sql = FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY})
    r = T.eia_forecast(ctx(sql), "sales", "ca_ht")
    p = r["prevision"]
    assert p["horizon"] == 3 and p["reliable"] and p["method"] == "naif_saisonnier"
    assert [x["periode"] for x in r["comparaison_n_1"]] == ["2026-11", "2026-12", "2027-01"]
    assert r["comparaison_n_1"][0] == {"periode": "2026-11", "prevu": 80.0, "n_1": 80.0, "variation_pct": 0.0}
    assert r["total_horizon"] == {"prevu": 265.0, "n_1": 265.0, "variation_pct": 0.0}
    assert p["evidence"]["tool"] == "eia_forecast" and set(r["tests_methodes"]) == set(F.METHODS)
    assert T.eia_forecast(ctx(sql), "sales", "ca_ht", horizon=1)["prevision"]["horizon"] == 1


def test_eia_forecast_only_on_configured_monthly_kpis():
    sql = FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY})
    with pytest.raises(ToolError, match="non prévue"):
        T.eia_forecast(ctx(sql), "sales", "taux_gain")
    short = FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY[:2]})
    with pytest.raises(ToolError, match="impossible"):
        T.eia_forecast(ctx(short), "sales", "ca_ht")
    gap = FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY[:5] + MONTHLY[6:]})
    with pytest.raises(ToolError, match="discontinue"):
        T.eia_forecast(ctx(gap), "sales", "ca_ht")


def test_tool_specs_are_valid_and_resolvable():
    reg = ToolRegistry(T.EIA_KPI_TOOLS)
    assert set(reg.specs) == {"eia_kpi", "eia_forecast"} and all(s.read_only for s in T.EIA_KPI_TOOLS)
    for s in T.EIA_KPI_TOOLS:
        assert callable(resolve_executor(s.executor)) and s.tool_id in CFG.tools
    assert validate_args(reg.specs["eia_kpi"].input_schema, {"team_id": "sales", "kpi_id": "ca_ht", "last_n": 99})["last_n"] == 36
    with pytest.raises(ToolError):
        validate_args(reg.specs["eia_forecast"].input_schema, {"team_id": "sales", "kpi_id": "ca_ht", "query": "x"})
    sql = FakeSql({"SUM(total_amount_ht) AS value FROM": MONTHLY})
    out = reg.run(reg.specs["eia_forecast"], ctx(sql), {"team_id": "sales", "kpi_id": "ca_ht", "horizon": 2})
    assert len(out["prevision"]["points"]) == 2 and not math.isnan(out["prevision"]["points"][0]["value"])
