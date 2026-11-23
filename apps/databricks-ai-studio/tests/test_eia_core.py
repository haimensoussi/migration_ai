"""Tests EIA Core (étape 1) : contrats, configuration d'équipe, persistance et règles de validation."""
import copy
import json
import os
import re

import pytest

from backend.eia import contracts as c
from backend.eia import store as st
from backend.eia import team_config as tc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPE = ("dataops_dev", "ai_studio", "data_")
USER = "analyste@sncf.fr"


def sales_dict():
    with open(os.path.join(ROOT, "config", "teams", "sales.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------------- contrats ----------------

def ev():
    return c.Evidence(tool="eia_kpi", source="orders", query="SELECT 1")


def test_ids_and_fingerprint_are_stable():
    assert re.match(r"^al_[0-9a-f]{12}$", c.new_id("al"))
    assert c.fingerprint("sales", "R1", "IDF", "2026-10") == c.fingerprint("Sales", "R1 ", "idf", "2026-10")
    assert c.fingerprint("sales", "R1", "IDF", "2026-10") != c.fingerprint("sales", "R1", "IDF", "2026-09")


def test_transitions_and_human_decisions():
    c.check_transition("mission", "brouillon", "validee", USER)
    with pytest.raises(c.ContractError):
        c.check_transition("mission", "brouillon", "validee", None)        # pas de validation sans utilisateur
    with pytest.raises(c.ContractError):
        c.check_transition("mission", "brouillon", "validee", "advisor")   # un agent ne valide pas
    with pytest.raises(c.ContractError):
        c.check_transition("mission", "brouillon", "terminee", USER)       # saut d'étape interdit
    with pytest.raises(c.ContractError):
        c.check_transition("mission", "brouillon", "inconnu", USER)
    c.check_transition("step", "echec", "en_cours")                        # reprise autorisée


def test_valid_result_passes():
    f = c.Finding(kind="kpi", title="CA", value=10.0, unit="EUR", evidence=ev())
    fc = c.Forecast(metric="ca_ht", method="naif_saisonnier", horizon=2, evidence=ev(), reliable=True,
                    backtest_error_pct=5.0, points=[c.ForecastPoint("2026-11", 10, 8, 12), c.ForecastPoint("2026-12", 11)])
    rc = c.Recommendation(title="Relancer", rationale="...", priority=1, based_on=[f.id, fc.id])
    r = c.AgentResult(agent="advisor", status="reussi", findings=[f], forecasts=[fc], recommendations=[rc])
    assert c.validate_result(r) == []


def test_invalid_results_are_reported():
    f = c.Finding(kind="kpi", title="CA inventé", value=10.0)                         # chiffre sans preuve
    fc = c.Forecast(metric="ca_ht", method="x", horizon=3, evidence=ev(), reliable=True,
                    points=[c.ForecastPoint("p", 5, 6, 7)])                             # 1 point / 3, hors bornes, fiable sans test
    al = c.Alert(rule_id="R", severity="grave", title="t", message="m")                # gravité inconnue, sans preuve
    rc = c.Recommendation(title="r", rationale="r", priority=0, based_on=["fd_inexistant"])
    m = c.Mission(title="m", objective="o", recommendation_id="", tasks=[], success_kpis=[])
    issues = c.validate_result(c.AgentResult(agent="x", status="reussi", errors=["boom"], findings=[f], forecasts=[fc],
                                             alerts=[al], recommendations=[rc], missions=[m]))
    text = " | ".join(issues)
    for expected in ("agent inconnu", "reussi avec des erreurs", "valeur sans preuve", "horizon et nombre",
                     "fiable sans test", "incohérent", "gravité inconnue", "sans valeur observée", "preuves inconnues",
                     "priorité invalide", "KPI de réussite"):
        assert expected in text, expected


def test_recommendation_may_cite_upstream_evidence():
    rc = c.Recommendation(title="r", rationale="r", priority=1, based_on=["fd_amont"])
    r = c.AgentResult(agent="advisor", status="reussi", recommendations=[rc])
    assert c.validate_result(r) != []
    assert c.validate_result(r, known_ids={"fd_amont"}) == []


def test_unreliable_forecast_needs_explanation():
    fc = c.Forecast(metric="m", method="naif", horizon=1, evidence=ev(), points=[c.ForecastPoint("p", 1)])
    assert any("sans explication" in i for i in c.validate_result(c.AgentResult(agent="prediction", status="reussi",
                                                                              forecasts=[fc])))
    fc.reliability_note = "Historique trop court"
    assert c.validate_result(c.AgentResult(agent="prediction", status="reussi", forecasts=[fc])) == []


def test_technical_alert_needs_no_observed_value():
    al = c.Alert(rule_id="TECH", severity="attention", title="Source indisponible", message="timeout", kind="technique")
    assert c.validate_result(c.AgentResult(agent="alerting", status="reussi", alerts=[al])) == []


# ---------------- configuration d'équipe ----------------

def test_sales_config_is_valid_and_generic():
    cfg = tc.load("sales", data_scope=SCOPE)
    assert cfg.name == "Sales Team" and set(cfg.agents) == set(c.AGENT_ROLES)
    assert all(r["status"] == "a_valider" for r in cfg.rules)          # aucun seuil officiel sans validation
    assert "sales" in tc.available()
    sql = cfg.kpi_sql("ca_ht")
    assert "`dataops_dev`.`ai_studio`.`data_sales_orders`" in sql and "{" not in sql


def test_agents_core_contains_no_sales_logic():
    for name in ("contracts.py", "team_config.py", "store.py"):
        with open(os.path.join(ROOT, "backend", "eia", name), encoding="utf-8") as f:
            src = f.read().lower()
        for word in ("data_sales", "sales_orders", "chiffre d'affaires", "ca_ht"):
            assert word not in src, (name, word)


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.pop("kpis"), "champ obligatoire manquant : kpis"),
    (lambda d: d.update(team_id="Sales!"), "team_id invalide"),
    (lambda d: d["sources"].update(x="autre.schema.table"), "hors zone de données"),
    (lambda d: d["sources"].update(y="dataops_dev.ai_studio.agents"), "hors zone de données"),
    (lambda d: d["kpis"][0].update(sql="DELETE FROM {orders}"), "requête refusée"),
    (lambda d: d["kpis"][0].update(sql="SELECT 1 AS period, 2 AS value FROM {inconnue}"), "sources non déclarées"),
    (lambda d: d["kpis"][0].update(sql="SELECT 1 AS period, 2 AS value FROM dataops_dev.ai_studio.agents"),
     "tables hors sources"),
    (lambda d: d["kpis"][0].update(sql="SELECT 1 AS x FROM {orders}"), "period et value"),
    (lambda d: d["kpis"].append(copy.deepcopy(d["kpis"][0])), "KPI en double"),
    (lambda d: d["rules"][0].update(kpi="absent"), "KPI inconnu"),
    (lambda d: d["rules"][0].update(status="officiel"), "statut de validation inconnu"),
    (lambda d: d["rules"][0].update(thresholds={"attention": -15, "critique": -5}), "moins sévère"),
    (lambda d: d["rules"][4].update(thresholds={"attention": 20, "critique": 10}), "moins sévère"),
    (lambda d: d["rules"][0].update(thresholds={"grave": 1}), "seuils invalides"),
    (lambda d: d["agents"].append("pirate"), "agents inconnus"),
    (lambda d: d["validation_policy"].update(mission_requires_validation=False), "mission_requires_validation"),
    (lambda d: d["validation_policy"].update(external_actions="autorise"), "external_actions"),
])
def test_invalid_configs_are_rejected(mutate, expected):
    d = sales_dict()
    mutate(d)
    issues = tc.validate(d, SCOPE)
    assert any(expected in i for i in issues), issues
    with pytest.raises(tc.TeamConfigError):
        tc.from_dict(d, SCOPE)


