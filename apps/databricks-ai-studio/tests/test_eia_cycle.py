"""Cycle EIA : tests synthétiques sans SQL, réseau, modèle ni écriture en production."""
import copy
import datetime as dt
from dataclasses import replace

import pytest

from backend.eia import agents as a, contracts as c, engine as e, kpi as k
from backend.eia.alerting import KpiData
from backend.eia.store import EiaRepository, MemoryEiaStore
from backend.eia.team_config import load, validate
from backend.tool_registry import ToolContext, ToolRegistry, ToolError

TODAY = dt.date(2026, 11, 24)
USER = "responsable@example.test"


def cfg():
    base = load("sales")
    kd = {"id": "x", "label": "Indicateur X", "grain": "mois", "unit": "%", "direction": "hausse_favorable",
          "sql": "SELECT '2026-10' AS period, 10 AS value", "formula": "Synthétique", "exclusions": "", "limits": "Test"}
    rule = {"id": "R", "label": "Sous le seuil", "kpi": "x", "type": "seuil_bas", "window_months": 1,
            "thresholds": {"attention": 90, "critique": 75}, "status": "a_valider", "owner_role": "Responsable"}
    pb = {"id": "PB", "title": "Diagnostic", "rationale": "Analyser avant de décider", "rules": ["R"],
          "success_kpis": ["x"], "status": "a_valider", "owner_role": "Responsable",
          "tasks": [{"title": "Analyser", "required_skills": [{"skill": "analyse_donnees", "level": 3}],
                     "estimated_hours": 8, "due_in_days": 14, "deliverable": "Diagnostic"},
                    {"title": "Revoir", "depends_on": [0], "required_skills": [{"skill": "analyse_donnees", "level": 3}],
                     "estimated_hours": 4, "due_in_days": 21, "deliverable": "Décision"}]}
    return replace(base, team_id="test", kpis=[kd], rules=[rule], analysis={"kpis": ["x"]},
                   playbooks=[pb], forecast={"kpis": ["x"], "horizon": 3, "season_length": 12, "test_points": 6})


class Source:
    def __init__(self, value=50, last="2026-10", fail=False):
        self.value, self.last, self.fail, self.calls = value, last, fail, 0

    def fetch(self, cfg, metric, today):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Source synthétique indisponible")
        return KpiData(cfg.kpi(metric), [{"period": k.month_add(self.last, i - 35), "dimension": "", "value": self.value}
                                      for i in range(36)], c.Evidence(tool="test", source="synthetique", query="série constante"))


def repo():
    r = EiaRepository(MemoryEiaStore())
    r.upsert_person({"person_id": "P", "team_id": "test", "full_name": "Personne fictive", "job_title": "Analyste",
                     "department": "Test", "availability_pct": 100, "capacity_hours_week": 35, "status": "actif"}, {"analyse_donnees": 5}, "test")
    return r


def run(r=None, source=None):
    r = r or repo()
    return r, e.run_cycle(cfg(), source or Source(), r, today=TODAY, actor=USER)


def draft(r, out, source=None):
    rid = out["etapes"]["advisor"]["recommendations"][0]["id"]
    return e.prepare_mission(cfg(), r, rid, USER, today=TODAY, source=source or Source())


def close(r, mid):
    r.set_mission_status(mid, "validee", USER)
    r.set_mission_status(mid, "en_cours", USER)
    for t in r.tasks(mid):
        r.set_task_status(mid, t["task_id"], "en_cours", USER)
        r.set_task_status(mid, t["task_id"], "fait", USER)
    r.set_mission_status(mid, "terminee", USER)


def test_cycle_known_numbers_cache_and_no_automatic_decisions():
    source = Source()
    r, out = run(source=source)
    assert out["statut"] == "termine", out["erreurs"]
    assert source.calls == out["requetes_kpi"] == 1
    assert len(r.s.data["eia_runs"]) == 1 and len(r.steps(out["run_id"])) == 6
    assert out["etapes"]["analyst"]["findings"][0]["value"] == 50
    assert [p["value"] for p in out["etapes"]["prediction"]["forecasts"][0]["points"]] == [50, 50, 50]
    alerts = r.alerts("test")
    assert len(alerts) == 1 and alerts[0]["observed"] == 50 and alerts[0]["threshold"] == 75
    recos = r.recommendations("test")
    assert len(recos) == 1 and recos[0]["status"] == "proposee"
    assert recos[0]["based_on"] == [alerts[0]["alert_id"]]
    assert len(out["missions_apercu"]) == 1 and len(out["missions_apercu"][0]["tasks"]) == 2
    assert r.missions("test") == [] and r.s.data["eia_assignments"] == []
    assert out["envoi"]["envoye"] is False


def test_no_breach_no_plan():
    r, out = run(source=Source(100))
    assert out["missions_apercu"] == [] and r.recommendations("test") == []


