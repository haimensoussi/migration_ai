"""Tests EIA étape 3 : moteur d'alerting indépendant, adaptateurs SQL et Power Automate."""
import copy
import datetime as dt
import json
import os
import random

import pytest

from backend.eia import adapters as ad
from backend.eia import alerting as al
from backend.eia import contracts as c
from backend.eia import kpi as K
from backend.eia import store as st
from backend.eia import team_config as tc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPE = ("dataops_dev", "ai_studio", "data_")
TODAY = dt.date(2026, 11, 23)
SEASON = [80, 85, 100, 95, 90, 105, 70, 50, 95, 110, 120, 140]
MONTHS = [K.month_add("2024-11", i) for i in range(24)]


def sales_dict():
    with open(os.path.join(ROOT, "config", "teams", "sales.json"), encoding="utf-8") as f:
        return json.load(f)


def cfg(rules=("SAL_R01", "SAL_R02", "SAL_R03", "SAL_R06"), notifications=None):
    d = sales_dict()
    d["rules"] = [r for r in d["rules"] if r["id"] in rules]
    if notifications is not None:
        d["notifications"] = notifications
    return tc.from_dict(d, SCOPE)


def monthly(factor_last_year=1.0, dim=""):
    """24 mois : 1re année = SEASON, 2e année = SEASON x facteur."""
    return [{"period": p, "dimension": dim, "value": v * (1 if i < 12 else factor_last_year)}
            for i, (p, v) in enumerate(zip(MONTHS, SEASON * 2))]


class FakeSource:
    def __init__(self, points_by_kpi, fail=()):
        self.points, self.fail, self.calls = points_by_kpi, set(fail), []

    def fetch(self, cfg_, kpi_id, today):
        self.calls.append(kpi_id)
        if kpi_id in self.fail:
            raise RuntimeError("warehouse indisponible")
        return al.KpiData(cfg_.kpi(kpi_id), self.points[kpi_id], c.Evidence(tool="eia_alerting", query=f"SQL {kpi_id}"))


DATA = {
    "ca_ht": monthly(0.9),                                                 # -10 % sur un an -> attention (seuil -5)
    "ca_ht_region": monthly(0.75, "NAQ") + monthly(1.1, "IDF"),           # NAQ -25 % -> critique (-20) ; IDF rien
    "atteinte_objectif": [{"period": p, "dimension": "", "value": 80.0} for p in MONTHS],   # 80 <= 90 -> attention
    "opportunites_bloquees": [{"period": "2026-10-31", "dimension": "", "value": 181.0}],  # >= 150 -> critique
}


def repo():
    ticks = iter(f"2026-11-23 07:{i // 60:02d}:{i % 60:02d}" for i in range(3600))
    return st.EiaRepository(st.MemoryEiaStore(), clock=lambda: next(ticks))


# ---------------- seuils ----------------

@pytest.mark.parametrize("value, rtype, expected", [
    (-12.0, "variation_annuelle", ("attention", -5.0)), (-15.0, "variation_annuelle", ("critique", -15.0)), (-25.0, "variation_annuelle", ("critique", -15.0)),
    (-4.9, "variation_annuelle", None), (-5.0, "variation_annuelle", ("attention", -5.0)),
    (160.0, "seuil_haut", ("critique", 150.0)), (49.0, "seuil_haut", None), (80.0, "seuil_bas", ("attention", 90.0)),
])
def test_breach(value, rtype, expected):
    th = {"attention": -5, "critique": -15} if rtype == "variation_annuelle" else \
        {"attention": 50, "critique": 150} if rtype == "seuil_haut" else {"attention": 90, "critique": 75}
    assert al.breach(value, rtype, th) == expected


# ---------------- exécution ----------------

def test_business_alerts_are_computed_from_rules_with_evidence():
    r = repo()
    rep = al.run_alerting(cfg(), FakeSource(DATA), r, today=TODAY)
    got = {(a["rule_id"], a["scope"]): (a["severity"], a["observed"]) for a in rep["nouvelles"]}
    assert got == {("SAL_R01", ""): ("attention", -10.0), ("SAL_R02", "NAQ"): ("critique", -25.0),
                   ("SAL_R03", ""): ("attention", 80.0), ("SAL_R06", ""): ("critique", 181.0)}
    assert rep["statut"] == "termine" and rep["techniques"] == []
    for a in rep["nouvelles"]:
        assert a["kind"] == "metier" and a["rule_status"] == "a_valider" and "seuil à valider" in a["message"]
        assert a["evidence"]["query"].startswith("SQL ")
    alerts = [c.Alert(**{k_: v for k_, v in a.items() if k_ not in ("evidence", "alert_id")},
                      evidence=c.Evidence(**a["evidence"])) for a in rep["nouvelles"]]
    assert c.validate_result(c.AgentResult(agent="alerting", status="reussi", alerts=alerts)) == []
    [run] = r.s.find("eia_runs")
    assert run["status"] == "termine" and run["trigger"] == "planifie" and "4 nouvelle(s)" in run["summary"]
    assert r.steps(rep["run_id"])[0]["status"] == "reussi"


