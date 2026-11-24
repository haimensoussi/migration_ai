"""Tests EIA : équipe de personnel, compétences et agent RH d'affectation (staffing)."""
import datetime as dt
import json
import os

import pytest

from backend.eia import contracts as c
from backend.eia import staff_seed as seed
from backend.eia import staffing as sf
from backend.eia import store as st
from backend.eia import team_config as tc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPE = ("dataops_dev", "ai_studio", "data_")
TODAY = dt.date(2026, 11, 23)
USER = "responsable@sncf.fr"
KNOWN = {"negociation", "relance_clients", "analyse_donnees"}


def person(pid, skills, avail=20, status="actif"):
    return {"person_id": pid, "full_name": f"Personne {pid}", "job_title": "Commercial", "capacity_hours_week": 35,
            "availability_pct": avail, "status": status, "skills": skills}


TASK = {"required_skills": [{"skill": "negociation", "level": 4}, {"skill": "relance_clients", "level": 3}],
        "estimated_hours": 8, "due_date": "2026-12-07"}                       # horizon 14 jours
PEOPLE = [person("A", {"negociation": 4, "relance_clients": 3}),                # 14 h libres, adéquation 1
          person("B", {"negociation": 2, "relance_clients": 5}, avail=40),      # 28 h libres, adéquation 0,75
          person("C", {"relance_clients": 5}),                                  # négociation absente -> écarté
          person("D", {"negociation": 5, "relance_clients": 5}),                # 14 h - 10 h de charge = 4 h
          person("E", {"negociation": 5, "relance_clients": 5}, status="inactif")]


# ---------------- classement (cas calculés à la main) ----------------

def test_ranking_matches_hand_computed_scores():
    top, excluded = sf.rank_candidates(TASK, PEOPLE, {"D": 10}, KNOWN, TODAY)
    assert [(x["person_id"], x["score"]) for x in top] == [("A", 1.0), ("D", 0.85), ("B", 0.825)]
    assert top[1]["availability_score"] == 0.5 and top[1]["free_hours"] == 4.0
    assert top[2]["gaps"] == [{"skill": "negociation", "detenu": 2, "requis": 4}]
    assert excluded == [{"person_id": "C", "motif": "compétence absente : negociation"}]     # E inactif : ignoré
    assert "negociation 2/4 requis" in top[2]["rationale"] and "lacunes : negociation (2 au lieu de 4)" in top[2]["rationale"]
    assert top[0]["rationale"].endswith("Proposition à confirmer par un responsable.")


def test_weights_top_n_and_ties_come_from_settings():
    top, _ = sf.rank_candidates(TASK, PEOPLE, {"D": 10}, KNOWN, TODAY,
                                {"skill_weight": 0.0, "availability_weight": 1.0, "top_n": 2, "status": "a_valider"})
    assert [x["person_id"] for x in top] == ["A", "B"]                      # même score 1.0 : ordre par charge puis id
    twins = [person("Z", {"negociation": 4}), person("Y", {"negociation": 4})]
    top, _ = sf.rank_candidates({"required_skills": ["negociation"], "estimated_hours": 4}, twins, {}, KNOWN, TODAY)
    assert [x["person_id"] for x in top] == ["Y", "Z"]


def test_no_availability_and_invalid_requirements():
    top, excluded = sf.rank_candidates(TASK, [person("A", {"negociation": 5, "relance_clients": 5})], {"A": 14}, KNOWN, TODAY)
    assert top == [] and excluded[0]["motif"] == "aucune disponibilité sur l'horizon"
    with pytest.raises(c.ContractError, match="hors référentiel"):
        sf.rank_candidates({"required_skills": ["astrologie"]}, PEOPLE, {}, KNOWN, TODAY)
    with pytest.raises(c.ContractError, match="Niveau requis"):
        sf.rank_candidates({"required_skills": [{"skill": "negociation", "level": 6}]}, PEOPLE, {}, KNOWN, TODAY)
    with pytest.raises(c.ContractError, match="estimated_hours"):
        sf.rank_candidates({**TASK, "estimated_hours": -2}, PEOPLE, {}, KNOWN, TODAY)


# ---------------- parcours complet avec confirmation humaine ----------------

def cfg():
    return tc.load("sales", data_scope=SCOPE)


