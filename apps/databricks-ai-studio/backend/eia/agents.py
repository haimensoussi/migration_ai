"""EIA Core - agents transverses supervisés par HAKIM (analyst, prediction, alerting, advisor, planner, staffing).

Chaque agent est une fonction déterministe qui renvoie un AgentResult conforme au contrat (validate_result) :
- aucun chiffre n'est produit par un modèle de langage ; HAKIM explique les résultats, il ne les calcule pas ;
- aucune logique métier n'est codée ici : KPI, règles, plans d'action types et compétences viennent de la
  configuration d'équipe (config/teams/<team_id>.json) ;
- les sorties sont des propositions : recommandations « proposées », missions en brouillon, affectations à
  confirmer par un responsable.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from backend.eia import alerting as al
from backend.eia import contracts as c
from backend.eia import forecast as fc_mod
from backend.eia import kpi as k
from backend.eia import staffing as sf
from backend.eia.team_config import TeamConfig

PLAYBOOK_MARK = "Plan d'action type {} (à valider)"
PLAYBOOK_RE = re.compile(r"^Plan d'action type (\S+) \(à valider\)$")


class CachedSource:
    """Partage les lectures de KPI entre les agents d'un même cycle (une requête par KPI) ; mémorise aussi les échecs."""

    def __init__(self, source: Any):
        self.source, self.cache, self.calls = source, {}, 0

    def fetch(self, cfg: TeamConfig, kpi_id: str, today: dt.date) -> al.KpiData:
        if kpi_id not in self.cache:
            self.calls += 1
            try:
                self.cache[kpi_id] = self.source.fetch(cfg, kpi_id, today)
            except Exception as e:
                self.cache[kpi_id] = e
        v = self.cache[kpi_id]
        if isinstance(v, Exception):
            raise v
        return v


def _finish(agent: str, items: dict, errors: list[str], summary: str, known: set[str] | None = None) -> c.AgentResult:
    r = c.AgentResult(agent=agent, status="echec" if errors else "reussi", summary=summary[:c.MAX_TEXT],
                      errors=errors, **items)
    issues = c.validate_result(r, known)
    if issues:
        raise c.ContractError(f"Sortie de l'agent {agent} non conforme : " + " ; ".join(issues))
    return r


# ---------------- analyst ----------------

def analyst(cfg: TeamConfig, source: Any, today: dt.date) -> c.AgentResult:
    """Constats chiffrés : dernière valeur et variations (mensuelle, N-1) des KPI suivis, par dimension."""
    kpis = (cfg.analysis or {}).get("kpis") or sorted({r["kpi"] for r in cfg.rules})
    window = int((cfg.analysis or {}).get("window_months", 1))
    findings, errors = [], []
    for kid in kpis:
        try:
            data = source.fetch(cfg, kid, today)
        except Exception as e:
            errors.append(f"KPI {kid} : {type(e).__name__} : {e}")
            continue
        kdef, unit = data.kdef, data.kdef.get("unit", "")
        for dim, s in k.by_dimension(data.points).items():
            if kdef["grain"] == "mois":
                res = k.compare(s, window, unit)
                parts = []
                if res.get("variation_mensuelle_pct") is not None:
                    parts.append(f"variation mensuelle {res['variation_mensuelle_pct']} %")
                if res.get("variation_annuelle_pct") is not None:
                    parts.append(f"variation N-1 {res['variation_annuelle_pct']} %")
                if res.get("variation_annuelle_points") is not None:
                    parts.append(f"variation N-1 {res['variation_annuelle_points']} points")
                if res.get("note"):
                    parts.append(res["note"])
                value, period, detail = res["valeur"], res["periode"], " ; ".join(parts)
            else:
                period = sorted(s)[-1]
                value, detail = s[period], "valeur à la date de référence"
            findings.append(c.Finding(kind="kpi", title=kdef["label"] + (f" - {dim}" if dim else ""),
                                      value=float(value), unit=unit, period=period, detail=detail,
                                      evidence=data.evidence))
    summary = f"{len(findings)} constat(s) sur {len(kpis) - len(errors)} KPI" + (f" ; {len(errors)} KPI en erreur" if errors else "")
    return _finish("analyst", {"findings": findings}, errors, summary)


# ---------------- prediction ----------------

def prediction(cfg: TeamConfig, source: Any, today: dt.date) -> c.AgentResult:
    """Prévisions des KPI autorisés par la configuration, avec test de fiabilité sur l'historique."""
    f = cfg.forecast or {}
    forecasts, errors = [], []
    for kid in f.get("kpis") or []:
        try:
            data = source.fetch(cfg, kid, today)
            if data.kdef["grain"] != "mois" or any(p["dimension"] for p in data.points):
                raise fc_mod.ForecastError("prévision possible uniquement sur un KPI mensuel global")
            pts = sorted(data.points, key=lambda p: p["period"])
            run = fc_mod.forecast([p["period"] for p in pts], [p["value"] for p in pts], horizon=int(f.get("horizon", 3)),
                                  season_length=int(f.get("season_length", 12)), test_points=int(f.get("test_points", 6)),
                                  max_error_pct=float(f.get("max_error_pct", 15)), metric=kid, evidence=data.evidence)
            forecasts.append(run.forecast)
        except Exception as e:
            errors.append(f"Prévision {kid} : {type(e).__name__} : {e}")
    reliable = sum(1 for x in forecasts if x.reliable)
    summary = f"{len(forecasts)} prévision(s), dont {reliable} fiable(s)" + (f" ; {len(errors)} en erreur" if errors else "")
    return _finish("prediction", {"forecasts": forecasts}, errors, summary)


