"""Icônes DISCOVERY et métadonnées de présentation des réponses (sans dépendance Streamlit).

Les icônes métier sont choisies par l'interface à partir de métadonnées structurées (outils appelés,
statuts, catégorie de l'agent), jamais à partir du texte produit par le modèle.
"""
from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICON_DIR = ASSETS / "icons"
MAX_CHIPS = 3

AVATAR_ASSISTANT = str(ICON_DIR / "discovery_train.svg")
AVATAR_USER = str(ICON_DIR / "user.svg")
AVATAR_TOOL = str(ICON_DIR / "tool.svg")

PRESENTATION_GUIDELINE = """
## Présentation des réponses (consigne générale DISCOVERY)
Tu es un assistant professionnel intégré à DISCOVERY, une plateforme IA destinée aux métiers de SNCF Réseau.
Réponds de manière claire, précise et structurée.
Utilise des paragraphes courts et des titres simples.
Évite les emojis décoratifs, les pictogrammes multicolores et les répétitions.
Ne surcharge pas les réponses avec des listes inutilement longues.
Conserve les informations techniques importantes, notamment les résultats SQL, les erreurs et les recommandations.
L'interface DISCOVERY se charge de l'affichage des icônes métier.
""".strip()

# Outils -> (icône, libellé) ; l'ordre de la liste fixe la priorité d'affichage
TOOL_CHIPS = [
    ({"ask_agent"}, "play", "Orchestration multi-agents"),
    ({"list_tables", "describe_table"}, "database", "Exploration des données"),
    ({"execute_sql", "get_table_profile", "generate_sql"}, "chart", "Analyse des données"),
    ({"run_job", "get_job_status"}, "clock", "Suivi des Jobs"),
    ({"search_documents", "office_read", "office_send"}, "document", "Documentation"),
]

CAPABILITIES = [
    ({"list_tables", "describe_table"}, "database", "Explorer les catalogues, schémas et tables Unity Catalog."),
    ({"execute_sql"}, "code", "Générer et exécuter des requêtes SQL autorisées."),
    ({"get_table_profile", "execute_sql"}, "chart", "Analyser les résultats et identifier les anomalies."),
    ({"get_job_status", "run_job"}, "clock", "Suivre l'état des Jobs Databricks."),
    ({"office_read", "office_send", "search_documents"}, "document", "Rechercher et préparer des documents et messages."),
]


@lru_cache(maxsize=None)
def icon_uri(name: str) -> str:
    data = (ICON_DIR / f"{name}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


def icon_img(name: str, label: str = "") -> str:
    return (f'<img class="discovery-inline-icon" src="{icon_uri(name)}" alt="" '
            f'aria-hidden="true">' + (html.escape(label) if label else ""))


def chips_for(events: list[dict], category: str | None = None, error: bool = False) -> list[tuple[str, str]]:
    """Choisit au plus MAX_CHIPS icônes métier pour une réponse, sans doublon."""
    used = {e.get("tool_id") for e in events}
    failed = error or any(e.get("status") in ("erreur", "refuse") for e in events)
    out: list[tuple[str, str]] = []
    if failed:
        out.append(("alert", "Incident d'exécution"))
    if category == "Qualité des données":
        out.append(("shield", "Qualité des données"))
    for tools, ico, label in TOOL_CHIPS:
        if used & tools:
            out.append((ico, label))
    if events and not failed:
        out.append(("success", "Outils exécutés avec succès"))
    seen, uniq = set(), []
    for ico, label in out:
        if ico not in seen:
            seen.add(ico)
            uniq.append((ico, label))
    return uniq[:MAX_CHIPS]


def chips_html(chips: list[tuple[str, str]]) -> str:
    if not chips:
        return ""
    return '<div class="dsc-chips">' + "".join(
        f'<span class="dsc-chip">{icon_img(i)}{html.escape(l)}</span>' for i, l in chips) + "</div>"


def capabilities_for(tool_ids: list[str]) -> list[tuple[str, str]]:
    ids = set(tool_ids or [])
    return [(ico, txt) for tools, ico, txt in CAPABILITIES if ids & tools][:3]


def with_presentation(instructions: str) -> str:
    """Ajoute la consigne générale après les instructions propres à l'agent (sans les remplacer)."""
    base = (instructions or "").rstrip()
    if PRESENTATION_GUIDELINE in base:
        return base
    return f"{base}\n\n{PRESENTATION_GUIDELINE}" if base else PRESENTATION_GUIDELINE
