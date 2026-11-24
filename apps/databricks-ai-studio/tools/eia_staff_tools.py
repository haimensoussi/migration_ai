"""Outils EIA de l'agent RH (staffing) : personnel d'une équipe et simulation d'affectation.

Lecture seule, sous l'identité de l'utilisateur (droits Unity Catalog sur les tables eia_*).
Le classement est calculé par backend.eia.staffing ; le modèle l'explique sans le modifier.
L'enregistrement et la confirmation d'une affectation sont des décisions humaines (page Missions).
"""
from __future__ import annotations

import datetime as dt

from backend import config as app_config
from backend.eia import contracts as c
from backend.eia import staffing as sf
from backend.eia import store as st
from backend.eia import team_config as tc
from backend.tool_registry import ToolContext, ToolError, ToolSpec


def _today() -> dt.date:
    return dt.date.today()


def _repo(ctx: ToolContext) -> st.EiaRepository:
    s = app_config.load_settings()
    return st.EiaRepository(st.SqlEiaStore(ctx.sql, s.table))


def _team(team_id: str) -> tc.TeamConfig:
    try:
        cfg = tc.load(team_id, data_scope=app_config.data_scope())
    except tc.TeamConfigError as e:
        raise ToolError(f"Configuration d'équipe invalide ou absente : {e}") from e
    if not cfg.skills:
        raise ToolError(f"L'équipe {team_id} n'a pas de référentiel de compétences")
    return cfg


def eia_personnel(ctx: ToolContext, team_id: str, competence: str = "", niveau_min: int = 1) -> dict:
    cfg = _team(team_id)
    if competence and competence not in cfg.skill_ids():
        raise ToolError(f"Compétence inconnue : {competence}. Référentiel : {', '.join(sorted(cfg.skill_ids()))}")
    repo = _repo(ctx)
    people = repo.people(cfg.team_id)
    load = repo.workload_hours([p["person_id"] for p in people])
    rows = []
    for p in people:
        if competence and p["skills"].get(competence, 0) < niveau_min:
            continue
        rows.append({"person_id": p["person_id"], "nom": p["full_name"], "fonction": p["job_title"],
                     "service": p["department"], "region": p.get("region"), "disponibilite_pct": p["availability_pct"],
                     "charge_confirmee_h": load.get(p["person_id"], 0), "competences": p["skills"]})
    rows.sort(key=lambda r: (-(r["competences"].get(competence, 0) if competence else 0), r["person_id"]))
    return {"equipe": cfg.team_id, "personnes": len(rows), "liste": rows[:100], "tronque": len(rows) > 100,
            "referentiel": cfg.skills, "niveaux": sf.LEVELS,
            "avertissement": "Données de personnel fictives (démonstration) ; critères professionnels uniquement."}


def eia_affectation(ctx: ToolContext, team_id: str, competences: list, charge_heures: int, echeance: str = "") -> dict:
    cfg = _team(team_id)
    if echeance:
        try:
            due = dt.date.fromisoformat(echeance)
        except ValueError as e:
            raise ToolError("echeance : date AAAA-MM-JJ attendue") from e
        if due <= _today():
            raise ToolError("echeance : date future attendue")
    repo = _repo(ctx)
    people = repo.people(cfg.team_id)
    if not people:
        raise ToolError(f"Aucune personne active pour l'équipe {cfg.team_id}")
    load = repo.workload_hours([p["person_id"] for p in people])
    task = {"required_skills": competences, "estimated_hours": charge_heures, "due_date": echeance or None}
    try:
        top, excluded = sf.rank_candidates(task, people, load, cfg.skill_ids(), _today(), cfg.staffing)
    except c.ContractError as e:
        raise ToolError(str(e)) from e
    return {"equipe": cfg.team_id, "candidats": top, "ecartes": len(excluded),
            "motifs_ecart": sorted({x["motif"] for x in excluded})[:10],
            "methode": sf.__doc__.split("\n\n")[2].strip(), "parametres": cfg.staffing,
            "avertissement": ("Simulation : aucune affectation enregistrée. Pondérations à valider ; la décision "
                              "revient à un responsable. Données de personnel fictives.")}


_TEAM = {"type": "string", "description": "Identifiant de l'équipe métier (ex. sales)"}
_SKILL_ITEM = {"type": "object", "properties": {"skill": {"type": "string"}, "level": {"type": "integer"}}}

EIA_STAFF_TOOLS: list[ToolSpec] = [
    ToolSpec(
        tool_id="eia_personnel", name="Personnel d'équipe", category="EIA",
        description=("Liste le personnel affectable d'une équipe métier : fonction, disponibilité pour les missions, "
                     "charge déjà confirmée et compétences (niveau 1 à 5), avec le référentiel de compétences. "
                     "Filtre facultatif sur une compétence et un niveau minimal."),
        input_schema={"type": "object", "properties": {
            "team_id": _TEAM,
            "competence": {"type": "string", "description": "Identifiant de compétence du référentiel (facultatif)"},
            "niveau_min": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Niveau minimal (défaut 1)"}},
            "required": ["team_id"]},
        output_schema={"type": "object", "properties": {"liste": {"type": "array"}, "referentiel": {"type": "array"}}},
        executor="tools.eia_staff_tools:eia_personnel"),
    ToolSpec(
        tool_id="eia_affectation", name="Simulation d'affectation", category="EIA",
        description=("Agent RH : classe les personnes les plus adaptées à une tâche selon les compétences requises "
                     "(référentiel de l'équipe, niveau 1 à 5), la charge estimée et la disponibilité restante avant "
                     "l'échéance. Score, lacunes et justification sont calculés par le code : les citer tels quels. "
                     "Simulation uniquement : n'enregistre ni ne confirme aucune affectation."),
        input_schema={"type": "object", "properties": {
            "team_id": _TEAM,
            "competences": {"type": "array", "items": _SKILL_ITEM, "minItems": 1, "maxItems": 6,
                            "description": "Compétences requises [{skill, level}] (level 1 à 5, défaut 3)"},
            "charge_heures": {"type": "integer", "minimum": 1, "maximum": 400, "description": "Charge estimée (heures)"},
            "echeance": {"type": "string", "description": "Échéance AAAA-MM-JJ (facultatif : 30 jours)"}},
            "required": ["team_id", "competences", "charge_heures"]},
        output_schema={"type": "object", "properties": {"candidats": {"type": "array"}, "ecartes": {"type": "integer"}}},
        executor="tools.eia_staff_tools:eia_affectation"),
]
