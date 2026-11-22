"""Outils HakimAI Transformation (étapes 1 à 7). HakimAI propose, il ne décide jamais.

- Écritures limitées aux plans dont l'utilisateur est propriétaire : créer un plan, enregistrer le cadrage et la
  découverte, ajouter des éléments au statut « propose ». Chacune est tracée dans copilot_actions.
- Pas de fiche de validation pour ces écritures : rien n'est publié ni exécuté, et la décision (valider, rejeter)
  se prend uniquement sur la page Transformation. Aucun outil ne permet à HakimAI de changer un statut.
- Découverte : avec le jeton de l'utilisateur (Unity Catalog s'applique), structure + agrégats, jamais de lignes.
- Étape 5 : la réutilisation d'un agent, outil, flux ou équipe est vérifiée sur les objets que l'utilisateur voit.
- Plan de travail : sur la page HakimAI (plan_required), chaque écriture exige un plan en cours qui l'annonce
  (backend/hakim_plan.py) ; hakim_plan_travail s'exécute directement, sans fiche de validation.
"""
from __future__ import annotations

from typing import Any

from backend import hakim_plan as HP
from backend import transformation as T
from backend.tool_registry import ToolContext, ToolError
from tools.hakim_tools import Platform, _p, _visible_agents
from tools.hakim_write_tools import audit


def _svc(p: Platform) -> T.TransformationService:
    if p.transformation is None:
        p.transformation = T.TransformationService(T.SqlTransformationStore(p.repo.sql, p.t))
    return p.transformation


_EXTRA = ("domaine", "processus", "objectif", "gain_attendu", "limites", "cas_usage", "mode", "existant",
          "existant_nom", "membres", "outils", "ordre", "valeur", "effort", "justification", "dependances",
          "prerequis", "risques", "realisation")


def _items_view(items: list[dict]) -> dict:
    out: dict[str, list] = {}
    for i in items:
        row = {"item_id": i["item_id"], "nom": i["name"], "statut": i["status"],
               "description": i["payload"].get("description", ""), "tables": i["evidence"].get("tables", []),
               "hypotheses": i["payload"].get("hypotheses", []), "note_decision": i.get("decision_note")}
        row.update({k: i["payload"][k] for k in _EXTRA if i["payload"].get(k)})
        out.setdefault(i["item_type"], []).append(row)
    return out


def _catalog(p: Platform) -> dict:
    teams = [t for t in (p.teams.list_teams() if p.teams else [])
             if p.is_admin or t["status"] == "publie" or t.get("owner") == p.user]
    agents = _visible_agents(p) if hasattr(p.repo, "list_agents") else []
    tools = p.repo.list_tools() if hasattr(p.repo, "list_tools") else []
    return T.platform_catalog(agents, tools, teams)


def _existing(p: Platform) -> dict:
    """Objets de la plateforme visibles par l'utilisateur, réutilisables à l'étape 5 ({type: {identifiant: nom}})."""
    return T.catalog_names(_catalog(p))


def _guard(fn):
    """Erreurs de règle renvoyées au modèle telles quelles."""
    def run(ctx: ToolContext, **args):
        p = _p(ctx)
        try:
            if p.plan_required:
                HP.check(p.work_plan, fn.__name__, args.get("plan"))
            return fn(ctx, p, **args)
        except (T.TransformationError, HP.PlanError) as e:
            raise ToolError(str(e)) from e
    run.__name__ = fn.__name__
    return run


STEP_OF = {"transformation_cadrage": 1, "transformation_decouvrir": 2,
           "transformation_feuille_route": 6, "transformation_suivre": 7, "transformation_relier": 7}


def _one_step(p: Platform, step: int) -> None:
    """Une étape par échange : l'utilisateur voit le résultat d'une étape avant la suivante (Platform recréée à chaque tour)."""
    done = sorted(p.transfo_steps - {step})
    if done:
        raise ToolError(f"Étape {done[0]} déjà réalisée dans ce message : présentez son résultat à l'utilisateur et "
                        f"attendez sa réponse avant l'étape {step} (une étape par échange).")
    p.transfo_steps.add(step)