def setup_mission():
    ticks = iter(f"2026-11-23 09:{i // 60:02d}:{i % 60:02d}" for i in range(3600))
    r = st.EiaRepository(st.MemoryEiaStore(), clock=lambda: next(ticks))
    for p in PEOPLE:
        r.upsert_person({k: v for k, v in p.items() if k != "skills"} | {"team_id": "sales"}, p["skills"], USER)
    run = r.start_run("sales", "demande", "Analyse", USER, {"steps": []})
    [rid] = r.save_recommendations("sales", run, [{"title": "Relancer", "rationale": "...", "priority": 1, "based_on": ["al_1"]}])
    r.set_recommendation_status(rid, "selectionnee", USER)
    tasks = [{"id": "mt_1", "title": "Négocier avec les comptes inactifs", **TASK},
             {"id": "mt_2", "title": "Relancer les clients inactifs", **TASK}]
    mid = r.create_mission_draft("sales", {"title": "Relance", "objective": "Réactiver", "recommendation_id": rid,
                                           "success_kpis": ["part_clients_inactifs"]}, tasks, USER)
    return r, mid


def test_proposal_requires_validated_mission_and_identified_user():
    r, mid = setup_mission()
    res = sf.propose_for_task(r, cfg(), mid, "mt_1", TODAY)
    assert [x["person_id"] for x in res["candidats"]] == ["A", "D", "B"] and res["parametres_statut"] == "a_valider"
    assert [a["status"] for a in r.assignments("mt_1")] == ["proposee"] * 3
    first = res["candidats"][0]["assignment_id"]
    with pytest.raises(c.ContractError, match="mission validée"):
        r.decide_assignment(first, "confirmee", USER)                       # mission encore en brouillon
    r.set_mission_status(mid, "validee", USER)
    with pytest.raises(c.ContractError, match="utilisateur identifié"):
        r.decide_assignment(first, "confirmee", "agent:staffing")           # un agent ne peut pas confirmer
    r.decide_assignment(first, "confirmee", USER)
    by_id = {a["person_id"]: a for a in r.assignments("mt_1")}
    assert by_id["A"]["status"] == "confirmee" and by_id["A"]["decided_by"] == USER
    assert by_id["D"]["status"] == by_id["B"]["status"] == "annulee"
    assert next(t for t in r.tasks(mid) if t["task_id"] == "mt_1")["owner"] == "Personne A"
    with pytest.raises(c.ContractError, match="déjà confirmée"):
        sf.propose_for_task(r, cfg(), mid, "mt_1", TODAY)
    assert "confirmee" in [e["event_type"] for e in r.events(first)]


def test_confirmed_workload_changes_next_proposal():
    r, mid = setup_mission()
    r.set_mission_status(mid, "validee", USER)
    first = sf.propose_for_task(r, cfg(), mid, "mt_1", TODAY)["candidats"][0]
    r.decide_assignment(first["assignment_id"], "confirmee", USER)
    assert r.workload_hours(["A", "B", "D"]) == {"A": 8, "B": 0, "D": 0}
    nxt = sf.propose_for_task(r, cfg(), mid, "mt_2", TODAY)["candidats"]
    # A : 14 - 8 = 6 h libres -> 0,7 + 0,3 x 6/8 = 0,925 ; D sans charge -> 1,0
    assert [(x["person_id"], x["score"]) for x in nxt] == [("D", 1.0), ("A", 0.925), ("B", 0.825)]
    r.set_task_status(mid, "mt_1", "en_cours", USER)
    r.set_task_status(mid, "mt_1", "fait", USER)
    assert r.workload_hours(["A"]) == {"A": 0}                               # tâche terminée : charge libérée


def test_skill_levels_are_validated_on_write():
    r, _ = setup_mission()
    with pytest.raises(c.ContractError, match="1 à 5"):
        r.upsert_person({"person_id": "X", "team_id": "sales", "full_name": "X", "capacity_hours_week": 35,
                         "availability_pct": 10, "status": "actif"}, {"negociation": 7}, USER)
    r.upsert_person({**{k: v for k, v in PEOPLE[0].items() if k != "skills"}, "team_id": "sales", "availability_pct": 50},
                    {"negociation": 5}, USER)
    a = next(p for p in r.people("sales") if p["person_id"] == "A")
    assert a["availability_pct"] == 50 and a["skills"] == {"negociation": 5, "relance_clients": 3}
    assert "E" not in [p["person_id"] for p in r.people("sales")] and len(r.people("sales", active_only=False)) == 5