def test_unknown_tools_rejected_when_catalog_given():
    assert any("outils inconnus" in i for i in tc.validate(sales_dict(), SCOPE, known_tools={"execute_sql"}))


def test_render_sql_refuses_undeclared_alias():
    cfg = tc.load("sales", data_scope=SCOPE)
    with pytest.raises(tc.TeamConfigError):
        cfg.render_sql("SELECT * FROM {agents}")
    with pytest.raises(tc.TeamConfigError):
        cfg.kpi("absent")


def test_load_rejects_bad_ids_and_mismatch(tmp_path):
    with pytest.raises(tc.TeamConfigError):
        tc.load("../etc")
    with pytest.raises(tc.TeamConfigError):
        tc.load("absente", base_dir=str(tmp_path))
    d = sales_dict()
    (tmp_path / "finance.json").write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(tc.TeamConfigError):
        tc.load("finance", base_dir=str(tmp_path))                     # team_id du fichier = sales


def test_another_team_reuses_the_same_core(tmp_path):
    d = sales_dict()
    d.update(team_id="finance", name="Finance Team", agents=["analyst", "prediction"])
    (tmp_path / "finance.json").write_text(json.dumps(d), encoding="utf-8")
    cfg = tc.load("finance", base_dir=str(tmp_path), data_scope=SCOPE)
    assert cfg.agents == ["analyst", "prediction"]


