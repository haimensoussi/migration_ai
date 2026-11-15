"""HakimAI, l'architecte de la plateforme DISCOVERY — lot 1 : guider, expliquer, diagnostiquer (lecture seule).

HakimAI n'est pas enregistré dans le catalogue des agents : ses outils lui sont propres et ne sont pas proposés
aux autres agents. Il agit avec les droits de l'utilisateur ; aucun de ses outils du lot 1 n'écrit.
"""
from __future__ import annotations

import os

from backend.agent_runtime import AgentConfig
from backend.tool_registry import ToolSpec
from tools.hakim_tools import GUIDE, PAGES, TOURS

AGENT_ID = "hakimai"
NAME = "HakimAI"
PERSONA = "l'architecte de la plateforme"


def enabled() -> bool:
    return os.environ.get("AI_STUDIO_HAKIM_ENABLED", "true").strip().lower() not in ("0", "false", "non", "off")


def max_turns() -> int:
    try:
        return max(1, int(os.environ.get("AI_STUDIO_HAKIM_MAX_TURNS", "30")))
    except ValueError:
        return 30


def _s(desc, **kw):
    return {"type": "string", "description": desc, **kw}


_AGENT = _s("Nom, @nom d'appel ou identifiant de l'agent")
_OBJ = {"type": "object"}


def _spec(tool_id, name, description, props=None, required=None):
    return ToolSpec(tool_id=tool_id, name=name, category="HakimAI", description=description,
                    input_schema={"type": "object", "properties": props or {}, "required": required or []},
                    output_schema=_OBJ, executor=f"tools.hakim_tools:{tool_id}", read_only=True)


TOOLS: list[ToolSpec] = [
    _spec("contexte_page", "Contexte de la page", "Page où se trouve l'utilisateur, objet affiché (agent, équipe...), "
          "identité et rôle administrateur. À appeler quand la question dépend de « ici », « cet agent », « cette page »."),
    _spec("ouvrir_page", "Ouvrir une page", "Propose à l'utilisateur un bouton pour aller sur une page de la plateforme.",
          {"page": _s("Page cible", enum=list(PAGES)), "raison": _s("Pourquoi cette page (une phrase)")}, ["page"]),
    _spec("aide_plateforme", "Aide sur la plateforme", "Explication de référence d'un concept de la plateforme.",
          {"sujet": _s("Sujet", enum=list(GUIDE))}, ["sujet"]),
    _spec("visite_guidee", "Visite guidée", "Parcours de pages recommandé selon le profil de l'utilisateur.",
          {"profil": _s("Profil", enum=list(TOURS))}),
    _spec("lister_agents", "Lister les agents", "Agents visibles par l'utilisateur (publiés, les siens ; tous pour un administrateur).",
          {"recherche": _s("Mot recherché (nom, rôle, catégorie)"), "statut": _s("Filtre", enum=["brouillon", "publie"])}),
    _spec("decrire_agent", "Décrire un agent", "Fiche d'un agent : identité, version, modèle, outils, tables, équipes, instructions.",
          {"agent": _AGENT}, ["agent"]),
    _spec("comparer_versions", "Comparer deux versions", "Différences entre deux versions d'un agent (outils, tables, modèle, "
          "instructions). Par défaut : version courante et précédente.",
          {"agent": _AGENT, "version_a": {"type": "integer", "minimum": 0}, "version_b": {"type": "integer", "minimum": 0}},
          ["agent"]),
    _spec("lister_outils", "Lister les outils", "Catalogue des outils : statut, lecture seule, confirmation, intégré ou créé.",
          {"recherche": _s("Mot recherché"), "statut": _s("Filtre", enum=["brouillon", "publie", "planifie", "indisponible"])}),
    _spec("lister_equipes", "Lister les équipes", "Équipes visibles : mission, chef, membres, responsable humain."),
    _spec("activite", "Activité", "Conversations, appels d'outils et taux de succès par agent sur une période.",
          {"agent": _AGENT, "jours": {"type": "integer", "minimum": 1, "maximum": 90}}),
    _spec("diagnostiquer_echec", "Diagnostiquer les échecs", "Échecs récents regroupés par agent, outil et message. Les "
          "détails ne sont montrés que pour les appels de l'utilisateur ou ses agents.",
          {"agent": _AGENT, "outil": _s("Identifiant d'outil"), "jours": {"type": "integer", "minimum": 1, "maximum": 30}}),
    _spec("explorer_donnees", "Explorer les données", "Lister les tables d'un schéma, décrire, profiler ou prévisualiser "
          "une table, avec les droits Unity Catalog de l'utilisateur.",
          {"action": _s("Action", enum=["lister_tables", "decrire", "profiler", "apercu"]),
           "table": _s("Nom complet catalog.schema.table"), "catalog": _s("Catalogue"), "schema": _s("Schéma"),
           "limite": {"type": "integer", "minimum": 1, "maximum": 50}}, ["action"]),
]

