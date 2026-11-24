"""Services des pages Missions / Notifications (backend.eia.console) : dépôt en mémoire, sans SQL ni envoi."""
import datetime as dt
from dataclasses import replace

import pytest

from backend.eia import console as cs, contracts as c, engine as e, kpi as k
from backend.eia.alerting import KpiData
from backend.eia.store import EiaRepository, MemoryEiaStore
from backend.eia.team_config import load

TODAY = dt.date(2026, 11, 24)
USER = "responsable@example.test"


def cfg(notifications=None):
    base = load("sales")
    kd = {"id": "x", "label": "Indicateur X", "grain": "mois", "unit": "%", "direction": "hausse_favorable",
          "sql": "SELECT 1", "formula": "Synthétique", "exclusions": "", "limits": "Test"}
    rule = {"id": "R", "label": "Sous le seuil", "kpi": "x", "type": "seuil_bas", "window_months": 1,
            "thresholds": {"attention": 90, "critique": 75}, "status": "a_valider", "owner_role": "Responsable"}
    pb = {"id": "PB", "title": "Diagnostic", "rationale": "Analyser", "rules": ["R"], "success_kpis": ["x"],
          "status": "a_valider", "owner_role": "Responsable",
          "tasks": [{"title": "Analyser", "required_skills": [{"skill": "analyse_donnees", "level": 3}],
                     "estimated_hours": 8, "due_in_days": 14, "deliverable": "Diagnostic"},
                    {"title": "Revoir", "depends_on": [0], "required_skills": [{"skill": "analyse_donnees", "level": 3}],
                     "estimated_hours": 4, "due_in_days": 21, "deliverable": "Décision"}]}
    return replace(base, team_id="test", kpis=[kd], rules=[rule], analysis={"kpis": ["x"]}, playbooks=[pb],
                   forecast={"kpis": ["x"], "horizon": 3, "season_length": 12, "test_points": 6},
                   notifications=notifications if notifications is not None else base.notifications)


class Source:
    def fetch(self, cfg, metric, today):
        return KpiData(cfg.kpi(metric), [{"period": k.month_add("2026-10", i - 35), "dimension": "", "value": 50}
                                      for i in range(36)], c.Evidence(tool="test", source="synthetique", query="q"))


@pytest.fixture
def world():
    r = EiaRepository(MemoryEiaStore())
    r.upsert_person({"person_id": "P", "team_id": "test", "full_name": "Personne fictive", "job_title": "Analyste",
                     "department": "Test", "availability_pct": 100, "capacity_hours_week": 35, "status": "actif"},
                    {"analyse_donnees": 5}, "test")
    out = e.run_cycle(cfg(), Source(), r, today=TODAY, actor=USER)
    rid = out["etapes"]["advisor"]["recommendations"][0]["id"]
    return r, out, rid


def test_open_recommendations_then_draft_links_mission(world):
    r, _, rid = world
    recos = cs.open_recommendations(r, "test")
    assert [x["reco_id"] for x in recos] == [rid] and recos[0]["mission_id"] is None
    mid = e.prepare_mission(cfg(), r, rid, USER, today=TODAY, source=Source())["mission_id"]
    recos = cs.open_recommendations(r, "test")
    assert recos[0]["mission_id"] == mid and recos[0]["mission_status"] == "brouillon"


def test_detail_actions_follow_contract(world):
    r, _, rid = world
    mid = e.prepare_mission(cfg(), r, rid, USER, today=TODAY, source=Source())["mission_id"]
    d = cs.mission_detail(r, "test", mid)
    assert [a["target"] for a in d["actions"]] == ["validee", "annulee"]
    assert d["hours"] == 12 and d["done"] == 0 and d["tasks"][1]["depends_on_titles"] == ["Analyser"]
    # brouillon : tâches bloquées, confirmation d'affectation indisponible (refus possible)
    assert all(not a["allowed"] for t in d["tasks"] for a in t["actions"])
    acts = {a["target"]: a for a in d["tasks"][0]["assignments"][0]["actions"]}
    assert not acts["confirmee"]["allowed"] and acts["refusee"]["allowed"]


