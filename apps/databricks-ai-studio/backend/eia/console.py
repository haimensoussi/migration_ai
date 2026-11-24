"""EIA Core - services des pages Missions et Notifications (et de l'outil HAKIM eia_suivi_mission).

Un seul chemin de décision pour l'interface et pour HAKIM : mêmes transitions (contracts.TRANSITIONS),
même appartenance à l'équipe, même refus de clôturer une mission dont des tâches sont ouvertes.
L'identité de décision est celle de l'utilisateur connecté, jamais une valeur saisie.
Aucun envoi externe ici : l'envoi reste dans run_alerting, sous une configuration validée.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from backend.eia import alerting as al
from backend.eia import contracts as c

OPEN_TASKS = ("a_faire", "en_cours", "bloque")
LABELS = {
    "mission": {"brouillon": "Brouillon", "validee": "Validée", "en_cours": "En cours", "terminee": "Terminée",
                "annulee": "Annulée"},
    "task": {"a_faire": "À faire", "en_cours": "En cours", "fait": "Fait", "bloque": "Bloquée", "annule": "Annulée"},
    "assignment": {"proposee": "Proposée", "confirmee": "Confirmée", "refusee": "Refusée", "annulee": "Annulée"},
    "alert": {"nouvelle": "Nouvelle", "vue": "Vue", "acquittee": "Acquittée", "resolue": "Résolue"},
    "recommendation": {"proposee": "Proposée", "selectionnee": "Sélectionnée", "validee": "Validée",
                       "rejetee": "Rejetée"},
}
ACTION_LABELS = {
    "mission": {"validee": "Valider la mission", "en_cours": "Lancer la mission", "terminee": "Clôturer la mission",
                "annulee": "Annuler la mission"},
    "task": {"en_cours": "Démarrer", "fait": "Marquer faite", "bloque": "Bloquer", "a_faire": "Remettre à faire",
             "annule": "Annuler"},
    "assignment": {"confirmee": "Confirmer", "refusee": "Refuser", "annulee": "Annuler"},
    "alert": {"vue": "Marquer vue", "acquittee": "Acquitter", "resolue": "Marquer résolue"},
}


def _human(user: str) -> None:
    if not isinstance(user, str) or "@" not in user or user.startswith("agent:"):
        raise c.ContractError("Décision humaine : utilisateur identifié requis")


def next_statuses(kind: str, current: str) -> list[str]:
    """Statuts atteignables (ordre stable pour l'affichage)."""
    return [s for s in c.STATUSES[kind] if s in c.TRANSITIONS[kind].get(current, set())]


def mission_of_team(repo: Any, team_id: str, mission_id: str) -> dict:
    m = repo.s.get("eia_missions", {"mission_id": mission_id, "team_id": team_id})
    if not m:
        raise c.ContractError("Mission inconnue ou appartenant à une autre équipe")
    return m


def mission_actions(mission: dict, tasks: list[dict]) -> list[dict]:
    """Actions possibles sur la mission, avec le motif quand une action est indisponible."""
    out = []
    open_tasks = sum(t["status"] in OPEN_TASKS for t in tasks)
    for target in next_statuses("mission", mission["status"]):
        reason = ""
        if target == "terminee" and open_tasks:
            reason = f"{open_tasks} tâche(s) encore ouverte(s)"
        out.append({"target": target, "label": ACTION_LABELS["mission"][target], "allowed": not reason, "reason": reason})
    return out


def task_actions(mission: dict, task: dict) -> list[dict]:
    allowed = mission["status"] in ("validee", "en_cours")
    reason = "" if allowed else "la mission doit être validée"
    return [{"target": t, "label": ACTION_LABELS["task"][t], "allowed": allowed, "reason": reason}
            for t in next_statuses("task", task["status"])]


def assignment_actions(mission: dict, a: dict) -> list[dict]:
    out = []
    for t in next_statuses("assignment", a["status"]):
        reason = ""
        if t == "confirmee" and mission["status"] not in ("validee", "en_cours"):
            reason = "la mission doit être validée"
        out.append({"target": t, "label": ACTION_LABELS["assignment"][t], "allowed": not reason, "reason": reason})
    return out


def mission_detail(repo: Any, team_id: str, mission_id: str) -> dict:
    m = mission_of_team(repo, team_id, mission_id)
    from backend.eia.store import _load
    m = {**m, "deliverables": _load(m.get("deliverables"), []), "success_kpis": _load(m.get("success_kpis"), [])}
    # Identifiants de tâche aléatoires : ordre d'affichage par échéance puis titre (suit les dépendances des playbooks).
    tasks = sorted(repo.tasks(mission_id), key=lambda t: (str(t.get("due_date") or "9999"), t.get("title") or ""))
    for t in tasks:
        t["assignments"] = repo.assignments(t["task_id"])
        t["actions"] = task_actions(m, t)
        for a in t["assignments"]:
            a["actions"] = assignment_actions(m, a)
    titles = {t["task_id"]: t["title"] for t in tasks}
    for t in tasks:
        t["depends_on_titles"] = [titles.get(x, x) for x in t["depends_on"]]
    reco = repo.s.get("eia_recommendations", {"reco_id": m.get("reco_id")}) or {}
    return {"mission": m, "tasks": tasks, "actions": mission_actions(m, tasks), "recommendation": reco,
            "hours": sum(int(t.get("estimated_hours") or 0) for t in tasks),
            "done": sum(t["status"] == "fait" for t in tasks)}


def decide(repo: Any, team_id: str, user: str, mission_id: str, objet: str, statut: str,
           task_id: str = "", assignment_id: str = "") -> dict:
    """Décision humaine sur une mission, une tâche ou une affectation de l'équipe (contrôles avant écriture)."""
    _human(user)
    mission = mission_of_team(repo, team_id, mission_id)
    if objet == "mission":
        if statut == "terminee" and any(t["status"] in OPEN_TASKS for t in repo.tasks(mission_id)):
            raise c.ContractError("Impossible de clôturer : des tâches sont encore ouvertes")
        repo.set_mission_status(mission_id, statut, user)
    elif objet == "tache":
        if not task_id:
            raise c.ContractError("task_id obligatoire pour une tâche")
        repo.set_task_status(mission_id, task_id, statut, user)
    elif objet == "affectation":
        row = repo.s.get("eia_assignments", {"assignment_id": assignment_id, "mission_id": mission_id})
        if not row:
            raise c.ContractError("Affectation inconnue ou appartenant à une autre mission")
        repo.decide_assignment(assignment_id, statut, user)
    else:
        raise c.ContractError("objet : mission | tache | affectation")
    return {"mission_id": mission_id, "objet": objet, "statut": statut, "decide_par": user,
            "task_id": task_id, "assignment_id": assignment_id, "mission_statut_avant": mission["status"]}


def open_recommendations(repo: Any, team_id: str) -> list[dict]:
    """Recommandations encore à traiter, avec l'éventuelle mission déjà préparée."""
    missions = {m["reco_id"]: m for m in repo.missions(team_id)}
    out = []
    for r in repo.recommendations(team_id):
        if r["status"] in ("proposee", "selectionnee"):
            m = missions.get(r["reco_id"])
            out.append({**r, "mission_id": m["mission_id"] if m else None, "mission_status": m["status"] if m else None})
    return out


def runs(repo: Any, team_id: str, limit: int = 20) -> list[dict]:
    return repo.s.find("eia_runs", {"team_id": team_id}, "started_at", limit=limit)


# ---------------- notifications ----------------

def alert_summary(alerts: list[dict]) -> dict:
    """Comptes séparés par nature : une erreur technique n'est jamais comptée comme anomalie métier."""
    open_ = [a for a in alerts if a["status"] in ("nouvelle", "vue")]
    biz = [a for a in open_ if a["kind"] == "metier"]
    return {"ouvertes_metier": len(biz), "critiques_metier": sum(a["severity"] == "critique" for a in biz),
            "ouvertes_techniques": sum(a["kind"] == "technique" for a in open_),
            "nouvelles": sum(a["status"] == "nouvelle" for a in alerts),
            "acquittees": sum(a["status"] == "acquittee" for a in alerts),
            "resolues": sum(a["status"] == "resolue" for a in alerts)}


def alert_actions(a: dict) -> list[dict]:
    return [{"target": t, "label": ACTION_LABELS["alert"][t], "allowed": True, "reason": ""}
            for t in next_statuses("alert", a["status"])]


def decide_alert(repo: Any, team_id: str, user: str, alert_id: str, statut: str) -> None:
    _human(user)
    row = repo.s.get("eia_alerts", {"alert_id": alert_id, "team_id": team_id})
    if not row:
        raise c.ContractError("Alerte inconnue ou appartenant à une autre équipe")
    repo.set_alert_status(alert_id, statut, user)


def notification_status(cfg: Any, alerts: list[dict], today: dt.date) -> dict:
    """État du canal d'envoi et aperçu du message (rien n'est envoyé depuis la page)."""
    enabled, min_sev, reason = al.notification_plan(cfg)
    eligible = [a for a in alerts if a["kind"] == "metier" and a["status"] == "nouvelle"
                and al.SEV_RANK[a["severity"]] >= al.SEV_RANK[min_sev]]
    subject, body = al.digest(cfg, eligible, today) if eligible else ("", "")
    n = cfg.notifications or {}
    return {"envoi_actif": enabled, "motif": reason, "gravite_min": min_sev, "canal": n.get("channel", ""),
            "destinataires": list(n.get("recipients") or []), "statut_canal": n.get("status", "non configuré"),
            "eligibles": len(eligible), "apercu_sujet": subject, "apercu_corps": body}