INSTRUCTIONS = f"""Tu es {NAME}, {PERSONA} DISCOVERY (SNCF Réseau). Tu guides les utilisateurs dans la plateforme :
agents IA, outils, équipes d'agents, chat et @mentions, catalogue d'outils, monitoring.

Ce que tu fais :
- Expliquer la plateforme et ses concepts (utilise aide_plateforme pour les définitions de référence).
- Répondre aux questions sur les agents, outils et équipes à partir des outils de lecture ; jamais de mémoire.
- Diagnostiquer : erreurs d'outils, agents peu utilisés, différences entre versions.
- Orienter : proposer la bonne page avec ouvrir_page, ou une visite guidée.
- Explorer les données avec les droits de l'utilisateur quand il le demande.

Règles :
- Si la question dépend de la page (« ici », « cet agent »), appelle d'abord contexte_page.
- Tu ne crées, ne modifies, ne publies et n'exécutes rien dans cette version : explique comment faire et ouvre la page.
- Un refus d'accès est normal : signale-le tel quel, sans le contourner.
- N'invente aucun agent, outil, chiffre ou résultat. Dis quand une information n'est pas disponible.
- Pour décrire ce qu'on peut faire sur une page, ne cite que les actions_disponibles renvoyées par contexte_page :
  n'ajoute aucune fonctionnalité (pas de « supprimer » si seule l'archive existe).
- Les chiffres doivent venir des outils et rester cohérents : un total est la somme exacte des groupes affichés.
- Ne rattache des résultats à une équipe ou un agent que si l'outil a été appelé avec ce filtre.
- Une colonne proposée par un message d'erreur est une suggestion de la plateforme, pas une correction certaine.
- Pas d'emoji ni de titres décoratifs.
- Réponds en français, de façon concise et concrète : étapes numérotées pour un « comment faire », tableau court pour une liste.
- Désigne les agents par leur prénom et leur nom d'appel (ex. Margot, @margot).
"""


def config(model_endpoint: str) -> AgentConfig:
    return AgentConfig(agent_id=AGENT_ID, version=1, name=NAME, model_endpoint=model_endpoint,
                       instructions=INSTRUCTIONS, tool_ids=[t.tool_id for t in TOOLS], temperature=0.1,
                       max_iterations=8)


def navigation_targets(events) -> list[dict]:
    """Boutons de navigation proposés par ouvrir_page pendant un tour (succès uniquement, sans doublon)."""
    seen, out = set(), []
    for ev in events:
        r = ev.result if isinstance(ev.result, dict) else {}
        if ev.tool_id == "ouvrir_page" and ev.status == "succes" and r.get("navigation") and r["navigation"] not in seen:
            seen.add(r["navigation"])
            out.append({"path": r["navigation"], "title": r.get("titre", ""), "reason": r.get("raison", "")})
    return out
