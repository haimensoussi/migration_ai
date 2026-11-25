"""Outils EIA Factory : Catalogue d'Agents et Team Builder (découverte, architecture, déploiement).

Lecture et profil avec les droits de l'utilisateur ; aucune ligne lue (statistiques agrégées du Transformation
Center). Les seules écritures sont l'enregistrement d'un brouillon et la décision de mise en service ou de retrait,
après confirmation humaine, à l'identité du contexte.
"""
from __future__ import annotations

from backend import config as app_config
from backend import transformation as T
from backend.eia import agent_catalog as ac
from backend.eia import store as st
from backend.eia import team_builder as tb
from backend.eia.adapters import SqlKpiSource
from backend.eia.contracts import ContractError
from backend.tool_registry import ToolContext, ToolError, ToolSpec


def _repo(ctx: ToolContext) -> st.EiaRepository:
    return st.EiaRepository(st.SqlEiaStore(ctx.sql, app_config.load_settings().table))


def _discover(ctx: ToolContext, catalogue: str, schema: str, tables: list[str]):
    cat, sch, _ = app_config.data_scope()
    catalogue, schema = catalogue or cat, schema or sch
    if not tables:
        raise ToolError("tables : liste des tables à analyser obligatoire")
    if len(tables) > T.MAX_TABLES:
        raise ToolError(f"{T.MAX_TABLES} tables au maximum")
    return lambda: T.discover(lambda c, s: list(ctx.workspace.tables.list(catalog_name=c, schema_name=s)), ctx.sql,
                              catalogue, schema, prefix=None, tables=list(tables))


def _run(ctx: ToolContext, phase: str, team_id: str, nom: str, objectifs: list[str] | None, catalogue: str,
         schema: str, tables: list[str], kpis: list[str] | None) -> dict:
    try:
        return tb.run(_discover(ctx, catalogue, schema, tables), SqlKpiSource(ctx.sql), team_id=team_id, name=nom,
                      description=f"Équipe conçue par le Team Builder ({ctx.user_email or 'utilisateur'})",
                      objectives=objectifs, kpi_ids=kpis or None, owner=ctx.user_email, upto=phase,
                      data_scope=app_config.data_scope())
    except (tb.TeamBuilderError, T.TransformationError) as e:
        raise ToolError(str(e)) from e


def eia_catalogue_agents(ctx: ToolContext, vue: str = "synthese", code: str = "") -> dict:
    try:
        if vue == "fiche":
            return ac.card(code)
        if vue == "fiches":
            return {"fiches": [{k: c.get(k) for k in ("code", "nom", "statut", "capacites", "modeles_equipe")}
                               for c in ac.cards()]}
        if vue == "modeles_equipe":
            return {"modeles_equipe": ac.templates()}
        return ac.summary()
    except KeyError as e:
        raise ToolError(str(e)) from e


def eia_team_builder(ctx: ToolContext, phase: str, tables: list, team_id: str = "", nom: str = "",
                     objectifs: list | None = None, catalogue: str = "", schema: str = "",
                     kpis: list | None = None) -> dict:
    out = _run(ctx, phase, team_id, nom, objectifs, catalogue, schema, tables, kpis)
    out.update(persistant=False, avertissement="Aperçu : rien n'est enregistré ; KPI et seuils « à valider »")
    return out


def eia_team_builder_enregistrer(ctx: ToolContext, team_id: str, nom: str, tables: list, objectifs: list | None = None,
                                 catalogue: str = "", schema: str = "", kpis: list | None = None) -> dict:
    out = _run(ctx, "deploiement", team_id, nom, objectifs, catalogue, schema, tables, kpis)
    if "architecture" not in out:
        raise ToolError("Contrôle de découverte en échec : " + " ; ".join(out["controles"][-1]["bloquants"]))
    try:
        row = tb.build(out["architecture"], out["controles"], out.get("recette"), ctx.user_email)
        cid = _repo(ctx).save_team_config(row)
    except ContractError as e:
        raise ToolError(str(e)) from e
    return {"config_id": cid, "team_id": team_id, "statut": "brouillon", "controles": out["controles"],
            "mise_en_service_possible": not tb.deployable(row), "conditions_manquantes": tb.deployable(row)}


def eia_team_builder_decision(ctx: ToolContext, config_id: str, statut: str) -> dict:
    repo = _repo(ctx)
    row = repo.team_config(config_id)
    if not row:
        raise ToolError("Configuration d'équipe inconnue")
    try:
        repo.set_team_config_status(config_id, statut, ctx.user_email,
                                    tb.deployable(row) if statut == "en_service" else None)
    except ContractError as e:
        raise ToolError(str(e)) from e
    return {"config_id": config_id, "team_id": row["team_id"], "statut": statut, "decide_par": ctx.user_email}


_STR = {"type": "string"}
_LIST = {"type": "array", "items": {"type": "string"}}
_BUILD = {"team_id": {"type": "string", "description": "Identifiant de la nouvelle équipe (minuscules, chiffres, _)"},
          "nom": _STR, "objectifs": _LIST,
          "catalogue": {"type": "string", "description": "Défaut : zone de données de la plateforme"},
          "schema": _STR, "tables": {**_LIST, "description": "Tables à analyser (noms courts)"},
          "kpis": {**_LIST, "description": "KPI candidats retenus (défaut : tous, 12 au plus)"}}


def _spec(tool_id: str, name: str, desc: str, props: dict, required: list[str], write: bool = False) -> ToolSpec:
    return ToolSpec(tool_id=tool_id, name=name, category="EIA", description=desc,
                    input_schema={"type": "object", "properties": props, "required": required},
                    output_schema={"type": "object"}, executor="tools.eia_factory_tools:" + tool_id,
                    requires_confirmation=write, read_only=not write)


EIA_FACTORY_TOOLS = [
    _spec("eia_catalogue_agents", "Catalogue d'agents EIA", "Catalogue officiel AG01-AG11 : synthèse, fiches, fiche "
          "détaillée d'un code (capacités, paramètres, interfaces, garde-fous, reste à faire) ou modèles d'équipe avec "
          "leur état. Lecture seule.",
          {"vue": {"type": "string", "enum": ["synthese", "fiches", "fiche", "modeles_equipe"]}, "code": _STR}, []),
    _spec("eia_team_builder", "Team Builder EIA (aperçu)", "EIA Factory : découverte de la source (profil agrégé, KPI "
          "candidats), proposition d'architecture (modèles AG, configuration) et déploiement en recette (cycle complet "
          "en mémoire). Chaque phase est fermée par un contrôle AG08. Aucune écriture ; aucun seuil inventé.",
          {"phase": {"type": "string", "enum": list(tb.PHASES)}, **_BUILD}, ["phase", "tables"]),
    _spec("eia_team_builder_enregistrer", "Enregistrer une équipe EIA (brouillon)", "Après confirmation humaine, "
          "rejoue les trois phases et enregistre la configuration en brouillon versionné avec ses contrôles et sa "
          "recette. Ne met pas l'équipe en service.", _BUILD, ["team_id", "nom", "tables"], True),
    _spec("eia_team_builder_decision", "Mise en service d'une équipe EIA", "Après décision explicite et confirmation "
          "humaine : met en service (contrôles AG08 et recette réussis obligatoires) ou retire une configuration. Ne "
          "jamais lancer à sa propre initiative.",
          {"config_id": _STR, "statut": {"type": "string", "enum": ["en_service", "retiree"]}},
          ["config_id", "statut"], True),
]
