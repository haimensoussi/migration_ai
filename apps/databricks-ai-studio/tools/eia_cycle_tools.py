"""Outils EIA du cycle complet : aperçus en lecture seule, persistance après confirmation dans HAKIM.

Pas d'identité de service ni de destinataire implicite. Les décisions prennent l'identité du contexte,
jamais un utilisateur fourni par le modèle. Les autorisations de stockage restent celles de Unity Catalog.
"""
from __future__ import annotations

from backend import config as app_config
from backend.eia import console
from backend.eia import engine
from backend.eia.contracts import ContractError
from backend.eia import store as st
from backend.eia import team_config as tc
from backend.eia.adapters import SqlKpiSource
from backend.tool_registry import ToolContext, ToolError, ToolSpec


def _team(team_id: str, ctx: ToolContext | None = None) -> tc.TeamConfig:
    """Équipe versionnée (config/teams) ou équipe mise en service par le Team Builder."""
    from backend.eia import team_builder as tb
    try:
        return tb.resolve(team_id, _repo(ctx) if ctx is not None else None, app_config.data_scope())
    except tc.TeamConfigError as e:
        raise ToolError(str(e)) from e


def _repo(ctx: ToolContext) -> st.EiaRepository:
    settings = app_config.load_settings()
    return st.EiaRepository(st.SqlEiaStore(ctx.sql, settings.table))


def eia_apercu_cycle(ctx: ToolContext, team_id: str) -> dict:
    cfg = _team(team_id, ctx)
    real = _repo(ctx)
    memory = st.EiaRepository(st.MemoryEiaStore())
    # Lectures RH différées à l'étape staffing : un refus de lecture devient une erreur d'étape,
    # sans empêcher les constats et recommandations métier. Toutes les écritures restent en mémoire.
    memory.people = real.people
    memory.workload_hours = real.workload_hours
    out = engine.run_cycle(cfg, SqlKpiSource(ctx.sql), memory, actor=ctx.user_email or "agent:eia")
    out.update(persistant=False, avertissement="Aperçu : identifiants temporaires, aucune écriture SQL ni notification")
    return out


def eia_cycle(ctx: ToolContext, team_id: str) -> dict:
    engine._human(ctx.user_email)
    out = engine.run_cycle(_team(team_id, ctx), SqlKpiSource(ctx.sql), _repo(ctx), actor=ctx.user_email)
    out["persistant"] = True
    return out


def eia_preparer_mission(ctx: ToolContext, team_id: str, recommendation_id: str) -> dict:
    return engine.prepare_mission(_team(team_id, ctx), _repo(ctx), recommendation_id, ctx.user_email,
                                  source=SqlKpiSource(ctx.sql))


def eia_bilan_mission(ctx: ToolContext, team_id: str, mission_id: str) -> dict:
    return engine.learn_mission(_team(team_id, ctx), _repo(ctx), SqlKpiSource(ctx.sql), mission_id)


def eia_suivi_mission(ctx: ToolContext, team_id: str, mission_id: str, objet: str, statut: str,
                     task_id: str = "", assignment_id: str = "") -> dict:
    """Décision confirmée par le runtime ; même chemin que la page Missions (backend.eia.console.decide)."""
    cfg = _team(team_id, ctx)
    try:
        return console.decide(_repo(ctx), cfg.team_id, ctx.user_email, mission_id, objet, statut, task_id, assignment_id)
    except ContractError as e:
        raise ToolError(str(e)) from e


_TEAM = {"type": "string", "description": "Équipe métier configurée (ex. sales)"}
_STR = {"type": "string"}


def _spec(tool_id: str, name: str, desc: str, props: dict, required: list[str], write: bool = False) -> ToolSpec:
    return ToolSpec(tool_id=tool_id, name=name, category="EIA", description=desc,
                    input_schema={"type": "object", "properties": {"team_id": _TEAM, **props},
                                  "required": ["team_id", *required]},
                    output_schema={"type": "object"}, executor="tools.eia_cycle_tools:" + tool_id,
                    requires_confirmation=write, read_only=not write)


EIA_CYCLE_TOOLS = [
    _spec("eia_apercu_cycle", "Aperçu du cycle EIA", "Exécute les six rôles EIA : constats, prévisions, règles, "
          "recommandations et aperçus de missions/affectations. Aucune écriture persistante. Identifiants temporaires, "
          "ne pas les utiliser pour créer une mission ; employer eia_cycle après confirmation.", {}, []),
    _spec("eia_cycle", "Cycle EIA historisé", "Après confirmation humaine, historise constats, prévisions, alertes "
          "et recommandations proposées. Ne crée aucune mission et ne confirme aucune affectation. Aucun envoi externe.",
          {}, [], True),
    _spec("eia_preparer_mission", "Préparer une mission EIA", "Après sélection explicite de la recommandation par "
          "l'utilisateur et confirmation, crée une mission en brouillon, ses tâches et des affectations proposées. "
          "Ne valide pas la mission et ne confirme pas les affectations. Utiliser un recommendation_id du cycle historisé.",
          {"recommendation_id": _STR}, ["recommendation_id"], True),
    _spec("eia_suivi_mission", "Décision et suivi de mission EIA", "Après décision explicite et confirmation humaine, "
          "change le statut de mission, tâche ou affectation. La confirmation d'affectation exige une mission validée. "
          "Ne clôture pas une mission avec des tâches ouvertes. Chaque décision reste distincte.",
          {"mission_id": _STR, "objet": {"type": "string", "enum": ["mission", "tache", "affectation"]},
           "statut": {"type": "string", "enum": ["validee", "en_cours", "terminee", "annulee", "fait", "bloque",
                                                    "a_faire", "annule", "confirmee", "refusee"]},
           "task_id": _STR, "assignment_id": _STR}, ["mission_id", "objet", "statut"], True),
    _spec("eia_bilan_mission", "Bilan de mission EIA", "LEARN : en lecture seule, avancement et comparaison des KPI "
          "après clôture à la référence initiale figée. Signale données manquantes, périodes inchangées et versions "
          "incompatibles. Ne déduit pas une causalité et ne modifie aucun seuil ni règle.",
          {"mission_id": _STR}, ["mission_id"]),
]