def test_source_failure_is_technical_not_business():
    src = Source(fail=True)
    r, out = run(source=src)
    assert src.calls == 1 and out["statut"] == "partiel"
    assert out["missions_apercu"] == []
    assert r.alerts("test") and all(x["kind"] == "technique" for x in r.alerts("test"))
    assert out["alerting"]["regles"]["R"]["statut"] == "non_evalue"


def test_repeated_alert_keeps_id():
    r, first = run()
    _, second = run(r)
    assert len(r.alerts("test")) == 1 and r.alerts("test")[0]["occurrences"] == 2
    assert first["etapes"]["advisor"]["recommendations"][0]["based_on"] == second["etapes"]["advisor"]["recommendations"][0]["based_on"]


def test_draft_human_selection_dependencies_and_idempotence():
    r, out = run()
    d = draft(r, out)
    mid = d["mission_id"]
    assert d["statut"] == "brouillon" and d["affectations_confirmees"] == 0
    tasks = r.tasks(mid)
    assert len(tasks) == 2
    ids = {t["task_id"] for t in tasks}
    assert all(set(t["depends_on"]) <= ids for t in tasks)
    assert {t["due_date"] for t in tasks} == {"2026-12-08", "2026-12-15"}
    assert r.recommendations("test")[0]["status"] == "selectionnee"
    assert all(x["status"] == "proposee" for x in r.s.data["eia_assignments"])
    again = draft(r, out)
    assert again["existante"] is True and again["mission_id"] == mid
    assert len(r.tasks(mid)) == 2


@pytest.mark.parametrize("user", ["", "agent:planner", "agent:planner@example.test"])
def test_agent_cannot_select(user):
    r, out = run()
    rid = r.recommendations("test")[0]["reco_id"]
    with pytest.raises(c.ContractError):
        e.prepare_mission(cfg(), r, rid, user, TODAY)
    assert r.recommendations("test")[0]["status"] == "proposee"
    assert r.missions("test") == []


def test_other_team_recommendation_rejected():
    r, out = run()
    with pytest.raises(c.ContractError):
        e.prepare_mission(replace(cfg(), team_id="autre"), r, r.recommendations("test")[0]["reco_id"], USER, TODAY)


def test_disabled_playbook_not_planned():
    cf = cfg()
    cf.playbooks[0]["status"] = "desactive"
    r, out = run()
    with pytest.raises(c.ContractError):
        e.prepare_mission(cf, r, r.recommendations("test")[0]["reco_id"], USER, TODAY)
    assert r.missions("test") == []


def test_confirmation_requires_validated_mission():
    r, out = run()
    mid = draft(r, out)["mission_id"]
    aid = r.s.data["eia_assignments"][0]["assignment_id"]
    with pytest.raises(c.ContractError):
        r.decide_assignment(aid, "confirmee", USER)
    r.set_mission_status(mid, "validee", USER)
    r.decide_assignment(aid, "confirmee", USER)
    assert r.s.get("eia_assignments", {"assignment_id": aid})["status"] == "confirmee"


def test_learn_rate_points_not_percent_and_no_mutation():
    r, out = run()
    mid = draft(r, out)["mission_id"]
    close(r, mid)
    before = copy.deepcopy(r.s.data)
    result = e.learn_mission(cfg(), r, Source(60, "2026-11"), mid, TODAY)
    assert result["evaluable"] is True
    row = result["comparaisons"][0]
    assert row["ecart"] == 10 and row["unite_ecart"] == "points" and row["variation_pct"] is None
    assert row["favorable"] is True and row["reference"]["value"] == 50
    assert r.s.data == before


def test_learn_unchanged_period_not_evaluable():
    r, out = run()
    mid = draft(r, out)["mission_id"]
    close(r, mid)
    assert e.learn_mission(cfg(), r, Source(60), mid, TODAY)["evaluable"] is False


def test_learn_requires_closed_mission():
    r, out = run()
    mid = draft(r, out)["mission_id"]
    src = Source(60, "2026-11")
    assert e.learn_mission(cfg(), r, src, mid, TODAY)["evaluable"] is False and src.calls == 0


def test_config_changed_not_evaluable():
    r, out = run()
    mid = draft(r, out)["mission_id"]
    close(r, mid)
    assert e.learn_mission(replace(cfg(), version="nouvelle"), r, Source(), mid, TODAY)["evaluable"] is False


def test_budget_marks_steps_expired():
    r = repo()
    out = e.run_cycle(cfg(), Source(), r, today=TODAY, max_seconds=1e-12)
    assert out["statut"] == "partiel"
    assert all(x["status"] == "expire" for x in out["etapes"].values())


