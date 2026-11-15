"""Règles des équipes d'agents (sans dépendance Streamlit ni SQL).

Une équipe : nom, nom d'appel @, mission, filière, responsable humain, membres, chef (agent coordinateur).
- @équipe envoie la question au chef (ou au membre unique) ;
- un seul niveau de délégation : le chef n'est membre d'aucune équipe et ne dirige qu'une équipe ;
  un membre n'est pas lui-même coordinateur ;
- publication réservée aux administrateurs des équipes.
"""
from __future__ import annotations

import re

from backend import personas
from backend.mentions import norm, slug

FILIERES = ["Transverse", "Supply Chain", "PTE", "UDR"]
ICONS = ["groups", "verified", "map", "query_stats", "inventory_2", "train", "engineering", "mail"]
STATUSES = ("brouillon", "publie", "archive")
MAX_NAME, MAX_MISSION, MAX_MEMBERS = 60, 140, 8
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
AGENT_PREFIX = "agent:"


def is_coordinator(agent: dict) -> bool:
    return any(str(t).startswith(AGENT_PREFIX) for t in agent.get("tool_ids") or [])


def normalize(t: dict) -> dict:
    members = list(dict.fromkeys(str(m) for m in (t.get("members") or []) if m))
    lead = str(t.get("lead_agent_id") or "") or None
    handle = norm(str(t.get("handle") or "").strip().lstrip("@")).replace(" ", "-")
    return {"team_id": t.get("team_id"), "name": re.sub(r"\s+", " ", str(t.get("name") or "")).strip(),
            "handle": handle or personas.suggest_handle(re.sub(r"(?i)^(équipe|equipe)\s+", "", str(t.get("name") or ""))),
            "mission": re.sub(r"\s+", " ", str(t.get("mission") or "")).strip(),
            "filiere": t.get("filiere") if t.get("filiere") in FILIERES else "Transverse",
            "icon": t.get("icon") if t.get("icon") in ICONS else "groups",
            "human_owner": str(t.get("human_owner") or "").strip().lower(),
            "members": [m for m in members if m != lead],
            "primary": [m for m in (t.get("primary") or members) if m in members and m != lead],
            "lead_agent_id": lead, "status": t.get("status") if t.get("status") in STATUSES else "brouillon"}


def validate(t: dict, agents: list[dict], teams: list[dict]) -> list[str]:
    errs, tid = [], t.get("team_id")
    by_id = {a["agent_id"]: a for a in agents}
    if not t["name"] or len(t["name"]) > MAX_NAME:
        errs.append(f"Nom obligatoire, {MAX_NAME} caractères au plus.")
    h = t["handle"]
    if not personas.HANDLE.match(h):
        errs.append("Nom d'appel invalide : 2 à 20 caractères, minuscules sans accent, chiffres, - ou _.")
    elif h in personas.RESERVED:
        errs.append(f"Nom d'appel réservé : @{h}.")
    else:
        taken = personas.taken_keys(agents)
        if slug(h) in taken:
            errs.append(f"@{h} est déjà le nom d'appel de l'agent « {taken[slug(h)]} ».")
        for o in teams:
            if o.get("team_id") != tid and o.get("status") != "archive" and slug(h) == slug(o.get("handle") or ""):
                errs.append(f"@{h} est déjà utilisé par l'équipe « {o['name']} ».")
    if len(t["mission"]) > MAX_MISSION:
        errs.append(f"Mission trop longue : {MAX_MISSION} caractères au plus.")
    if t["human_owner"] and not EMAIL.match(t["human_owner"]):
        errs.append("Responsable humain : adresse e-mail attendue (ou laisser vide : « à désigner »).")
    if not t["members"]:
        errs.append("Au moins un membre.")
    if len(t["members"]) > MAX_MEMBERS:
        errs.append(f"{MAX_MEMBERS} membres au plus.")
    for m in t["members"]:
        a = by_id.get(m)
        if not a or a.get("status") == "archive":
            errs.append(f"Membre introuvable ou archivé : {m}.")
        elif is_coordinator(a):
            errs.append(f"« {a['name']} » coordonne d'autres agents : il ne peut être que chef d'équipe.")
    others = [o for o in teams if o.get("team_id") != tid and o.get("status") != "archive"]
    lead = t["lead_agent_id"]
    if len(t["members"]) > 1 and not lead:
        errs.append("Une équipe de plusieurs agents a besoin d'un chef d'équipe.")
    if lead:
        a = by_id.get(lead)
        if not a or a.get("status") == "archive":
            errs.append("Chef d'équipe introuvable ou archivé.")
        for o in others:
            if o.get("lead_agent_id") == lead:
                errs.append(f"« {a['name'] if a else lead} » dirige déjà l'équipe « {o['name']} ».")
            if lead in (o.get("members") or []):
                errs.append(f"« {a['name'] if a else lead} » est membre de l'équipe « {o['name']} » : "
                            "un chef ne peut pas être consulté par un autre chef.")
    for m in t["members"]:
        for o in others:
            if o.get("lead_agent_id") == m:
                errs.append(f"« {by_id.get(m, {}).get('name', m)} » dirige l'équipe « {o['name']} » : "
                            "il ne peut pas être membre d'une autre équipe.")
    return list(dict.fromkeys(errs))


def publish_errors(t: dict, agents: list[dict]) -> list[str]:
    by_id = {a["agent_id"]: a for a in agents}
    errs = []
    if not any(by_id.get(m, {}).get("status") == "publie" for m in t["members"]):
        errs.append("Au moins un membre doit être publié.")
    if t["lead_agent_id"] and by_id.get(t["lead_agent_id"], {}).get("status") != "publie":
        errs.append("Le chef d'équipe doit être publié.")
    return errs


def target_agent(t: dict) -> str | None:
    """Agent qui reçoit les questions adressées à @équipe."""
    if t.get("lead_agent_id"):
        return t["lead_agent_id"]
    return (t.get("members") or [None])[0] if len(t.get("members") or []) == 1 else None


def lead_tool_ids(current: list[str], members: list[str]) -> list[str]:
    """Outils du chef : ses outils propres + exactement les membres de son équipe."""
    return [x for x in current if not str(x).startswith(AGENT_PREFIX)] + [AGENT_PREFIX + m for m in members]


def lead_instructions(t: dict, members: list[dict]) -> str:
    lines = "\n".join(f"- « {m['name']} » ({personas.display(m)}) : {m.get('tagline') or m.get('description') or ''}"
                       for m in members)
    return (f"Tu es le chef de l'équipe « {t['name']} » de DISCOVERY (agent IA). Mission de l'équipe : "
            f"{t['mission'] or 'à préciser'}.\n\n## Membres\n{lines}\n\n## Règles\n"
            "- Pour chaque question, consulte le ou les membres concernés avec ask_agent ; découpe les questions mixtes.\n"
            "- N'invente aucun résultat : rapporte ce que les membres ont répondu et cite qui a répondu.\n"
            "- Si aucun membre n'est compétent, dis-le et indique ce qui manque.\n"
            "- Rédige une synthèse unique, courte, en français.")


def mention_entry(t: dict, agents: list[dict]) -> dict | None:
    """Entrée de la liste @ pour une équipe (dirigée vers son chef ou son membre unique)."""
    target = target_agent(t)
    if not target:
        return None
    n = len(t["members"])
    return {"agent_id": target, "name": f"Équipe {t['name']}", "handle": t["handle"], "kind": "team",
            "persona": f"{n} agent{'s' if n > 1 else ''}", "tagline": t["mission"], "category": t["filiere"],
            "aliases": [], "status": t["status"], "owner": t.get("owner")}