# ---------------- schéma SQL <-> magasin ----------------

def test_sql_schema_matches_store_columns():
    with open(os.path.join(ROOT, "database", "eia_schema.sql"), encoding="utf-8") as f:
        ddl = f.read()
    blocks = dict(re.findall(r"CREATE TABLE IF NOT EXISTS dataops_dev\.ai_studio\.(\w+) \((.*?)\n\) COMMENT", ddl, re.S))
    assert set(blocks) == set(st.TABLES)
    # aucun point-virgule hors fin d'instruction : le fichier se découpe sans analyseur SQL
    assert [l for l in ddl.splitlines() if ";" in l and not l.rstrip().endswith(";")] == []
    assert ddl.count(";") == len(st.TABLES)
    for table, body in blocks.items():
        cols = [m.group(1) for m in re.finditer(r"^\s{2}(\w+) (STRING|INT|DOUBLE|TIMESTAMP)", body, re.M)]
        assert tuple(cols) == st.TABLES[table][1], table
        types = dict(re.findall(r"^\s{2}(\w+) (STRING|INT|DOUBLE|TIMESTAMP)", body, re.M))
        for col, kind in st.TABLES[table][2].items():
            assert types[col] == {"ts": "TIMESTAMP", "d": "DOUBLE", "i": "INT", "j": "STRING"}[kind], (table, col)


# ---------------- persistance et règles ----------------

def repo():
    ticks = iter(f"2026-11-23 10:00:{i:02d}" for i in range(60))
    return st.EiaRepository(st.MemoryEiaStore(), clock=lambda: next(ticks))


def alert(observed=-20.0):
    return {"rule_id": "R02", "severity": "critique", "title": "Région en baisse", "observed": observed,
            "threshold": -20.0, "scope": "NAQ", "period": "2026-10", "evidence": {"tool": "eia_kpi"}}


def test_alert_deduplication_and_status():
    r = repo()
    fp = c.fingerprint("t", "R02", "NAQ", "2026-10")
    a1, new1 = r.record_alert("t", "run_1", alert(), fp)
    a2, new2 = r.record_alert("t", "run_2", alert(-25.0), fp)
    assert (new1, new2) == (True, False) and a1 == a2
    rows = r.alerts("t")
    assert len(rows) == 1 and rows[0]["occurrences"] == 2 and rows[0]["observed"] == -25.0
    assert rows[0]["evidence"] == {"tool": "eia_kpi"}
    r.set_alert_status(a1, "resolue", USER)
    a3, new3 = r.record_alert("t", "run_3", alert(), fp)                # réapparition après résolution
    assert new3 and a3 != a1
    with pytest.raises(c.ContractError):
        r.set_alert_status(a1, "nouvelle", USER)


def reco_flow(r):
    run = r.start_run("t", "demande", "Analyse", USER, {"steps": []})
    [rid] = r.save_recommendations("t", run, [{"title": "Relancer", "rationale": "...", "priority": 1,
                                                "based_on": ["al_1"]}])
    return run, rid


MISSION = {"title": "Relance clients inactifs", "objective": "Réactiver", "success_kpis": ["part_clients_inactifs"]}
TASKS = [{"title": "Extraire la liste", "owner": "ADV"}, {"title": "Appeler", "owner": "Commerciaux"}]


def test_mission_requires_selected_recommendation_and_starts_as_draft():
    r = repo()
    _, rid = reco_flow(r)
    with pytest.raises(c.ContractError):
        r.create_mission_draft("t", {**MISSION, "recommendation_id": rid}, TASKS, USER)       # non sélectionnée
    r.set_recommendation_status(rid, "selectionnee", USER)
    with pytest.raises(c.ContractError):
        r.create_mission_draft("t", {**MISSION, "recommendation_id": rid, "status": "validee"}, TASKS, USER)
    with pytest.raises(c.ContractError):
        r.create_mission_draft("t", {**MISSION, "recommendation_id": rid}, [], USER)          # sans tâche
    mid = r.create_mission_draft("t", {**MISSION, "recommendation_id": rid}, TASKS, USER)
    [m] = r.missions("t")
    assert m["status"] == "brouillon" and m["validated_by"] is None and m["success_kpis"] == ["part_clients_inactifs"]
    assert len(r.tasks(mid)) == 2


