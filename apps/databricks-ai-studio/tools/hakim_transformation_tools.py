"""Outils HakimAI Transformation (lot A : cadrage, découverte, cartographie). HakimAI propose, il ne décide jamais.

- Écritures limitées aux plans dont l'utilisateur est propriétaire : créer un plan, enregistrer le cadrage et la
  découverte, ajouter des éléments au statut « propose ». Chacune est tracée dans copilot_actions.
- Pas de fiche de validation pour ces écritures : rien n'est publié ni exécuté, et la décision (valider, rejeter)
  se prend uniquement sur la page Transformation. Aucun outil ne permet à HakimAI de changer un statut.
- Découverte : avec le jeton de l'utilisateur (Unity Catalog s'applique), structure + agrégats, jamais de lignes.
"""
from __future__ import annotations

from typing import Any

from backend import transformation as T
from backend.tool_registry import ToolContext, ToolError
from tools.hakim_tools import Platform, _p
from tools.hakim_write_tools import audit


def _svc(p: Platform) -> T.TransformationService:
    if p.transformation is None:
        p.transformation = T.TransformationService(T.SqlTransformationStore(p.repo.sql, p.t))
    return p.transformation


def _items_view(items: list[dict]) -> dict:
    out: dict[str, list] = {}
    for i in items:
        out.setdefault(i["item_type"], []).append(
            {"item_id": i["item_id"], "nom": i["name"], "statut": i["status"],
             "description": i["payload"].get("description", ""), "tables": i["evidence"].get("tables", []),
             "hypotheses": i["payload"].get("hypotheses", []), "note_decision": i.get("decision_note")})
    return out


def _guard(fn):
    """Erreurs de règle renvoyées au modèle telles quelles."""
    def run(ctx: ToolContext, **args):
        try:
            return fn(ctx, _p(ctx), **args)
        except T.TransformationError as e:
            raise ToolError(str(e)) from e
    run.__name__ = fn.__name__
    return run


STEP_OF = {"transformation_cadrage": 1, "transformation_decouvrir": 2, "transformation_proposer": 3}


def _one_step(p: Platform, tool_id: str) -> None:
    """Une étape par échange : l'utilisateur voit le résultat d'une étape avant la suivante (Platform recréée à chaque tour)."""
    step = STEP_OF[tool_id]
    done = sorted(p.transfo_steps - {step})
    if done:
        raise ToolError(f"Étape {done[0]} déjà réalisée dans ce message : présentez son résultat à l'utilisateur et "
                        f"attendez sa réponse avant l'étape {step} (une étape par échange).")
    p.transfo_steps.add(step)


def _write(tool_id: str, p: Platform, plan_id: str | None, args: dict, after: Any) -> str:
    return audit(p, tool_id, "transformation", plan_id, args, None, after, "succes")


@_guard
def transformation_plans(ctx: ToolContext, p: Platform) -> dict:
    svc, out = _svc(p), []
    for plan in svc.list_plans(p.user, p.is_admin):
        full = svc.get(plan["plan_id"], p.user, p.is_admin)
        steps = svc.progress(full, svc.items(plan["plan_id"], p.user, p.is_admin))
        current = next((s for s in steps if s["statut"] == "en_cours"), None)
        out.append({"plan_id": plan["plan_id"], "nom": plan["name"], "proprietaire": plan["owner"],
                    "modifiable": plan["owner"] == p.user, "etape_en_cours": current and current["libelle"],
                    "mis_a_jour": plan["updated_at"]})
    return {"plans": out, "nombre": len(out)}


@_guard
def transformation_etat(ctx: ToolContext, p: Platform, plan: str) -> dict:
    svc = _svc(p)
    full, items = svc.get(plan, p.user, p.is_admin), svc.items(plan, p.user, p.is_admin)
    return {"plan_id": full["plan_id"], "nom": full["name"], "proprietaire": full["owner"],
            "modifiable": full["owner"] == p.user, "etapes": svc.progress(full, items),
            "cadrage": full["context"],
            "cadrage_manquant": [k for k in T.CONTEXT_FIELDS if not full["context"].get(k)],
            "decouverte": T.discovery_summary(full["discovery"]),
            "elements": _items_view(items),
            "a_decider": sum(1 for i in items if i["status"] == "propose"),
            "rappel": "Les éléments se valident ou se rejettent sur la page Transformation, par le propriétaire."}


@_guard
def transformation_creer_plan(ctx: ToolContext, p: Platform, nom: str) -> dict:
    plan = _svc(p).create(nom, p.user)
    aid = _write("transformation_creer_plan", p, plan["plan_id"], {"nom": nom}, {"name": plan["name"]})
    return {"plan_id": plan["plan_id"], "nom": plan["name"], "action_id": aid,
            "suite": "Étape 1 : cadrage (secteur, objectifs, irritants, contraintes, périmètre)."}


@_guard
def transformation_cadrage(ctx: ToolContext, p: Platform, plan: str, **champs) -> dict:
    _one_step(p, "transformation_cadrage")
    ctx_saved = _svc(p).set_context(plan, p.user, {k: v for k, v in champs.items() if v not in (None, "")})
    aid = _write("transformation_cadrage", p, plan, {"plan": plan, **champs}, ctx_saved)
    return {"cadrage": ctx_saved, "manquant": [k for k in T.CONTEXT_FIELDS if not ctx_saved.get(k)], "action_id": aid}


@_guard
def transformation_decouvrir(ctx: ToolContext, p: Platform, plan: str) -> dict:
    svc = _svc(p)
    svc._owned(plan, p.user)   # contrôle avant de lancer les requêtes
    _one_step(p, "transformation_decouvrir")
    s = p.repo.s
    d = T.discover(lambda c, sc: list(ctx.workspace.tables.list(catalog_name=c, schema_name=sc)), ctx.sql,
                   s.catalog, s.schema)
    svc.set_discovery(plan, p.user, d)
    summary = T.discovery_summary(d)
    summary["action_id"] = _write("transformation_decouvrir", p, plan, {"plan": plan},
                                  {"tables": len(d["tables"]), "liens": len(d["liens_probables"])})
    return summary


@_guard
def transformation_proposer(ctx: ToolContext, p: Platform, plan: str, elements: list) -> dict:
    _one_step(p, "transformation_proposer")
    res = _svc(p).propose(plan, p.user, elements, origin="hakim")
    res["action_id"] = _write("transformation_proposer", p, plan, {"plan": plan, "elements": elements}, res)
    res["a_faire"] = "Demander à l'utilisateur de valider ou rejeter ces éléments sur la page Transformation."
    return res