def test_same_situation_is_not_alerted_twice():
    r = repo()
    al.run_alerting(cfg(), FakeSource(DATA), r, today=TODAY)
    rep2 = al.run_alerting(cfg(), FakeSource(DATA), r, today=TODAY + dt.timedelta(days=1))
    assert rep2["nouvelles"] == [] and len(rep2["deja_connues"]) == 4
    assert {a["occurrences"] for a in r.alerts("sales")} == {2} and len(r.alerts("sales")) == 4


def test_source_failure_is_a_technical_alert_and_other_rules_continue():
    r = repo()
    rep = al.run_alerting(cfg(), FakeSource(DATA, fail={"ca_ht_region"}), r, today=TODAY)
    [t] = rep["techniques"]
    assert t["kind"] == "technique" and t["rule_id"] == "TECH_SOURCE" and "warehouse indisponible" in t["message"]
    assert {a["rule_id"] for a in rep["nouvelles"] if a["kind"] == "metier"} == {"SAL_R01", "SAL_R03", "SAL_R06"}
    assert rep["regles"]["SAL_R02"]["statut"] == "non_evalue" and rep["statut"] == "partiel"
    assert r.s.find("eia_runs")[0]["status"] == "partiel"


def test_disabled_rule_and_missing_history_are_reported_not_alerted():
    d = cfg(rules=("SAL_R01", "SAL_R03"))
    rules = copy.deepcopy(d.rules)
    rules[1]["status"] = "desactive"
    d = tc.TeamConfig(**{**d.__dict__, "rules": rules})
    short = {"ca_ht": monthly(0.9)[-6:]}
    rep = al.run_alerting(d, FakeSource(short), repo(), today=TODAY)
    assert rep["nouvelles"] == [] and "SAL_R03" not in rep["regles"]
    assert "impossible" in rep["regles"]["SAL_R01"]["non_evalues"][0]


def test_forecast_rule_only_when_forecast_is_reliable():
    falling = {"ca_ht": [{"period": p, "dimension": "", "value": v * (0.97 ** i)}
                         for i, (p, v) in enumerate(zip(MONTHS, SEASON * 2))]}
    rep = al.run_alerting(cfg(rules=("SAL_R08",)), FakeSource(falling), repo(), today=TODAY)
    [a] = rep["nouvelles"]
    assert a["rule_id"] == "SAL_R08" and a["severity"] == "critique" and a["period"] == "2026-11..2027-01"
    assert "méthode saisonnier_tendance" in a["message"]
    rnd = random.Random(3)
    noisy = {"ca_ht": [{"period": p, "dimension": "", "value": rnd.uniform(10, 1000)} for p in MONTHS]}
    rep = al.run_alerting(cfg(rules=("SAL_R08",)), FakeSource(noisy), repo(), today=TODAY)
    assert rep["nouvelles"] == [] and "non fiable" in rep["regles"]["SAL_R08"]["non_evalues"][0]


# ---------------- envoi ----------------

NOTIF = {"channel": "power_automate", "status": "valide", "min_severity": "critique",
         "recipients": ["direction.commerciale@sncf.fr"], "technology": "outlook", "operation": "send_mail"}


def test_no_sending_without_validated_channel():
    r = repo()
    n = ad.MemoryNotifier()
    rep = al.run_alerting(cfg(), FakeSource(DATA), r, notifier=n, today=TODAY)
    assert n.sent == [] and not rep["envoi"]["envoye"] and "aucun canal" in rep["envoi"]["motif"]
    assert [e["event_type"] for e in r.events(rep["run_id"])].count("envoi_non_autorise") == 1
    rep = al.run_alerting(cfg(notifications={**NOTIF, "status": "a_valider"}), FakeSource(DATA), repo(), notifier=n,
                          today=TODAY)
    assert n.sent == [] and "non validé" in rep["envoi"]["motif"]