def _write(tool_id: str, p: Platform, plan_id: str | None, args: dict, after: Any) -> str:
    if p.plan_required and p.work_plan.get("plan_travail_id"):
        args = {**args, "plan_travail_id": p.work_plan["plan_travail_id"]}
    aid = audit(p, tool_id, "transformation", plan_id, args, None, after, "succes")
    if p.plan_required:
        HP.consume(p.work_plan, tool_id)
    return aid


def hakim_plan_travail(ctx: ToolContext, **args) -> dict:
    """Exécution directe : contrôle la forme, enregistre le plan dans la conversation et le trace."""
    p = _p(ctx)
    from backend import hakim   # import tardif : backend.hakim importe les outils
    bad = HP.issue(args, {t.tool_id for t in hakim.TOOLS})   # plan mal formé : erreur rendue au modèle, rien d'enregistré
    if bad:
        raise ToolError(bad)
    plan = HP.approve(p.work_plan, args)
    aid = audit(p, HP.PLAN_TOOL, "plan_travail", plan["plan_travail_id"], HP.normalize(args), None,
                {"etapes": HP.describe(args), "restant": plan["restant"]}, "succes")
    return {"plan_travail_id": plan["plan_travail_id"], "etapes": HP.describe(args),
            "ecritures_permises": plan["restant"], "action_id": aid,
            "a_faire": "Les étapes sont affichées à l'utilisateur : exécute-les maintenant, dans l'ordre, sans demander "
                       "de validation et sans recopier la liste ; une étape de transformation par message, aucune "
                       "écriture non annoncée. Termine par un compte rendu court (fait, écart, à décider)."}


@_guard
def transformation_plans(ctx: ToolContext, p: Platform) -> dict:
    svc, out = _svc(p), []
    for plan in svc.list_plans(p.user, p.is_admin):
        full = svc.get(plan["plan_id"], p.user, p.is_admin)
        steps = svc.progress(full, svc.items(plan["plan_id"], p.user, p.is_admin), _catalog(p))
        current = next((s for s in steps if s["statut"] == "en_cours"), None)
        out.append({"plan_id": plan["plan_id"], "nom": plan["name"], "proprietaire": plan["owner"],
                    "modifiable": plan["owner"] == p.user, "etape_en_cours": current and current["libelle"],
                    "mis_a_jour": plan["updated_at"]})
    return {"plans": out, "nombre": len(out)}


@_guard
def transformation_etat(ctx: ToolContext, p: Platform, plan: str) -> dict:
    svc = _svc(p)
    full, items, catalog = svc.get(plan, p.user, p.is_admin), svc.items(plan, p.user, p.is_admin), _catalog(p)
    return {"plan_id": full["plan_id"], "nom": full["name"], "proprietaire": full["owner"],
            "modifiable": full["owner"] == p.user, "etapes": svc.progress(full, items, catalog),
            "cadrage": full["context"],
            "cadrage_manquant": [k for k in T.CONTEXT_FIELDS if not full["context"].get(k)],
            "decouverte": T.discovery_summary(full["discovery"]),
            "elements": _items_view(items),
            "feuille_de_route": svc.planned(items),
            "suivi_generation": svc.tracking(items, catalog),
            "a_decider": sum(1 for i in items if i["status"] == "propose"),
            "incoherences": svc.coherence(items),
            "rappel": "Les éléments se valident ou se rejettent sur la page Transformation, par le propriétaire."}


@_guard
def transformation_creer_plan(ctx: ToolContext, p: Platform, nom: str) -> dict:
    plan = _svc(p).create(nom, p.user)
    aid = _write("transformation_creer_plan", p, plan["plan_id"], {"nom": nom}, {"name": plan["name"]})
    return {"plan_id": plan["plan_id"], "nom": plan["name"], "action_id": aid,
            "suite": "Étape 1 : cadrage (secteur, objectifs, irritants, contraintes, périmètre)."}


