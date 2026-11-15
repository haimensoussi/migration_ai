"""Identité « humaine » des agents : prénom, nom d'appel @, rôle, accroche, exemples, anciens noms.

Le prénom ne change ni les droits ni les outils : la mention « Agent IA » reste affichée partout.
"""
from __future__ import annotations

import json
import re

from backend.mentions import norm, slug

HANDLE = re.compile(r"^[a-z][a-z0-9_-]{1,19}$")
RESERVED = {"tous", "tout", "all", "admin", "admins", "agent", "agents", "discovery", "moi", "aide", "help",
            "system", "systeme", "everyone", "here", "ici", "equipe", "support"}
MAX_PERSONA, MAX_TAGLINE, MAX_EXAMPLE, MAX_EXAMPLES, MAX_ALIASES = 40, 90, 100, 3, 5
AI_BADGE = "Agent IA"


def _list(v) -> list[str]:
    if isinstance(v, str):
        try:
            v = json.loads(v) if v.strip().startswith("[") else [x for x in v.splitlines()]
        except ValueError:
            v = v.splitlines()
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def suggest_handle(name: str) -> str:
    """Nom d'appel dérivé du prénom : premier mot, minuscules sans accent."""
    first = slug(name or "").split("-")[0]
    return first[:20]


def normalize(p: dict) -> dict:
    """Champs d'identité homogènes (sans validation)."""
    handle = norm(str(p.get("handle") or "").strip().lstrip("@")).replace(" ", "-")
    return {"handle": handle or suggest_handle(p.get("name") or ""),
            "persona": str(p.get("persona") or "").strip()[:MAX_PERSONA],
            "tagline": re.sub(r"\s+", " ", str(p.get("tagline") or "")).strip(),
            "call_examples": _list(p.get("call_examples"))[:MAX_EXAMPLES],
            "aliases": _list(p.get("aliases"))[:MAX_ALIASES]}


def taken_keys(agents: list[dict], except_id: str | None = None) -> dict[str, str]:
    """Clés déjà utilisées après @ (nom d'appel, nom, anciens noms) -> nom de l'agent qui les porte."""
    out = {}
    for a in agents:
        if a.get("agent_id") == except_id:
            continue
        for k in [a.get("handle")] + [a.get("name")] + _list(a.get("aliases")):
            if k:
                out.setdefault(slug(k), a.get("name") or "?")
    return out


def validate(p: dict, agents: list[dict], agent_id: str | None = None) -> list[str]:
    errs, h = [], p.get("handle") or ""
    if not HANDLE.match(h):
        errs.append("Nom d'appel invalide : 2 à 20 caractères, minuscules sans accent, chiffres, - ou _, "
                    "commençant par une lettre.")
    elif h in RESERVED:
        errs.append(f"Nom d'appel réservé : @{h}.")
    taken = taken_keys(agents, agent_id)
    if h and slug(h) in taken:
        errs.append(f"@{h} est déjà utilisé par « {taken[slug(h)]} ».")
    for al in p.get("aliases") or []:
        if slug(al) in taken:
            errs.append(f"Ancien nom « {al} » déjà utilisé par « {taken[slug(al)]} ».")
    if len(p.get("tagline") or "") > MAX_TAGLINE:
        errs.append(f"Accroche trop longue : {MAX_TAGLINE} caractères au plus.")
    if any(len(x) > MAX_EXAMPLE for x in p.get("call_examples") or []):
        errs.append(f"Exemple trop long : {MAX_EXAMPLE} caractères au plus.")
    return errs


def display(a: dict) -> str:
    """« Margot, la cartographe » (ou le nom seul)."""
    name, role = (a.get("name") or "").strip(), (a.get("persona") or "").strip()
    return f"{name}, {role}" if name and role else name


def mention(a: dict) -> str:
    """Texte inséré après @ : le nom d'appel s'il existe, sinon le nom."""
    return a.get("handle") or a.get("name") or ""


def to_row(p: dict) -> dict:
    return {"handle": p.get("handle") or None, "persona": p.get("persona") or None,
            "tagline": p.get("tagline") or None,
            "call_examples": json.dumps(p.get("call_examples") or [], ensure_ascii=False),
            "aliases": json.dumps(p.get("aliases") or [], ensure_ascii=False)}
