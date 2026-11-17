"""Exécuteurs des flux Power Automate (mode boîte d'échange) : dépôt d'une demande et lecture de sa réponse.

- La table `flux_demandes` est écrite par le service principal de l'App (ctx.app_sql) ; l'utilisateur est
  enregistré dans user_name et seul lui peut relire ses demandes.
- Les valeurs fixes du créateur sont fusionnées ici et ne sont jamais renvoyées au modèle.
- Aucun appel réseau sortant : Power Automate lit la table via le connecteur Azure Databricks.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid

from backend import flux
from backend.config import load_settings
from backend.tool_registry import ToolContext, ToolError, ToolSpec

DEMANDE_ID = re.compile(r"^[0-9a-f]{32}$")


def _table(name: str = flux.TABLE) -> str:
    return load_settings().table(name)


def _check_dates(spec: ToolSpec, args: dict) -> None:
    for p in (spec.config or {}).get("parametres") or []:
        v = args.get(p["nom"])
        if p.get("type") == "date" and v not in (None, ""):
            try:
                dt.date.fromisoformat(str(v))
            except ValueError as e:
                raise ToolError(f"Date invalide pour {p['nom']} : AAAA-MM-JJ attendu.") from e


def submit(app_sql, spec: ToolSpec, args: dict, user: str, conversation_id: str = "", agent_id: str = "",
           test: bool = False) -> dict:
    """Dépose une demande en_attente. Utilisé par l'outil (agents) et par le banc de test de la page Flux."""
    if app_sql is None:
        raise ToolError("Boîte d'échange des flux indisponible dans ce contexte : demande non déposée.")
    if not user:
        raise ToolError("Utilisateur inconnu : demande refusée.")
    if not flux.is_flux(spec):
        raise ToolError(f"« {spec.tool_id} » n'est pas un flux.")
    cfg = spec.config or {}
    if cfg.get("mode", "boite") != "boite":
        raise ToolError("Mode de connexion non disponible dans ce lot : seule la boîte d'échange est prise en charge.")
    _check_dates(spec, args)
    params = {**args, **(cfg.get("valeurs_fixes") or {})}   # les valeurs fixes priment sur celles de l'agent
    did = uuid.uuid4().hex
    app_sql.execute(
        f"INSERT INTO {_table()} (demande_id, flux_id, flux_version, conversation_id, agent_id, user_name, parametres, "
        "statut, reponse, erreur, test, created_at, pris_en_charge_at, termine_at) "
        "VALUES (:id, :flux, :ver, :conv, :agent, :user, :params, 'en_attente', NULL, NULL, :test, "
        "current_timestamp(), NULL, NULL)",
        {"id": did, "flux": spec.tool_id, "ver": str(spec.version), "conv": conversation_id or "",
         "agent": agent_id or "", "user": user, "params": json.dumps(params, ensure_ascii=False, default=str),
         "test": bool(test)})
    return {"demande_id": did, "flux": spec.tool_id, "statut": "en_attente", "test": bool(test),
            "parametres_transmis": args,
            "message": (f"Demande déposée. Power Automate la traite de façon asynchrone (délai indicatif : "
                        f"{cfg.get('delai_minutes', 60)} min). Lire la réponse avec flux_suivi(demande_id) ; "
                        "ne pas inventer de résultat en attendant.")}


def call_flow(ctx: ToolContext, spec: ToolSpec, **args) -> dict:
    return submit(getattr(ctx, "app_sql", None), spec, args, ctx.user_email, ctx.conversation_id,
                  getattr(ctx, "agent_id", ""))


call_flow.needs_spec = True


def read_request(app_sql, demande_id: str, user: str) -> dict:
    if app_sql is None:
        raise ToolError("Boîte d'échange des flux indisponible dans ce contexte.")
    did = str(demande_id or "").strip().lower()
    if not DEMANDE_ID.match(did):
        raise ToolError("Identifiant de demande invalide : 32 caractères hexadécimaux attendus.")
    r = app_sql.query(
        f"SELECT d.demande_id, d.flux_id, d.statut, d.reponse, d.erreur, d.test, "
        "CAST(d.created_at AS STRING) AS created_at, CAST(d.termine_at AS STRING) AS termine_at, "
        "timestampdiff(MINUTE, d.created_at, current_timestamp()) AS age_minutes, t.config "
        f"FROM {_table()} d LEFT JOIN {_table('tools')} t ON t.tool_id = d.flux_id "
        "WHERE d.demande_id = :id AND d.user_name = :u", {"id": did, "u": user or ""}, row_limit=1)
    if not r["rows"]:
        raise ToolError("Demande introuvable pour cet utilisateur.")
    x = r["rows"][0]
    try:
        delai = int((json.loads(x.get("config") or "{}") or {}).get("delai_minutes") or 60)
    except (TypeError, ValueError, json.JSONDecodeError):
        delai = 60
    age = int(x.get("age_minutes") or 0)
    statut = x["statut"]
    out = {"demande_id": did, "flux": x["flux_id"], "statut": statut, "cree_le": x.get("created_at"),
           "termine_le": x.get("termine_at"), "anciennete_minutes": age}
    if statut == "en_attente" and age > delai:
        out["statut"] = "expiree"   # statut logique : la ligne reste en_attente dans la table
        out["message"] = (f"Aucune prise en charge après {age} min (délai : {delai} min) : le flux Power Automate "
                          "est peut-être arrêté. Prévenir le propriétaire du flux.")
    elif statut in ("en_attente", "en_cours"):
        out["message"] = "Pas encore de réponse : réessayer plus tard, sans inventer de résultat."
    elif statut == "terminee":
        out["reponse"] = flux.parse_json(x.get("reponse"))
    elif statut == "erreur":
        out["erreur"] = x.get("erreur") or "Erreur signalée par le flux, sans détail."
    return out


def flux_suivi(ctx: ToolContext, demande_id: str) -> dict:
    return read_request(getattr(ctx, "app_sql", None), demande_id, ctx.user_email)