def test_mission_validation_and_task_progress():
    r = repo()
    _, rid = reco_flow(r)
    r.set_recommendation_status(rid, "selectionnee", USER)
    mid = r.create_mission_draft("t", {**MISSION, "recommendation_id": rid}, TASKS, USER)
    tid = r.tasks(mid)[0]["task_id"]
    with pytest.raises(c.ContractError):
        r.set_task_status(mid, tid, "en_cours", USER)                    # mission encore en brouillon
    with pytest.raises(c.ContractError):
        r.set_mission_status(mid, "validee", "planner")                  # un agent ne valide pas
    r.set_mission_status(mid, "validee", USER)
    [m] = r.missions("t")
    assert m["status"] == "validee" and m["validated_by"] == USER and m["validated_at"]
    r.set_task_status(mid, tid, "en_cours", USER)
    r.set_task_status(mid, tid, "fait", USER)
    assert [e["event_type"] for e in r.events(mid)] == ["brouillon", "validee"]
    assert [e["event_type"] for e in r.events(tid)] == ["en_cours", "fait"]


def test_run_and_steps_lifecycle():
    r = repo()
    run, _ = reco_flow(r)
    r.save_step(run, "s1", "analyst", "en_cours", attempts=1, depends_on=[])
    r.save_step(run, "s1", "analyst", "reussi", output={"summary": "ok"}, duration_ms=1200)
    [s] = r.steps(run)
    assert s["status"] == "reussi" and json.loads(s["output"]) == {"summary": "ok"} and s["attempts"] == 1
    r.end_run(run, "termine", "Synthèse")
    with pytest.raises(c.ContractError):
        r.end_run(run, "echec")                                          # déjà terminée


def test_store_rejects_unknown_columns_and_duplicates():
    s = st.MemoryEiaStore()
    with pytest.raises(c.ContractError):
        s.insert("eia_runs", {"run_id": "r", "pirate": 1})
    with pytest.raises(c.ContractError):
        s.insert("inconnue", {})
    s.insert("eia_events", {"event_id": "e1"})
    with pytest.raises(c.ContractError):
        s.insert("eia_events", {"event_id": "e1"})


class FakeSql:
    def __init__(self, rows=None):
        self.calls, self.rows = [], rows or []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, params))
        return {"rows": self.rows}

    def execute(self, statement, params=None):
        self.calls.append((statement, params))


def test_sql_store_statements_are_parameterized_and_typed():
    sql = FakeSql()
    s = st.SqlEiaStore(sql, lambda n: f"`dataops_dev`.`ai_studio`.`{n}`")
    s.insert("eia_alerts", {"alert_id": "a", "observed": -2.5, "occurrences": 1, "first_seen_at": "2026-11-23 10:00:00",
                            "title": "x'); DROP TABLE t; --"})
    q, p = sql.calls[-1]
    assert q.startswith("INSERT INTO `dataops_dev`.`ai_studio`.`eia_alerts`") and "DROP" not in q
    assert "CAST(:v" in q and "AS DOUBLE)" in q and "AS INT)" in q and "AS TIMESTAMP)" in q
    assert "x'); DROP TABLE t; --" in p.values()
    s.update("eia_alerts", {"alert_id": "a"}, {"status": "vue"})
    q, p = sql.calls[-1]
    assert q == "UPDATE `dataops_dev`.`ai_studio`.`eia_alerts` SET status = :s0 WHERE alert_id = :k0"
    assert p == {"s0": "vue", "k0": "a"}
    s.find("eia_alerts", {"team_id": "t", "status": ["nouvelle", "vue"]}, "last_seen_at", limit=5)
    q, p = sql.calls[-1]
    assert "WHERE team_id = :w0 AND status IN (:w1_0, :w1_1) ORDER BY last_seen_at DESC LIMIT 5" in q
    assert "CAST(first_seen_at AS STRING) AS first_seen_at" in q
    with pytest.raises(c.ContractError):
        s.find("eia_alerts", order_by="1; DROP TABLE x")


def test_sql_store_converts_text_values():
    row = {"alert_id": "a", "observed": "-2.5", "occurrences": "3", "first_seen_at": "2026-11-23T10:00:00.000Z"}
    s = st.SqlEiaStore(FakeSql([row]), lambda n: n)
    out = s.get("eia_alerts", {"alert_id": "a"})
    assert out["observed"] == -2.5 and out["occurrences"] == 3 and out["first_seen_at"] == "2026-11-23 10:00:00"