# ---------------- alerting ----------------

def alerting(cfg: TeamConfig, source: Any, repo: Any, today: dt.date, notifier: Any = None,
             trigger: str = "demande", run_id: str | None = None) -> tuple[c.AgentResult, dict]:
    """Réutilise evaluate_rule ; intégré au cycle sans créer une seconde exécution ni envoyer de notification."""
    if run_id is None:
        report = al.run_alerting(cfg, source, repo, notifier=notifier, today=today, trigger=trigger, actor="agent:alerting")
    else:
        new, repeated, technical, rules = [], [], [], {}
        failures: set[str] = set()
        def record(alert: c.Alert) -> None:
            row = c.to_dict(alert)
            aid, fresh = repo.record_alert(cfg.team_id, run_id, row,
                                           c.fingerprint(cfg.team_id, alert.rule_id, alert.scope or alert.metric, alert.period))
            row["alert_id"] = aid
            (new if fresh else repeated).append(row)
            if alert.kind == "technique":
                technical.append(row)
        for rule in cfg.rules:
            if rule.get("status") == "desactive":
                continue
            kid = rule["kpi"]
            try:
                data = source.fetch(cfg, kid, today)
            except Exception as e:
                if kid not in failures:
                    record(al.technical_alert("TECH_SOURCE", f"Source indisponible : {kid}", str(e)[:1500], kid, today))
                    failures.add(kid)
                rules[rule["id"]] = {"statut": "non_evalue", "motif": "source indisponible"}
                continue
            try:
                alerts, skipped = al.evaluate_rule(cfg, rule, data)
                for alert in alerts:
                    record(alert)
                rules[rule["id"]] = {"statut": "evalue", "alertes": len(alerts), "non_evalues": skipped}
            except Exception as e:
                record(al.technical_alert("TECH_RULE", rule["label"], str(e)[:1500], kid, today))
                rules[rule["id"]] = {"statut": "erreur", "motif": str(e)[:1500]}
        report = {"run_id": run_id, "nouvelles": new, "deja_connues": repeated, "techniques": technical,
                  "regles": rules, "envoi": {"envoye": False},
                  "synthese": f"{len(rules)} règle(s), {len(new)} nouvelle(s) alerte(s), {len(technical)} erreur(s) technique(s)"}
    alerts = []
    for a in report["nouvelles"] + report["deja_connues"]:
        ev = c.Evidence(**a["evidence"]) if a.get("evidence") else None
        fields = {x: a[x] for x in c.Alert.__dataclass_fields__ if x not in ("evidence", "id") and x in a}
        alerts.append(c.Alert(**fields, evidence=ev, id=a["alert_id"]))
    errors = [a["message"] for a in report["techniques"]]
    return _finish("alerting", {"alerts": alerts}, errors, report["synthese"]), report


# ---------------- advisor ----------------

def _fmt(v: Any) -> str:
    return "n.d." if v is None else f"{v:g}"


def _label(a: c.Alert) -> str:
    """Titre de l'alerte avec son périmètre, sans le répéter si le moteur d'alerting l'y a déjà mis."""
    if not a.scope or a.title.endswith(f" - {a.scope}"):
        return a.title
    return f"{a.title} - {a.scope}"


def advisor(cfg: TeamConfig, alerts: list[c.Alert]) -> c.AgentResult:
    """Recommandations : plans d'action types de la configuration déclenchés par les alertes métier."""
    business = [a for a in alerts if a.kind == "metier"]
    candidates = []
    for pb in cfg.playbooks:
        if pb.get("status") == "desactive":
            continue
        matched = [a for a in business if a.rule_id in pb["rules"]]
        if not matched:
            continue
        top = max(al.SEV_RANK[a.severity] for a in matched)
        candidates.append((top, len(matched), pb, sorted(matched, key=lambda a: (-al.SEV_RANK[a.severity], a.rule_id, a.scope))))
    candidates.sort(key=lambda x: (-x[0], -x[1], x[2]["id"]))
    recos = []
    for prio, (_, _, pb, matched) in enumerate(candidates, 1):
        shown = matched[:6]
        facts = " ; ".join(f"{a.rule_id} {_label(a)} : {_fmt(a.observed)} "
                           f"(seuil {_fmt(a.threshold)}, {a.severity})" for a in shown)
        more = f" ; et {len(matched) - len(shown)} autre(s)" if len(matched) > len(shown) else ""
        recos.append(c.Recommendation(
            title=pb["title"], rationale=f"{pb['rationale']} Déclencheurs : {facts}{more}.", priority=prio,
            based_on=[a.id for a in matched],
            assumptions=[PLAYBOOK_MARK.format(pb["id"]), f"Seuils des règles à valider par {pb.get('owner_role', 'le responsable')}"],
            risks=list(pb.get("risks") or [])))
    summary = (f"{len(recos)} recommandation(s) issue(s) de {len(business)} alerte(s) métier" if recos
               else "Aucune alerte métier ne déclenche de plan d'action")
    return _finish("advisor", {"recommendations": recos}, [], summary, known={a.id for a in alerts})


