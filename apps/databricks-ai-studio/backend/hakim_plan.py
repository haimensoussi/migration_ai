"""Plan de travail HakimAI : HakimAI affiche ses étapes (« Étape N — Titre ») puis les exécute aussitôt.

- Le plan est enregistré par l'outil hakim_plan_travail, sans fiche de validation : il sert d'annonce et de trace.
- Les écritures de transformation (GATED) exigent un plan en cours qui les annonce ; chaque étape d'écriture
  annoncée autorise un seul appel réussi. Un plan terminé ou remplacé n'autorise plus rien.
- L'état de chaque étape (à faire, en cours, fait) est déduit des outils réellement appelés, pas du modèle.
- Logique pure (sans base ni Streamlit) : testée dans tests/test_hakim_plan.py.
"""
from __future__ import annotations

import uuid

PLAN_TOOL = "hakim_plan_travail"
GATED = ("transformation_creer_plan", "transformation_cadrage", "transformation_decouvrir",
         "transformation_proposer", "transformation_feuille_route", "transformation_relier")
NATURES = {"lecture": "lecture", "ecriture": "écriture tracée", "aucune": "aucune écriture"}
NO_TOOL = "aucun"
MAX_STEPS = 8
MAX_TITLE = 60
STATES = {"a_faire": "à faire", "en_cours": "en cours", "fait": "fait"}


class PlanError(Exception):
    """Écriture hors plan annoncé : message renvoyé au modèle."""


def _txt(v, n: int) -> str:
    return str(v or "").strip()[:n]


def issue(args: dict, known_tools: set[str]) -> str | None:
    """Problème de forme du plan, détecté avant l'appel (sinon None)."""
    a = args or {}
    steps = a.get("etapes")
    if not isinstance(steps, list) or not steps:
        return "Plan incomplet : au moins une étape dans « etapes »."
    if len(steps) > MAX_STEPS:
        return f"Plan trop long : {MAX_STEPS} étapes au plus ; découpe le travail en plusieurs plans."
    for n, s in enumerate(steps, 1):
        s = s if isinstance(s, dict) else {}
        tool, nature = _txt(s.get("outil"), 80) or NO_TOOL, s.get("nature")
        title = str(s.get("titre") or "").strip()
        if not title:
            return f"Étape {n} : donne un titre court (ex. « Contrôle de l'archive »)."
        if len(title) > MAX_TITLE:
            return f"Étape {n} : titre trop long ({len(title)} caractères, {MAX_TITLE} au plus)."
        if nature not in NATURES:
            return f"Étape {n} : nature attendue parmi {', '.join(NATURES)}."
        if tool != NO_TOOL and tool not in known_tools:
            return f"Étape {n} : outil « {tool} » inconnu (identifiant exact ou « aucun »)."
        if tool == PLAN_TOOL:
            return f"Étape {n} : un plan ne peut pas annoncer {PLAN_TOOL}."
        if tool in GATED and nature != "ecriture":
            return f"Étape {n} : {tool} écrit dans le plan de transformation ; nature « ecriture »."
        if nature == "ecriture" and tool == NO_TOOL:
            return f"Étape {n} : une écriture cite l'outil qui l'effectue."
    return None


def normalize(args: dict) -> dict:
    a = args or {}
    steps = [{"titre": _txt(s.get("titre"), MAX_TITLE), "outil": _txt(s.get("outil"), 80) or NO_TOOL,
              "nature": s.get("nature")} for s in a.get("etapes") or [] if isinstance(s, dict)]
    return {"plan": _txt(a.get("plan"), 40) or None, "etapes": steps}


def describe(args: dict) -> list[str]:
    """Libellés « Étape N — Titre », sans outil ni nature (affichage et journal)."""
    return [f"Étape {n} — {s['titre']}" for n, s in enumerate(normalize(args)["etapes"], 1)]


def progress(steps: list[dict], called: list[str]) -> list[str]:
    """État de chaque étape d'après les outils réussis, dans l'ordre : une étape avec outil est faite quand son outil
    a été appelé après l'étape précédente ; une étape sans outil (présentation) est faite dès qu'elle est atteinte
    (fin du message ou étape suivante) ; la première étape non faite est « en cours », les suivantes « à faire »."""
    out, cur, blocked = [], 0, False
    for s in steps:
        if blocked:
            out.append("a_faire")
        elif s.get("outil", NO_TOOL) == NO_TOOL:
            out.append("fait")
        elif s["outil"] in called[cur:]:
            cur = called.index(s["outil"], cur) + 1
            out.append("fait")
        else:
            blocked = True
            out.append("en_cours")
    return out


def lines(store: dict | None) -> list[dict]:
    """Lignes affichées sous le message : libellé et état de chaque étape du plan courant."""
    st = store or {}
    steps = st.get("etapes") or []
    states = progress(steps, st.get("appels") or [])
    return [{"libelle": f"Étape {n} — {s['titre']}", "etat": e} for n, (s, e) in enumerate(zip(steps, states), 1)]


def record(store: dict | None, events: list[tuple[str, str]]) -> None:
    """Ajoute au plan courant les outils réussis du tour, dans l'ordre, après le dernier appel du plan."""
    if not store or not store.get("etapes"):
        return
    ids = [tid for tid, status in events]
    start = len(ids) - ids[::-1].index(PLAN_TOOL) if PLAN_TOOL in ids else 0
    store.setdefault("appels", []).extend(tid for tid, status in events[start:]
                                          if status == "succes" and tid != PLAN_TOOL)


def approve(store: dict, args: dict, now: str = "") -> dict:
    """Enregistre le plan dans la session (remplace le précédent)."""
    p = normalize(args)
    remaining: dict[str, int] = {}
    for s in p["etapes"]:
        if s["nature"] == "ecriture":
            remaining[s["outil"]] = remaining.get(s["outil"], 0) + 1
    store.clear()
    store.update({"plan_travail_id": "pt_" + uuid.uuid4().hex[:12], "statut": "valide", "valide_le": now,
                  "plan": p["plan"], "etapes": p["etapes"], "restant": remaining, "faits": [], "appels": []})
    if not remaining:
        store["statut"] = "termine"
    return dict(store)


def check(store: dict | None, tool_id: str, plan_arg: str | None) -> None:
    """Lève PlanError si l'écriture n'est pas annoncée par un plan encore ouvert."""
    if tool_id not in GATED:
        return
    st = store or {}
    if st.get("statut") != "valide":
        raise PlanError(f"Aucun plan de travail en cours n'annonce {tool_id} : appelle d'abord {PLAN_TOOL} (étapes "
                        "avec titre court, outil et nature), puis exécute-les.")
    if st.get("restant", {}).get(tool_id, 0) <= 0:
        raise PlanError(f"{tool_id} n'est pas (ou plus) annoncé dans le plan en cours {st.get('plan_travail_id')} : "
                        f"propose un nouveau plan avec {PLAN_TOOL}.")
    if st.get("plan") and plan_arg and plan_arg != st["plan"]:
        raise PlanError(f"Le plan en cours porte sur {st['plan']}, pas sur {plan_arg} : propose un nouveau plan.")


def consume(store: dict | None, tool_id: str) -> None:
    """Après une écriture réussie : décompte l'étape ; le plan se termine quand tout est fait."""
    if tool_id not in GATED or not store or store.get("statut") != "valide":
        return
    left = store["restant"]
    left[tool_id] = max(0, left.get(tool_id, 0) - 1)
    store["faits"].append(tool_id)
    if not any(left.values()):
        store["statut"] = "termine"
