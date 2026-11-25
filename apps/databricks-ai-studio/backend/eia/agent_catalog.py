"""EIA Factory - étape 2 : Catalogue d'Agents (fiches, capacités, paramètres, modèles d'équipe).

Toutes les informations sont dérivées du Framework (agent_models) : le catalogue ne peut pas diverger du code.
Lecture seule ; utilisé par la page Catalogue d'agents, HAKIM (eia_catalogue_agents) et le Team Builder.
"""
from __future__ import annotations

from backend.eia import agent_models as am

# Modèles d'équipe (templates) proposés par le Team Builder.
TEMPLATES: dict[str, dict] = {
    "equipe_metier": {
        "nom": "Équipe EIA métier", "modeles": list(am.BUSINESS_TEAM),
        "description": "Boucle complète CAPTER -> APPRENDRE : KPI, alertes, recommandations, missions, affectations "
                       "proposées, suivi et bilan. Référence : équipe Sales.",
        "prerequis": ["KPI lisibles dans la zone de données", "Règles d'alerte et seuils (à valider)",
                      "Plans d'action types détaillés en tâches (à valider)", "Référentiel de compétences"]},
    "equipe_surveillance": {
        "nom": "Équipe de surveillance des données et KPI", "modeles": ["AG01", "AG08"],
        "description": "CAPTER, COMPRENDRE et PRÉDIRE avec contrôle et traçabilité ; sans recommandation tant que les "
                       "règles et plans d'action ne sont pas définis par le métier. Première étape de toute nouvelle équipe.",
        "prerequis": ["KPI lisibles dans la zone de données"]},
    "eia_factory": {
        "nom": "EIA Factory (Team Builder)", "modeles": list(am.FACTORY_TEAM),
        "description": "Méta-équipe qui conçoit des équipes : découverte de la source (AG01), proposition "
                       "d'architecture (AG10), déploiement (AG09), contrôles de passage (AG08).",
        "prerequis": ["Périmètre de données Unity Catalog lisible par l'utilisateur"]},
}


def _templates_using(code: str) -> list[str]:
    return [tid for tid, t in TEMPLATES.items() if code in t["modeles"]]


def card(code: str) -> dict:
    """Fiche d'une catégorie : description officielle, modèle, capacités, paramètres, interfaces, état."""
    meta = am.CATEGORIES.get(code)
    if not meta:
        raise KeyError(f"Catégorie inconnue : {code}")
    out = {"code": code, "nom": meta["nom"], "fonctions_officielles": meta["fonctions"], "statut": meta["statut"],
           "modeles_equipe": _templates_using(code)}
    if meta.get("fusionne_dans"):
        return {**out, "fusionne_dans": meta["fusionne_dans"], "modele": None}
    m = am.MODELS[code]
    d = m.describe()
    producers = {i: [x.code for x in am.MODELS.values() if i in x.outputs] for i in (*m.inputs, *m.optional_inputs)}
    consumers = {o: [x.code for x in am.MODELS.values() if o in (*x.inputs, *x.optional_inputs)] for o in m.outputs}
    return {**out, "modele": d, "capacites": list(m.functions), "operationnel": m.status != "squelette",
            "recoit_de": producers, "transmet_a": consumers,
            "interfaces": {i: am.INTERFACES[i] for i in (*m.inputs, *m.optional_inputs, *m.outputs)}}


def cards(statut: str | None = None) -> list[dict]:
    return [card(c) for c in am.CATEGORIES if statut is None or am.CATEGORIES[c]["statut"] == statut]


def template(template_id: str) -> dict:
    t = TEMPLATES.get(template_id)
    if not t:
        raise KeyError(f"Modèle d'équipe inconnu : {template_id}")
    strict = am.check_composition(t["modeles"])
    design = am.check_composition(t["modeles"], allow_skeleton=True)
    pending = [c for c in t["modeles"] if am.MODELS[c].status != "disponible"]
    state = "operationnel" if not strict else ("en_attente_de_modeles" if not design else "incoherent")
    return {"id": template_id, **t, "etat": state, "problemes": strict,
            "modeles_a_completer": [{"code": c, "statut": am.MODELS[c].status, "reste_a_faire": am.MODELS[c].missing}
                                    for c in pending]}


def templates() -> list[dict]:
    return [template(t) for t in TEMPLATES]


def summary() -> dict:
    status = {}
    for meta in am.CATEGORIES.values():
        status[meta["statut"]] = status.get(meta["statut"], 0) + 1
    return {"categories": len(am.CATEGORIES), "modeles": len(am.MODELS), "par_statut": status,
            "modeles_equipe": {t["id"]: t["etat"] for t in templates()},
            "garde_fous_communs": list(am.GUARDRAILS)}
