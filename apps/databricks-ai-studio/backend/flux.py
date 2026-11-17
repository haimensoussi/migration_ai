"""Rubrique Flux : flux Power Automate utilisables comme outils par les agents (lot 1, mode boîte d'échange).

Un flux est un ToolSpec de catégorie « Flux », sans code : sa configuration décrit les paramètres attendus, les
valeurs fixées par le créateur (cachées au modèle) et la réponse. L'agent dépose une demande dans la table
`flux_demandes` ; le flux Power Automate la lit (connecteur Azure Databricks), l'exécute et y écrit sa réponse.
Aucun appel sortant depuis Databricks.
"""
from __future__ import annotations

import json
import re
import unicodedata

from backend.tool_registry import ToolSpec

EXECUTOR = "tools.flow_tools:call_flow"
CATEGORY = "Flux"
TABLE = "flux_demandes"
PREFIX = "flux_"
TYPES = ("string", "number", "integer", "boolean", "date", "enum")
TYPE_LABELS = {"string": "texte", "number": "nombre", "integer": "entier", "boolean": "oui/non", "date": "date",
               "enum": "liste de valeurs"}
KINDS = ("lecture", "action")
STATUTS = ("en_attente", "en_cours", "terminee", "erreur")
PARAM = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")
FLUX_ID = re.compile(r"^flux_[a-z0-9_]{2,40}$")
SUFFIX = (" Flux Power Automate asynchrone : renvoie un demande_id ; la réponse arrive plus tard, "
          "la lire avec flux_suivi.")


def is_flux(spec: ToolSpec) -> bool:
    return spec.executor == EXECUTOR


def slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s)).strip("_")[:40]


def flux_id_for(name: str) -> str:
    s = slug(name)
    return PREFIX + s[len(PREFIX):] if s.startswith(PREFIX) else PREFIX + s


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "oui", "yes", "x")


def _values(v) -> list[str]:
    if isinstance(v, (list, tuple)):
        items = v
    else:
        items = str(v or "").replace(";", ",").split(",")
    return list(dict.fromkeys(str(x).strip() for x in items if str(x).strip()))


def normalize(d: dict) -> dict:
    """Brouillon nettoyé (lignes vides du tableur ignorées, types et bornes ramenés à des valeurs connues)."""
    params = []
    for p in d.get("parametres") or []:
        nom = str((p or {}).get("nom") or "").strip().lower()
        if not nom:
            continue
        t = str(p.get("type") or "string").strip().lower()
        params.append({"nom": nom, "type": t, "obligatoire": _bool(p.get("obligatoire", False)),
                       "description": str(p.get("description") or "").strip(),
                       "valeurs": _values(p.get("valeurs")) if t == "enum" else []})
    fixes = d.get("valeurs_fixes") or {}
    if isinstance(fixes, list):   # lignes du tableur {nom, valeur}
        fixes = {str((r or {}).get("nom") or "").strip().lower(): (r or {}).get("valeur") for r in fixes}
    fixes = {str(k).strip().lower(): v for k, v in fixes.items() if str(k).strip()}
    try:
        delai = int(d.get("delai_minutes") or 60)
    except (TypeError, ValueError):
        delai = 60
    name = str(d.get("name") or "").strip()
    return {"tool_id": str(d.get("tool_id") or "").strip() or flux_id_for(name), "name": name,
            "description": str(d.get("description") or "").strip(),
            "type": str(d.get("type") or "lecture").strip().lower(), "parametres": params, "valeurs_fixes": fixes,
            "reponse": str(d.get("reponse") or "").strip(), "delai_minutes": max(1, min(delai, 1440))}


def check(d: dict, existing: dict | None = None, owner: str = "") -> list[str]:
    """Erreurs bloquantes. existing : {tool_id: propriétaire} des outils en base (« __integre__ » pour un intégré)."""
    d = normalize(d)
    errs = []
    if not d["name"]:
        errs.append("Nom du flux manquant.")
    if not FLUX_ID.match(d["tool_id"]):
        errs.append(f"Identifiant invalide « {d['tool_id']} » : flux_ suivi de 2 à 40 caractères a-z, 0-9, _.")
    owner_of = (existing or {}).get(d["tool_id"])
    if owner_of is not None and owner_of != owner:
        errs.append(f"L'identifiant « {d['tool_id']} » est déjà pris par un autre outil ou flux.")
    if len(d["description"]) < 20:
        errs.append("Description pour le modèle trop courte (20 caractères au moins) : dire ce que fait le flux "
                    "et quand l'utiliser.")
    if d["type"] not in KINDS:
        errs.append(f"Type inconnu « {d['type']} » : lecture ou action.")
    seen = set()
    for p in d["parametres"]:
        if not PARAM.match(p["nom"]):
            errs.append(f"Nom de paramètre invalide « {p['nom']} » : minuscules, chiffres et _, sans espace ni accent.")
        if p["nom"] in seen:
            errs.append(f"Paramètre en double : {p['nom']}.")
        seen.add(p["nom"])
        if p["type"] not in TYPES:
            errs.append(f"Type inconnu pour {p['nom']} : {p['type']}.")
        if p["type"] == "enum" and not p["valeurs"]:
            errs.append(f"Liste de valeurs vide pour {p['nom']}.")
        if not p["description"]:
            errs.append(f"Description manquante pour le paramètre {p['nom']} (le modèle en a besoin).")
    for k, v in d["valeurs_fixes"].items():
        if not PARAM.match(k):
            errs.append(f"Nom de valeur fixe invalide « {k} ».")
        if k in seen:
            errs.append(f"« {k} » est à la fois un paramètre et une valeur fixe : choisir l'un ou l'autre.")
        if v is None or str(v).strip() == "":
            errs.append(f"Valeur fixe vide pour {k}.")
    return errs