# ---------------- outils HAKIM (lecture seule) ----------------

def test_hakim_staff_tools_simulate_without_writing(monkeypatch):
    from backend import hakim
    from backend.tool_registry import ToolContext, ToolError, ToolRegistry
    from tools import eia_staff_tools as tools
    r, mid = setup_mission()
    before = {t: len(rows) for t, rows in r.s.data.items()}
    monkeypatch.setattr(tools, "_repo", lambda ctx: r)
    monkeypatch.setattr(tools, "_today", lambda: TODAY)
    reg = ToolRegistry(hakim.TOOLS)
    specs = {t.tool_id: t for t in hakim.TOOLS}
    assert {"eia_kpi", "eia_forecast", "eia_personnel", "eia_affectation"} <= set(hakim.config("m").tool_ids)
    assert all(specs[t].read_only for t in ("eia_personnel", "eia_affectation"))
    ctx = ToolContext(sql=None, workspace=None)
    out = reg.run(specs["eia_affectation"], ctx, {"team_id": "sales", "charge_heures": 8, "echeance": "2026-12-07",
                                                  "competences": TASK["required_skills"]})
    assert [x["person_id"] for x in out["candidats"]] == ["A", "D", "B"] and out["ecartes"] == 1
    assert "Simulation" in out["avertissement"] and out["methode"].startswith("Score =")
    assert {t: len(rows) for t, rows in r.s.data.items()} == before          # aucune écriture
    lst = reg.run(specs["eia_personnel"], ctx, {"team_id": "sales", "competence": "negociation", "niveau_min": 4})
    assert [p["person_id"] for p in lst["liste"]] == ["D", "A"] and len(lst["referentiel"]) == 12
    for bad in ({"competences": [{"skill": "astrologie"}]}, {"echeance": "2026-01-01"}):
        with pytest.raises(ToolError):
            reg.run(specs["eia_affectation"], ctx, {"team_id": "sales", "charge_heures": 8,
                                                    "competences": TASK["required_skills"], **bad})


# ---------------- configuration et personnel fictif ----------------

def test_sales_config_declares_skills_and_staffing_agent():
    conf = cfg()
    assert "staffing" in conf.agents and "staffing" in conf.instructions and len(conf.skills) == 12
    assert conf.staffing["status"] == "a_valider" and "eia_affectation" in conf.tools
    d = json.load(open(os.path.join(ROOT, "config", "teams", "sales.json"), encoding="utf-8"))
    for bad, msg in (({"skill_weight": 0.9, "availability_weight": 0.3, "status": "a_valider"}, "somme 1"),
                     ({"skill_weight": 0.7, "availability_weight": 0.3, "status": "ok"}, "staffing.status")):
        assert any(msg in i for i in tc.validate({**d, "staffing": bad}, SCOPE))
    assert any("double" in i for i in tc.validate({**d, "skills": d["skills"] + [d["skills"][0]]}, SCOPE))


REPS = [{"rep_id": f"R{i:03d}", "first_name": "Prénom", "last_name": f"Nom{i}", "email": f"r{i}@x.example",
         "team": t, "region": "IDF", "status": s}
        for i, (t, s) in enumerate([("PME", "actif"), ("ETI", "actif"), ("Grands comptes", "actif"),
                                    ("Direction régionale", "actif"), ("PME", "parti")], 1)]


def test_seed_is_deterministic_and_within_profiles():
    a, b = seed.build_sales_staff(REPS), seed.build_sales_staff(list(reversed(REPS)))
    assert a == b and len(a) == len(REPS) + len(seed.SUPPORT)
    known = cfg().skill_ids()
    for p, skills in a:
        prof = seed.PROFILES[p["department"]]
        assert set(skills) == set(prof) <= known
        assert all(prof[s][0] <= lv <= prof[s][1] for s, lv in skills.items())
        lo, hi = seed.AVAILABILITY[p["department"]]
        assert lo <= p["availability_pct"] <= hi and p["capacity_hours_week"] == 35
    assert [p["status"] for p, _ in a if p["person_id"] == "R005"] == ["inactif"]
    assert next(p for p, _ in a if p["person_id"] == "S005")["email"] == "ines.moreau@horizon-equipements.example"