def test_full_flow_through_console_and_closure_guard(world):
    r, _, rid = world
    mid = e.prepare_mission(cfg(), r, rid, USER, today=TODAY, source=Source())["mission_id"]
    cs.decide(r, "test", USER, mid, "mission", "validee")
    m = r.s.get("eia_missions", {"mission_id": mid})
    assert m["status"] == "validee" and m["validated_by"] == USER
    d = cs.mission_detail(r, "test", mid)
    aid = d["tasks"][0]["assignments"][0]["assignment_id"]
    cs.decide(r, "test", USER, mid, "affectation", "confirmee", assignment_id=aid)
    assert r.s.get("eia_assignments", {"assignment_id": aid})["decided_by"] == USER
    cs.decide(r, "test", USER, mid, "mission", "en_cours")
    close = {a["target"]: a for a in cs.mission_detail(r, "test", mid)["actions"]}["terminee"]
    assert not close["allowed"] and "2 tâche(s)" in close["reason"]
    with pytest.raises(c.ContractError, match="tâches sont encore ouvertes"):
        cs.decide(r, "test", USER, mid, "mission", "terminee")
    for t in r.tasks(mid):
        cs.decide(r, "test", USER, mid, "tache", "en_cours", task_id=t["task_id"])
        cs.decide(r, "test", USER, mid, "tache", "fait", task_id=t["task_id"])
    cs.decide(r, "test", USER, mid, "mission", "terminee")
    assert r.s.get("eia_missions", {"mission_id": mid})["status"] == "terminee"


@pytest.mark.parametrize("user", ["agent:planner", "", "sans-arobase"])
def test_decisions_require_identified_human(world, user):
    r, _, rid = world
    mid = e.prepare_mission(cfg(), r, rid, USER, today=TODAY, source=Source())["mission_id"]
    with pytest.raises(c.ContractError):
        cs.decide(r, "test", user, mid, "mission", "validee")
    alert = r.alerts("test")[0]
    with pytest.raises(c.ContractError):
        cs.decide_alert(r, "test", user, alert["alert_id"], "acquittee")
    assert r.s.get("eia_missions", {"mission_id": mid})["status"] == "brouillon"


def test_other_team_and_foreign_assignment_rejected(world):
    r, _, rid = world
    mid = e.prepare_mission(cfg(), r, rid, USER, today=TODAY, source=Source())["mission_id"]
    with pytest.raises(c.ContractError, match="autre équipe"):
        cs.decide(r, "sales", USER, mid, "mission", "validee")
    with pytest.raises(c.ContractError, match="autre mission"):
        cs.decide(r, "test", USER, mid, "affectation", "refusee", assignment_id="as_inconnu")
    alert = r.alerts("test")[0]
    with pytest.raises(c.ContractError, match="autre équipe"):
        cs.decide_alert(r, "sales", USER, alert["alert_id"], "vue")


def test_alert_summary_separates_technical_and_actions(world):
    r, _, _ = world
    alerts = r.alerts("test")
    tech = {**alerts[0], "alert_id": "t1", "kind": "technique", "severity": "critique", "status": "nouvelle"}
    s = cs.alert_summary(alerts + [tech])
    assert s["ouvertes_metier"] == len(alerts) == 1 and s["critiques_metier"] == 1 and s["ouvertes_techniques"] == 1
    aid = alerts[0]["alert_id"]
    assert [a["target"] for a in cs.alert_actions(alerts[0])] == ["vue", "acquittee", "resolue"]
    cs.decide_alert(r, "test", USER, aid, "acquittee")
    row = r.s.get("eia_alerts", {"alert_id": aid})
    assert row["status"] == "acquittee" and row["decided_by"] == USER
    assert cs.alert_summary(r.alerts("test"))["ouvertes_metier"] == 0


def test_notification_status_never_sends_and_previews(world):
    r, _, _ = world
    off = cs.notification_status(cfg(notifications={}), r.alerts("test"), TODAY)
    assert not off["envoi_actif"] and "aucun canal" in off["motif"] and off["eligibles"] == 1
    assert off["apercu_sujet"].startswith("[DISCOVERY]") and "1 nouvelle(s) alerte(s), dont 1 critique(s)" in off["apercu_sujet"]
    assert "à valider" in off["apercu_corps"]


def test_runs_listed(world):
    r, out, _ = world
    assert [x["run_id"] for x in cs.runs(r, "test")] == [out["run_id"]]