def input_schema(d: dict) -> dict:
    """Schéma vu par le modèle : paramètres non fixés seulement."""
    d = normalize(d)
    props, req = {}, []
    for p in d["parametres"]:
        if p["nom"] in d["valeurs_fixes"]:
            continue
        if p["type"] == "date":
            prop = {"type": "string", "format": "date", "description": (p["description"] + " (AAAA-MM-JJ)").strip()}
        elif p["type"] == "enum":
            prop = {"type": "string", "enum": p["valeurs"], "description": p["description"]}
        else:
            prop = {"type": p["type"], "description": p["description"]}
        props[p["nom"]] = prop
        if p["obligatoire"]:
            req.append(p["nom"])
    return {"type": "object", "properties": props, "required": req}


def build_spec(d: dict, owner: str, status: str = "brouillon", version: str = "1") -> ToolSpec:
    d = normalize(d)
    action = d["type"] == "action"
    desc = d["description"] + SUFFIX + (f" Réponse attendue : {d['reponse']}" if d["reponse"] else "")
    cfg = {"mode": "boite", "type": d["type"], "description": d["description"], "parametres": d["parametres"],
           "valeurs_fixes": d["valeurs_fixes"], "reponse": d["reponse"], "delai_minutes": d["delai_minutes"]}
    return ToolSpec(tool_id=d["tool_id"], name=d["name"], category=CATEGORY, description=desc,
                    input_schema=input_schema(d), output_schema={"type": "object"}, executor=EXECUTOR,
                    identity="utilisateur", requires_confirmation=action, read_only=not action, status=status,
                    version=str(version), config=cfg, owner=owner)


def draft_from_spec(spec: ToolSpec) -> dict:
    c = spec.config or {}
    return {"tool_id": spec.tool_id, "name": spec.name, "description": c.get("description", ""),
            "type": c.get("type", "lecture"), "parametres": list(c.get("parametres") or []),
            "valeurs_fixes": dict(c.get("valeurs_fixes") or {}), "reponse": c.get("reponse", ""),
            "delai_minutes": c.get("delai_minutes", 60)}


def json_schema(spec: ToolSpec) -> dict:
    """Schéma du JSON `parametres` d'une demande, à coller dans l'action Power Automate « Analyser JSON »."""
    c = spec.config or {}
    kinds = {"date": "string", "enum": "string"}
    props = {p["nom"]: {"type": kinds.get(p["type"], p["type"])} for p in c.get("parametres") or []}
    for k, v in (c.get("valeurs_fixes") or {}).items():
        props.setdefault(k, {"type": "number" if isinstance(v, (int, float)) and not isinstance(v, bool) else
                             "boolean" if isinstance(v, bool) else "string"})
    req = [p["nom"] for p in c.get("parametres") or [] if p.get("obligatoire")] + list(c.get("valeurs_fixes") or {})
    return {"type": "object", "properties": props, "required": req}


def pa_queries(spec: ToolSpec, table: str) -> dict:
    """Requêtes SQL à configurer dans le flux (connecteur Azure Databricks). <...> = contenu dynamique Power Automate.

    L'identifiant du flux est validé (FLUX_ID) : il peut être écrit en clair dans la requête.
    """
    if not FLUX_ID.match(spec.tool_id):
        raise ValueError(f"Identifiant de flux invalide : {spec.tool_id}")
    f = spec.tool_id
    return {
        "1. Lire les demandes en attente":
            f"SELECT demande_id, parametres, test, user_name, created_at\nFROM {table}\n"
            f"WHERE flux_id = '{f}' AND statut = 'en_attente'\nORDER BY created_at\nLIMIT 10",
        "2. Prendre en charge une demande":
            f"UPDATE {table}\nSET statut = 'en_cours', pris_en_charge_at = current_timestamp()\n"
            f"WHERE demande_id = '<demande_id>' AND flux_id = '{f}' AND statut = 'en_attente'",
        "3. Écrire la réponse":
            f"UPDATE {table}\nSET statut = 'terminee', reponse = '<reponse_json>', termine_at = current_timestamp()\n"
            f"WHERE demande_id = '<demande_id>' AND flux_id = '{f}' AND statut = 'en_cours'",
        "4. Signaler une erreur":
            f"UPDATE {table}\nSET statut = 'erreur', erreur = '<message_erreur>', termine_at = current_timestamp()\n"
            f"WHERE demande_id = '<demande_id>' AND flux_id = '{f}' AND statut IN ('en_attente', 'en_cours')",
    }


def parse_json(v):
    if not isinstance(v, str):
        return v
    try:
        return json.loads(v)
    except (TypeError, json.JSONDecodeError):
        return v
