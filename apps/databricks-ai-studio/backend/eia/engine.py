"""EIA Core - cycle linéaire appelé par HAKIM ; aucun second orchestrateur ni boucle de modèle.

Deux phases de gouvernance :
1. run_cycle : analyst -> prediction -> alerting -> advisor -> planner -> staffing.
   Recommandations proposées ; missions et affectations en aperçu seulement. Jamais de sélection automatique.
2. prepare_mission : après une décision humaine, sélection de la recommandation, mission en brouillon et
   affectations proposées. La validation de mission et la confirmation des affectations restent séparées.

Le repo fourni contrôle la persistance : MemoryEiaStore pour un aperçu sans écriture, SqlEiaStore pour
un cycle historisé (outil avec confirmation humaine). L'identité et les droits sont ceux de l'appelant.
Les notifications externes ne font pas partie de ce cycle ; leur point d'entrée demeure run_alerting.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any

from backend.eia import agents as a
from backend.eia import contracts as c

ROLES = ("analyst", "prediction", "alerting", "advisor", "planner", "staffing")
MAX_PREVIEWS = 8


def _human(user: str) -> None:
    if not isinstance(user, str) or "@" not in user or user.startswith("agent:"):
        raise c.ContractError("Décision humaine : utilisateur identifié requis")


def run_cycle(cfg: Any, source: Any, repo: Any, today: dt.date | None = None, actor: str = "agent:eia",
              trigger: str = "demande", max_seconds: float = 300) -> dict:
    """Exécute le cycle et journalise les résultats. Limite coopérative entre étapes (ne coupe pas une requête SQL)."""
    if trigger not in c.TRIGGERS:
        raise c.ContractError(f"Déclencheur inconnu : {trigger}")
    if max_seconds <= 0:
        raise c.ContractError("max_seconds doit être positif")
    today = today or dt.date.today()
    started = time.monotonic()
    cache = a.CachedSource(source)
    run_id = repo.start_run(cfg.team_id, trigger, "Cycle EIA du " + today.isoformat(), actor,
                            {"steps": list(ROLES), "config_version": cfg.version,
                             "governance": "propositions uniquement", "max_seconds": max_seconds})
    results: dict[str, c.AgentResult] = {}
    errors: list[str] = []
    previews: list[dict] = []
    report: dict = {}
    assignments: dict = {}

    def step(role: str, fn: Any, depends: list[str]) -> Any:
        t0 = time.monotonic()
        if t0 - started >= max_seconds:
            result = c.AgentResult(agent=role, status="expire", summary="Budget du cycle dépassé",
                                   errors=["Limite de durée atteinte avant l'étape"])
            repo.save_step(run_id, role, role, "expire", attempts=0, depends_on=depends,
                           output=c.to_dict(result), ended_at=repo.clock())
            results[role] = result
            errors.append(f"{role} : budget de durée dépassé")
            return None
        repo.save_step(run_id, role, role, "en_cours", attempts=1, depends_on=depends, started_at=repo.clock())
        extra = None
        try:
            value = fn()
            result, extra = value if isinstance(value, tuple) else (value, None)
            known = set().union(*(r.ids() for r in results.values())) if results else set()
            issues = c.validate_result(result, known)
            if issues:
                raise c.ContractError(" ; ".join(issues))
        except Exception as e:
            result = c.AgentResult(agent=role, status="echec", summary=f"Étape {role} en erreur",
                                   errors=[f"{type(e).__name__} : {e}"[:1500]])
        results[role] = result
        errors.extend(f"{role} : {e}" for e in result.errors)
        repo.save_step(run_id, role, role, result.status, output=c.to_dict(result), issues=result.errors,
                       error=" ; ".join(result.errors)[:2000] or None, ended_at=repo.clock(),
                       duration_ms=int((time.monotonic() - t0) * 1000))
        return extra

    step("analyst", lambda: a.analyst(cfg, cache, today), [])
    step("prediction", lambda: a.prediction(cfg, cache, today), ["analyst"])
    report = step("alerting", lambda: a.alerting(cfg, cache, repo, today, trigger=trigger, run_id=run_id), ["analyst", "prediction"]) or {}
    business_alerts = results["alerting"].alerts

    def advise() -> c.AgentResult:
        r = a.advisor(cfg, business_alerts)
        if r.recommendations:
            repo.save_recommendations(cfg.team_id, run_id, [c.to_dict(x) for x in r.recommendations])
        return r

    step("advisor", advise, ["alerting"])

    def plan() -> c.AgentResult:
        missions: list[c.Mission] = []
        issues: list[str] = []
        for reco in results["advisor"].recommendations[:MAX_PREVIEWS]:
            try:
                r = a.planner(cfg, c.to_dict(reco), today)
                missions.extend(r.missions)
            except Exception as e:
                issues.append(f"Recommandation {reco.id} : {e}")
        count = len(results["advisor"].recommendations)
        return c.AgentResult(agent="planner", status="echec" if issues else "reussi", missions=missions, errors=issues,
                             summary=f"{len(missions)} aperçu(s) de mission sur {count} recommandation(s), "
                                     "aucune mission enregistrée ; sélection humaine requise")

    step("planner", plan, ["advisor"])

    def staff() -> c.AgentResult:
        people = repo.people(cfg.team_id) if cfg.skills and results["planner"].missions else []
        load = repo.workload_hours([p["person_id"] for p in people]) if people else {}
        issues: list[str] = []
        total = 0
        for mission in results["planner"].missions:
            r, per_task = a.staffing(cfg, mission, people, load, today)
            assignments[mission.id] = per_task
            total += sum(1 for v in per_task.values() if v["candidats"])
            issues.extend(r.errors)
        return c.AgentResult(agent="staffing", status="echec" if issues else "reussi", errors=issues,
                             summary=f"{total} tâche(s) avec des candidats ; simulations indépendantes par mission, "
                                     "aucune affectation enregistrée")

    step("staffing", staff, ["planner"])
    for mission in results["planner"].missions:
        row = c.to_dict(mission)
        row.update(statut="apercu", affectations=assignments.get(mission.id, {}), selection_humaine_requise=True)
        previews.append(row)

    # Une erreur d'agent n'est jamais transformée en anomalie métier.
    technical = []
    for role, r in results.items():
        if r.errors and role != "alerting":
            alert = a.al.technical_alert("TECH_EIA_" + role.upper(), f"Étape EIA {role} en erreur",
                                         " ; ".join(r.errors)[:2000], role, today)
            aid, _ = repo.record_alert(cfg.team_id, run_id, c.to_dict(alert),
                                      c.fingerprint(cfg.team_id, alert.rule_id, role, today.isoformat()))
            technical.append({**c.to_dict(alert), "alert_id": aid})
    status = "partiel" if errors else "termine"
    summary = (f"{len(results['analyst'].findings)} constat(s), {len(results['prediction'].forecasts)} prévision(s), "
               f"{sum(x.kind == 'metier' for x in business_alerts)} alerte(s) métier, "
               f"{len(results['advisor'].recommendations)} recommandation(s), {len(previews)} aperçu(s) de mission. "
               "Aucune mission ni affectation validée automatiquement.")
    repo.log("run", run_id, "cycle_observe", actor,
             {"config_version": cfg.version, "findings": c.to_dict(results["analyst"])["findings"]})
    repo.end_run(run_id, status, summary, " ; ".join(errors)[:2000])
    return {"run_id": run_id, "equipe": cfg.team_id, "statut": status, "synthese": summary,
            "date": today.isoformat(), "config_version": cfg.version,
            "etapes": {role: c.to_dict(r) for role, r in results.items()},
            "alerting": report, "missions_apercu": previews, "techniques": technical,
            "requetes_kpi": cache.calls, "erreurs": errors,
            "cycle": {"PERCEIVE": "analyst", "UNDERSTAND": "alerting + advisor", "PREDICT": "prediction",
                      "PLAN": "planner + staffing", "ACT": "attente_selection_et_validation_humaines",
                      "LEARN": "observations historisées ; bilan après mission terminée via learn_mission"},
            "envoi": {"envoye": False, "motif": "Notifications externes exclues du cycle EIA"}}


def prepare_mission(cfg: Any, repo: Any, recommendation_id: str, user: str, today: dt.date | None = None,
                    source: Any = None) -> dict:
    """Décision humaine confirmée par le runtime : sélection, création d'un brouillon, propositions d'affectation.

    Ne valide jamais la mission et ne confirme aucune affectation. Un seul brouillon par recommandation :
    une relance renvoie celui qui existe, sans dupliquer ses tâches."""
    _human(user)
    today = today or dt.date.today()
    reco = repo.s.get("eia_recommendations", {"reco_id": recommendation_id, "team_id": cfg.team_id})
    if not reco:
        raise c.ContractError("Recommandation inconnue ou appartenant à une autre équipe")
    if reco["status"] == "rejetee":
        raise c.ContractError("La recommandation a été rejetée")
    existing = repo.s.find("eia_missions", {"team_id": cfg.team_id, "reco_id": recommendation_id}, limit=2)
    if existing:
        return {"mission_id": existing[0]["mission_id"], "statut": existing[0]["status"], "existante": True}
    from backend.eia.store import _load
    reco["assumptions"] = _load(reco.get("assumptions"), [])
    # Construire et vérifier tout le plan avant la première écriture.
    result = a.planner(cfg, reco, today)
    mission = result.missions[0]
    mrow, tasks = a.mission_record(mission, today)
    people = repo.people(cfg.team_id) if cfg.skills else []
    load = repo.workload_hours([p["person_id"] for p in people]) if people else {}
    staffing_result, per_task = a.staffing(cfg, mission, people, load, today)
    if reco["status"] == "proposee":
        repo.set_recommendation_status(recommendation_id, "selectionnee", user)
    baseline, baseline_errors = observe(cfg, source, mission.success_kpis, today) if source else ([], ["Source de référence absente"])
    mid = repo.create_mission_draft(cfg.team_id, mrow, tasks, user)
    repo.log("mission", mid, "baseline", user,
             {"date": today.isoformat(), "config_version": cfg.version, "points": baseline, "erreurs": baseline_errors})
    for task_id, proposed in per_task.items():
        if proposed["candidats"]:
            ids = repo.propose_assignments(mid, task_id, proposed["candidats"], "agent:staffing")
            for candidate, assignment_id in zip(proposed["candidats"], ids):
                candidate["assignment_id"] = assignment_id
    repo.log("mission", mid, "planifiee", user,
             {"config_version": cfg.version, "playbook_id": a.playbook_of(reco), "staffing": c.to_dict(staffing_result)})
    return {"mission_id": mid, "statut": "brouillon", "existante": False,
            "recommandation_id": recommendation_id, "taches": [{**t, "task_id": t["id"]} for t in tasks], "affectations_proposees": per_task,
            "erreurs_affectation": staffing_result.errors,
            "validation_humaine_requise": True, "affectations_confirmees": 0,
            "erreurs_baseline": baseline_errors}


def observe(cfg: Any, source: Any, metrics: list[str], today: dt.date) -> tuple[list[dict], list[str]]:
    """Dernière observation par KPI/dimension ; pas de total entre dimensions ni moyenne de taux."""
    rows, errors = [], []
    for metric in metrics:
        try:
            data = source.fetch(cfg, metric, today)
            for dimension, series in a.k.by_dimension(data.points).items():
                period = sorted(series)[-1]
                rows.append({"metric": metric, "dimension": dimension, "period": period, "value": series[period],
                             "unit": data.kdef.get("unit", ""), "evidence": c.to_dict(data.evidence)})
        except Exception as e:
            errors.append(f"{metric} : {type(e).__name__} : {e}")
    return rows, errors


def learn_mission(cfg: Any, repo: Any, source: Any, mission_id: str, today: dt.date | None = None) -> dict:
    """Bilan en lecture seule : avancement + variations des KPI par rapport à la référence figée.

    Les changements ne prouvent pas un effet causal de la mission et ne changent ni les règles ni leurs seuils.
    Les périodes inchangées, unités différentes et données manquantes sont explicitement non évaluables.
    """
    from backend.eia.store import _load
    today = today or dt.date.today()
    mission = repo.s.get("eia_missions", {"mission_id": mission_id, "team_id": cfg.team_id})
    if not mission:
        raise c.ContractError("Mission inconnue ou appartenant à une autre équipe")
    tasks = repo.tasks(mission_id)
    out = {"mission_id": mission_id, "statut": mission["status"], "taches_total": len(tasks),
           "taches_faites": sum(t["status"] == "fait" for t in tasks), "comparaisons": [],
           "limite": "Variation observée, pas de causalité démontrée ; aucun seuil ni règle modifié"}
    if mission["status"] != "terminee":
        return {**out, "evaluable": False, "motif": "Bilan d'efficacité après clôture humaine de la mission"}
    events = repo.s.find("eia_events", {"object_type": "mission", "object_id": mission_id,
                                        "event_type": "baseline"}, limit=2)
    if len(events) != 1:
        return {**out, "evaluable": False, "motif": "Référence initiale absente ou ambiguë"}
    baseline = _load(events[0].get("payload"), {})
    if baseline.get("config_version") != cfg.version:
        return {**out, "evaluable": False, "motif": "Version de configuration différente : comparabilité à valider"}
    current, errors = observe(cfg, source, _load(mission["success_kpis"], []), today)
    old = {(p["metric"], p["dimension"]): p for p in baseline.get("points", [])}
    new = {(p["metric"], p["dimension"]): p for p in current}
    for key in sorted(old.keys() | new.keys()):
        b, n = old.get(key), new.get(key)
        row = {"metric": key[0], "dimension": key[1], "reference": b, "observation": n}
        if not b or not n:
            row.update(evaluable=False, motif="Dimension ou observation manquante")
        elif n["unit"] != b["unit"] or n["period"] <= b["period"]:
            row.update(evaluable=False, motif="Unité différente ou aucune période plus récente")
        else:
            delta = n["value"] - b["value"]
            direction = cfg.kpi(key[0]).get("direction")
            row.update(evaluable=True, ecart=round(delta, 4), unite_ecart="points" if n["unit"] == "%" else n["unit"],
                       variation_pct=None if n["unit"] in ("%", "ratio") else a.k.pct(n["value"], b["value"]),
                       favorable=(delta > 0 if direction == "hausse_favorable" else delta < 0)
                       if direction in ("hausse_favorable", "baisse_favorable") and delta else None)
        out["comparaisons"].append(row)
    return {**out, "evaluable": any(r["evaluable"] for r in out["comparaisons"]), "erreurs": errors}
