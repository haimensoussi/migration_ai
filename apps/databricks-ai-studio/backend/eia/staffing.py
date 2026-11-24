"""EIA Core - affectation des tâches de mission au personnel (agent RH « staffing »).

Le classement est calculé par le code, de façon explicable, à partir de critères professionnels
uniquement : compétences requises (niveau 1 à 5), capacité et charge déjà confirmée.
Le modèle de langage peut expliquer le classement, jamais le modifier.
Aucune affectation n'est effective sans confirmation d'un responsable (EiaRepository.decide_assignment).

Score = poids_compétences x adéquation + poids_disponibilité x disponibilité (pondérations de la
configuration d'équipe, statut « à valider »).
  adéquation    : moyenne, sur les compétences requises, de min(niveau détenu / niveau requis, 1)
  disponibilité : min(heures libres sur l'horizon / charge estimée, 1)
Une personne ne possédant pas du tout une compétence requise est écartée.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from backend.eia.contracts import ContractError

LEVELS = {1: "notions", 2: "pratique encadrée", 3: "autonome", 4: "confirmé", 5: "référent"}
DEFAULTS = {"skill_weight": 0.7, "availability_weight": 0.3, "top_n": 3, "default_horizon_days": 30}


def normalize_requirements(required: Any, known_skills: set[str]) -> list[dict]:
    """[{skill, level}] ; un identifiant seul vaut niveau 3 (autonome). Refuse les compétences hors référentiel."""
    out, seen = [], set()
    for r in required or []:
        skill, level = (r, 3) if isinstance(r, str) else (r.get("skill"), r.get("level", 3))
        if skill not in known_skills:
            raise ContractError(f"Compétence hors référentiel : {skill}")
        if not isinstance(level, int) or not 1 <= level <= 5:
            raise ContractError(f"Niveau requis invalide pour {skill} : {level} (1 à 5)")
        if skill not in seen:
            seen.add(skill)
            out.append({"skill": skill, "level": level})
    return out


def free_hours(person: dict, load_hours: int, horizon_days: int) -> float:
    weekly = (person.get("capacity_hours_week") or 0) * (person.get("availability_pct") or 0) / 100
    return max(weekly * max(horizon_days, 7) / 7 - load_hours, 0.0)


def rank_candidates(task: dict, people: list[dict], load: dict[str, int], known_skills: set[str],
                    today: dt.date, settings: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Classe les personnes pour une tâche. Renvoie (candidats retenus, personnes écartées avec motif)."""
    s = {**DEFAULTS, **{k: v for k, v in (settings or {}).items() if k in DEFAULTS}}
    req = normalize_requirements(task.get("required_skills"), known_skills)
    hours = task.get("estimated_hours")
    if hours is not None and (not isinstance(hours, int) or hours <= 0):
        raise ContractError("estimated_hours : entier positif attendu")
    due = task.get("due_date")
    horizon = (dt.date.fromisoformat(str(due)[:10]) - today).days if due else s["default_horizon_days"]
    ranked, excluded = [], []
    for p in people:
        if p.get("status", "actif") != "actif":
            continue
        skills = p.get("skills") or {}
        missing = [r["skill"] for r in req if not skills.get(r["skill"])]
        if missing:
            excluded.append({"person_id": p["person_id"], "motif": "compétence absente : " + ", ".join(missing)})
            continue
        ratios = [min(skills[r["skill"]] / r["level"], 1.0) for r in req]
        skill_score = sum(ratios) / len(ratios) if ratios else 1.0
        gaps = [{"skill": r["skill"], "detenu": skills[r["skill"]], "requis": r["level"]}
                for r in req if skills[r["skill"]] < r["level"]]
        cur = int(load.get(p["person_id"], 0))
        free = free_hours(p, cur, horizon)
        if hours:
            avail = min(free / hours, 1.0)
        else:
            cap = free_hours(p, 0, horizon)
            avail = free / cap if cap else 0.0
        if avail <= 0:
            excluded.append({"person_id": p["person_id"], "motif": "aucune disponibilité sur l'horizon"})
            continue
        score = s["skill_weight"] * skill_score + s["availability_weight"] * avail
        ranked.append({"person_id": p["person_id"], "full_name": p.get("full_name", ""), "job_title": p.get("job_title", ""),
                       "score": round(score, 4), "skill_score": round(skill_score, 4), "availability_score": round(avail, 4),
                       "free_hours": round(free, 1), "load_hours": cur, "gaps": gaps,
                       "levels": {r["skill"]: skills[r["skill"]] for r in req}})
    ranked.sort(key=lambda c: (-c["score"], c["load_hours"], c["person_id"]))
    top = ranked[:int(s["top_n"])]
    for c in top:
        c["rationale"] = rationale(c, req, hours, horizon)
    return top, excluded


def rationale(c: dict, req: list[dict], hours: int | None, horizon: int) -> str:
    """Justification rédigée par le code (aucun chiffre inventé)."""
    parts = [f"{c['full_name']} ({c['job_title']}) : score {c['score']:.2f}"]
    if req:
        parts.append("compétences " + ", ".join(
            f"{r['skill']} {c['levels'][r['skill']]}/{r['level']} requis" for r in req))
    parts.append(f"{c['free_hours']:.0f} h libres sur {horizon} jours (charge confirmée {c['load_hours']} h"
                 + (f", tâche estimée à {hours} h)" if hours else ")"))
    if c["gaps"]:
        parts.append("lacunes : " + ", ".join(f"{g['skill']} ({g['detenu']} au lieu de {g['requis']})" for g in c["gaps"]))
    return " ; ".join(parts) + ". Proposition à confirmer par un responsable."


def propose_for_task(repo: Any, cfg: Any, mission_id: str, task_id: str, today: dt.date,
                     proposer: str = "agent:staffing") -> dict:
    """Calcule et enregistre les propositions d'affectation d'une tâche (statut « proposée »)."""
    task = next((t for t in repo.tasks(mission_id) if t["task_id"] == task_id), None)
    if task is None:
        raise ContractError(f"Tâche inconnue : {task_id}")
    people = repo.people(cfg.team_id)
    if not people:
        return {"candidats": [], "ecartes": [], "motif": f"aucune personne active pour l'équipe {cfg.team_id}"}
    load = repo.workload_hours([p["person_id"] for p in people])
    top, excluded = rank_candidates(task, people, load, cfg.skill_ids(), today, cfg.staffing)
    ids = repo.propose_assignments(mission_id, task_id, top, proposer) if top else []
    for c, aid in zip(top, ids):
        c["assignment_id"] = aid
    return {"candidats": top, "ecartes": excluded, "parametres_statut": (cfg.staffing or {}).get("status", "a_valider"),
            "motif": "" if top else "aucune personne ne réunit les compétences requises avec de la disponibilité"}