def playbook_of(reco: dict) -> str | None:
    for x in reco.get("assumptions") or []:
        m = PLAYBOOK_RE.match(str(x))
        if m:
            return m.group(1)
    return None


# ---------------- planner ----------------

def planner(cfg: TeamConfig, reco: dict, today: dt.date) -> c.AgentResult:
    """Mission en brouillon construite à partir du plan d'action type de la recommandation."""
    pb_id = playbook_of(reco)
    if not pb_id:
        raise c.ContractError("Recommandation sans plan d'action type : mission à construire manuellement")
    pb = cfg.playbook(pb_id)
    if pb.get("status") == "desactive":
        raise c.ContractError("Le plan d'action type est désactivé")
    tasks: list[c.MissionTask] = []
    for t in pb["tasks"]:
        tasks.append(c.MissionTask(
            title=t["title"], owner=t.get("owner_role", ""), due_in_days=t.get("due_in_days"),
            deliverable=t.get("deliverable", ""), depends_on=[tasks[i].id for i in t.get("depends_on") or []],
            required_skills=sf.normalize_requirements(t.get("required_skills"), cfg.skill_ids()),
            estimated_hours=t.get("estimated_hours")))
    due = max((t.due_in_days or 0 for t in tasks), default=0) or None
    m = c.Mission(title=pb["title"], objective=reco.get("rationale", pb["rationale"])[:2000],
                  recommendation_id=reco["reco_id"] if "reco_id" in reco else reco["id"], tasks=tasks,
                  success_kpis=list(pb["success_kpis"]), deliverables=[t.deliverable for t in tasks if t.deliverable],
                  owner=pb.get("owner_role", ""), due_in_days=due)
    hours = sum(t.estimated_hours or 0 for t in tasks)
    return _finish("planner", {"missions": [m]}, [], f"Mission en brouillon : {len(tasks)} tâche(s), {hours} h estimées, "
                   f"échéance {due} jours ; à valider par {m.owner or 'un responsable'}")


def mission_record(m: c.Mission, today: dt.date) -> tuple[dict, list[dict]]:
    """Conversion d'une Mission en lignes pour EiaRepository.create_mission_draft (dates absolues)."""
    def date(days: int | None) -> str | None:
        return (today + dt.timedelta(days=days)).isoformat() if days else None
    mission = {"id": m.id, "title": m.title, "objective": m.objective, "recommendation_id": m.recommendation_id,
               "owner": m.owner, "due_date": date(m.due_in_days), "deliverables": m.deliverables,
               "success_kpis": m.success_kpis}
    tasks = [{"id": t.id, "title": t.title, "owner": t.owner, "due_date": date(t.due_in_days), "deliverable": t.deliverable,
              "depends_on": t.depends_on, "required_skills": t.required_skills, "estimated_hours": t.estimated_hours}
             for t in m.tasks]
    return mission, tasks


# ---------------- staffing ----------------

def staffing(cfg: TeamConfig, mission: c.Mission, people: list[dict], load: dict[str, int],
             today: dt.date) -> tuple[c.AgentResult, dict]:
    """Classement des personnes pour chaque tâche (simulation : rien n'est enregistré ni confirmé).

    La charge d'une tâche déjà attribuée au premier candidat est ajoutée à sa charge pour les tâches suivantes,
    pour prendre en compte ce choix hypothétique ; une disponibilité partielle reste visible dans le score
    et doit être arbitrée par le responsable."""
    load = dict(load)
    per_task, errors = {}, []
    for t in mission.tasks:
        task = {"required_skills": t.required_skills, "estimated_hours": t.estimated_hours,
                "due_date": (today + dt.timedelta(days=t.due_in_days)).isoformat() if t.due_in_days else None}
        try:
            top, excluded = sf.rank_candidates(task, people, load, cfg.skill_ids(), today, cfg.staffing)
        except c.ContractError as e:
            errors.append(f"Tâche {t.title} : {e}")
            continue
        per_task[t.id] = {"tache": t.title, "candidats": top, "ecartes": len(excluded)}
        if top:
            load[top[0]["person_id"]] = load.get(top[0]["person_id"], 0) + (t.estimated_hours or 0)
        else:
            errors.append(f"Tâche {t.title} : aucune personne disponible avec les compétences requises")
    staffed = sum(1 for v in per_task.values() if v["candidats"])
    summary = f"{staffed}/{len(mission.tasks)} tâche(s) avec des candidats ; affectations à confirmer par un responsable"
    return _finish("staffing", {}, errors, summary), per_task