@_guard
def transformation_cadrage(ctx: ToolContext, p: Platform, plan: str, **champs) -> dict:
    _one_step(p, STEP_OF["transformation_cadrage"])
    ctx_saved = _svc(p).set_context(plan, p.user, {k: v for k, v in champs.items() if v not in (None, "")})
    aid = _write("transformation_cadrage", p, plan, {"plan": plan, **champs}, ctx_saved)
    return {"cadrage": ctx_saved, "manquant": [k for k in T.CONTEXT_FIELDS if not ctx_saved.get(k)], "action_id": aid}


@_guard
def transformation_decouvrir(ctx: ToolContext, p: Platform, plan: str) -> dict:
    svc = _svc(p)
    owned = svc._owned(plan, p.user)   # contrôle avant de lancer les requêtes
    _one_step(p, STEP_OF["transformation_decouvrir"])
    s = p.repo.s
    per = T.perimeter_args(owned.get("context"), s.catalog, s.schema)   # périmètre choisi sur la page, sinon défaut
    d = T.discover(lambda c, sc: list(ctx.workspace.tables.list(catalog_name=c, schema_name=sc)), ctx.sql,
                   per["catalog"], per["schema"], prefix=per["prefix"], tables=per["tables"] or None,
                   tags=lambda c, sc: (ctx.sql.query(T.column_tags_query(c), {"schema": sc}) or {}).get("rows", []))
    svc.set_discovery(plan, p.user, d)
    summary = T.discovery_summary(d)
    summary["action_id"] = _write("transformation_decouvrir", p, plan, {"plan": plan},
                                  {"tables": len(d["tables"]), "liens": len(d["liens_probables"])})
    return summary


@_guard
def transformation_proposer(ctx: ToolContext, p: Platform, plan: str, elements: list) -> dict:
    step = T.proposal_step(elements if isinstance(elements, list) else [])
    _one_step(p, step)
    res = _svc(p).propose(plan, p.user, elements, origin="hakim", existing=_existing(p) if step in (5, 6) else None)
    res["action_id"] = _write("transformation_proposer", p, plan, {"plan": plan, "elements": elements}, res)
    res["a_faire"] = "Demander à l'utilisateur de valider ou rejeter ces éléments sur la page Transformation."
    return res


@_guard
def transformation_feuille_route(ctx: ToolContext, p: Platform, plan: str, vagues: list) -> dict:
    _one_step(p, STEP_OF["transformation_feuille_route"])
    svc = _svc(p)
    elements = [{"type": "vague", **v} for v in (vagues or [])]
    res = svc.propose(plan, p.user, elements, origin="hakim")
    res["action_id"] = _write("transformation_feuille_route", p, plan, {"plan": plan, "vagues": vagues}, res)
    res["a_faire"] = "Demander à l'utilisateur de valider ou rejeter ces vagues sur la page Transformation."
    return res


@_guard
def transformation_suivre(ctx: ToolContext, p: Platform, plan: str) -> dict:
    _one_step(p, STEP_OF["transformation_suivre"])
    svc = _svc(p)
    items, catalog = svc.items(plan, p.user, p.is_admin), _catalog(p)
    suivi = svc.tracking(items, catalog)
    after = {"suivi": len(suivi), "publies": sum(x["statut"] == "publie" for x in suivi)}
    return {"plan_id": plan, "suivi": suivi, "action_id": _write("transformation_suivre", p, plan, {"plan": plan}, after),
            "rappel": "La publication se fait depuis l'écran de l'objet ; reliez ensuite le brouillon ou l'objet publié au plan."}


@_guard
def transformation_relier(ctx: ToolContext, p: Platform, plan: str, element: str, objet: str) -> dict:
    _one_step(p, STEP_OF["transformation_relier"])
    linked = _svc(p).link(plan, p.user, element, objet, _catalog(p))
    linked["action_id"] = _write("transformation_relier", p, plan,
                                  {"plan": plan, "element": element, "objet": objet}, linked)
    linked["suite"] = "Vérifier le suivi, tester le brouillon, puis demander sa publication depuis l'écran natif."
    return linked