def test_validated_channel_sends_only_new_critical_alerts_once():
    r, n = repo(), ad.MemoryNotifier()
    conf = cfg(notifications=NOTIF)
    rep = al.run_alerting(conf, FakeSource(DATA), r, notifier=n, today=TODAY)
    [msg] = n.sent
    assert rep["envoi"]["envoye"] and len(msg["alerts"]) == 2                     # R02 NAQ et R06 (critiques)
    assert "2 nouvelle(s) alerte(s), dont 2 critique(s)" in msg["subject"] and "à valider" in msg["body"]
    assert msg["body"].index("SAL_R02") < msg["body"].index("SAL_R06")
    al.run_alerting(conf, FakeSource(DATA), r, notifier=n, today=TODAY)
    assert len(n.sent) == 1                                                        # rien de nouveau : pas de renvoi
    assert "notification_envoyee" in [e["event_type"] for e in r.events(rep["run_id"])]


def test_sending_failure_is_technical_and_alerts_are_kept():
    r = repo()
    rep = al.run_alerting(cfg(notifications=NOTIF), FakeSource(DATA), r,
                          notifier=ad.MemoryNotifier(fail=RuntimeError("HTTP 502")), today=TODAY)
    assert rep["statut"] == "partiel" and [t["rule_id"] for t in rep["techniques"]] == ["TECH_NOTIFY"]
    assert len([a for a in r.alerts("sales") if a["kind"] == "metier"]) == 4


@pytest.mark.parametrize("block, expected", [
    ({**NOTIF, "channel": "smtp"}, "channel"), ({**NOTIF, "status": "ok"}, "status"),
    ({**NOTIF, "recipients": ["pas-une-adresse"]}, "recipients"), ({**NOTIF, "operation": ""}, "sans destinataires"),
    ({**NOTIF, "min_severity": "grave"}, "min_severity"),
])
def test_notifications_block_is_validated(block, expected):
    d = sales_dict()
    d["notifications"] = block
    assert any(expected in i for i in tc.validate(d, SCOPE))


def test_power_automate_notifier_payload_and_checks():
    posted, checked = [], []
    pa = ad.PowerAutomateNotifier({**NOTIF, "recipients": ["a@sncf.fr", "b@sncf.fr"]}, post=lambda p: posted.append(p) or {"http_status": 202},
                                  check_recipients=checked.append)
    assert pa.send("Sujet", "Corps", [], "run_1") == {"http_status": 202}
    assert posted[0] == {"sessionId": "run_1", "question": "Sujet", "technology": "outlook", "operation": "send_mail",
                         "parameters": {"to": "a@sncf.fr;b@sncf.fr", "subject": "Sujet", "body": "Corps"},
                         "status": "approved", "requires_confirmation": False}
    assert checked == ["a@sncf.fr;b@sncf.fr"]
    with pytest.raises(ValueError):
        ad.PowerAutomateNotifier({**NOTIF, "status": "a_valider"}, post=print, check_recipients=print)


# ---------------- adaptateur SQL et indépendance ----------------

class FakeSql:
    def __init__(self, rows, truncated=False):
        self.rows, self.truncated, self.calls = rows, truncated, []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append(statement)
        return {"rows": self.rows, "truncated": self.truncated}


def test_sql_source_runs_configured_query_and_excludes_current_month():
    conf = cfg()
    rows = [{"period": f"{p}-01", "value": str(v)} for p, v in zip(MONTHS, SEASON * 2)] + [{"period": "2026-11-01", "value": "1"}]
    sql = FakeSql(rows)
    data = ad.SqlKpiSource(sql).fetch(conf, "ca_ht", TODAY)
    assert sql.calls == [conf.kpi_sql("ca_ht")] and data.points[-1]["period"] == "2026-10"
    assert data.notes["mois_exclus_incomplets"] == ["2026-11"] and data.evidence.source.endswith("data_sales_orders")
    with pytest.raises(ad.SourceError, match="tronqu"):
        ad.SqlKpiSource(FakeSql(rows, truncated=True)).fetch(conf, "ca_ht", TODAY)
    with pytest.raises(ad.SourceError, match="Aucune valeur"):
        ad.SqlKpiSource(FakeSql([])).fetch(conf, "ca_ht", TODAY)


def test_engine_has_no_platform_dependency():
    for name in ("alerting.py", "adapters.py", "kpi.py", "forecast.py"):
        with open(os.path.join(ROOT, "backend", "eia", name), encoding="utf-8") as f:
            imports = [l.strip() for l in f if l.strip().startswith(("import ", "from "))]
        allowed = ("from __future__", "import datetime", "import time", "import math", "import re", "from dataclasses",
                   "from typing", "from backend import sql_guard", "from backend.eia", "from tools import power_automate")
        assert [l for l in imports if not l.startswith(allowed)] == [], name