def test_registry_hakim_catalog_confirmation_contracts():
    from backend import hakim
    from tools.catalog import BUILTIN_TOOLS
    from tools.eia_cycle_tools import EIA_CYCLE_TOOLS
    reg = ToolRegistry(hakim.TOOLS)
    pub = {x.tool_id for x in BUILTIN_TOOLS}
    for spec in EIA_CYCLE_TOOLS:
        assert spec.tool_id in hakim.config("m").tool_ids and spec.tool_id in pub
        assert reg.specs[spec.tool_id].read_only == spec.read_only
        assert spec.requires_confirmation == (not spec.read_only)


def test_preview_via_registry_does_not_write_real_repo(monkeypatch):
    from tools import eia_cycle_tools as tools
    r = repo()
    before = copy.deepcopy(r.s.data)
    monkeypatch.setattr(tools, "_team", lambda team_id: cfg())
    monkeypatch.setattr(tools, "_repo", lambda ctx: r)
    monkeypatch.setattr(tools, "SqlKpiSource", lambda sql: Source())
    reg = ToolRegistry(tools.EIA_CYCLE_TOOLS)
    ctx = ToolContext(sql=None, workspace=None, user_email=USER)
    out = reg.run(reg.specs["eia_apercu_cycle"], ctx, {"team_id": "test"})
    assert out["persistant"] is False and out["missions_apercu"]
    assert r.s.data == before


def test_tracking_tool_rejects_closure_with_open_tasks(monkeypatch):
    from tools import eia_cycle_tools as tools
    r, out = run()
    mid = draft(r, out)["mission_id"]
    monkeypatch.setattr(tools, "_team", lambda team_id: cfg())
    monkeypatch.setattr(tools, "_repo", lambda ctx: r)
    ctx = ToolContext(sql=None, workspace=None, user_email=USER)
    with pytest.raises(ToolError):
        tools.eia_suivi_mission(ctx, "test", mid, "mission", "terminee")


@pytest.mark.parametrize("tool_id", ["eia_cycle", "eia_preparer_mission", "eia_suivi_mission"])
def test_runtime_requires_separate_confirmation(tool_id, monkeypatch):
    import json
    from backend import hakim
    from backend.agent_runtime import AgentRuntime
    from tools.eia_cycle_tools import EIA_CYCLE_TOOLS
    class Model:
        def __init__(self):
            self.count = 0
        def chat(self, *args, **kwargs):
            self.count += 1
            if self.count == 1:
                return {"message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "decision", "type": "function", "function": {"name": tool_id,
                     "arguments": json.dumps({"team_id": "test"})}}]}, "finish_reason": "tool_calls"}
            return {"message": {"role": "assistant", "content": "Fin"}, "finish_reason": "stop"}
    reg = ToolRegistry(EIA_CYCLE_TOOLS)
    called = []
    monkeypatch.setattr(reg, "run", lambda *args, **kwargs: called.append(True) or {"ok": True})
    rt = AgentRuntime(Model(), reg, ToolContext(sql=None, workspace=None, user_email=USER))
    config = hakim.config("test")
    first = rt.run(config, [{"role": "user", "content": "Proposition"}])
    assert first.pending["tool"] == tool_id and called == []
    rejected = rt.resume(config, first.messages, {"decision": False})
    assert rejected.events[0].status == "refuse" and called == []
    # Une confirmation d'un outil ne vaut pas confirmation de l'outil suivant.
    rt = AgentRuntime(Model(), reg, ToolContext(sql=None, workspace=None, user_email=USER))
    pending = rt.run(config, [{"role": "user", "content": "Proposition"}])
    approved = rt.resume(config, pending.messages, {"decision": True})
    assert approved.events[0].status == "succes" and called == [True]


def test_staffing_permission_failure_preserves_business_results(monkeypatch):
    r = repo()
    def denied(team_id):
        raise PermissionError("Lecture RH refusée")
    monkeypatch.setattr(r, "people", denied)
    _, out = run(r)
    assert out["statut"] == "partiel" and out["etapes"]["advisor"]["recommendations"]
    assert out["etapes"]["staffing"]["status"] == "echec"
    assert all(x["kind"] == "technique" for x in out["techniques"])


def test_assignment_ids_returned_for_human_decisions():
    r, out = run()
    result = draft(r, out)
    candidates = [p for v in result["affectations_proposees"].values() for p in v["candidats"]]
    assert len(candidates) == 2
    assert all(r.s.get("eia_assignments", {"assignment_id": p["assignment_id"]}) is not None for p in candidates)
    assert all(r.s.get("eia_mission_tasks", {"mission_id": result["mission_id"], "task_id": t["task_id"]}) is not None
               for t in result["taches"])


def test_playbook_validation():
    cf = load("sales")
    data = {name: copy.deepcopy(getattr(cf, name)) for name in cf.__dataclass_fields__}
    data["playbooks"][0]["tasks"][0]["depends_on"] = [0]
    assert any("dépendances" in x for x in validate(data))
    data["playbooks"][0]["tasks"][0]["required_skills"] = [{"skill": "inventee", "level": 8}]
    assert any("compétence" in x for x in validate(data))
