"""Initialisation : catalogue d'outils + agents d'exemple. Idempotent pour les outils (MERGE)."""
from __future__ import annotations

from backend.agent_repository import AgentRepository
from tools.catalog import BUILTIN_TOOLS

DQ_TABLES = [
    "dataops_dev.description_du_reseau_bronze.dq_resultats_controles",
    "dataops_dev.description_du_reseau_bronze.dq_anomalies_detail",
    "dataops_dev.description_du_reseau_bronze.rapport_fraicheur_donnees",
    "dataops_dev.description_du_reseau_bronze.declivite_pentes_et_rampes",
]

EXAMPLE_AGENTS = [
    ({"name": "Data Quality Advisor", "icon": "verified", "category": "Qualité des données",
      "description": "Explique les résultats des contrôles qualité et les anomalies du schéma description_du_reseau_bronze."},
     {"instructions": (
         "Tu es le conseiller Data Quality de SNCF Réseau. Tu appliques le cadre DAMA-DMBOK "
         "(complétude, unicité, validité, cohérence, intégrité référentielle, fraîcheur). "
         "Tu expliques les résultats des contrôles et les anomalies, tu identifies des causes possibles "
         "et tu proposes des règles candidates. Toute règle ou tout seuil que tu proposes est marqué « à valider » "
         "par le responsable métier : tu ne présentes jamais un seuil comme officiel. "
         "Distingue les constats statistiques des exigences métier et les erreurs techniques des anomalies métier."),
      "tool_ids": ["list_tables", "describe_table", "get_table_profile", "execute_sql"],
      "knowledge_tables": DQ_TABLES, "temperature": 0.1, "max_iterations": 6}),
    ({"name": "SQL Assistant", "icon": "terminal", "category": "Analyse",
      "description": "Explore les tables accessibles et répond aux questions par des requêtes SQL en lecture seule."},
     {"instructions": (
         "Tu es un assistant SQL Databricks. Avant d'écrire une requête, vérifie la structure des tables "
         "avec describe_table. Écris du SQL Databricks en lecture seule, montre la requête utilisée et résume le résultat."),
      "tool_ids": ["list_tables", "describe_table", "execute_sql"], "knowledge_tables": [],
      "temperature": 0.0, "max_iterations": 8}),
    ({"name": "Smart Office", "icon": "support_agent", "category": "Exploitation",
      "description": "Assistant bureautique : consulte et envoie des messages via le flux Power Automate Smart Office."},
     {"instructions": (
         "Tu es Smart Office, assistant bureautique de SNCF Réseau. Tu traites les demandes de messagerie "
         "en appelant le flux Power Automate : office_read pour rechercher ou lire, office_send pour envoyer ou répondre. "
         "Avant un envoi, rédige un message clair et professionnel, vérifie le destinataire, l'objet et le corps, "
         "et n'invente jamais une adresse : demande-la si elle manque. Chaque envoi est soumis à l'approbation "
         "de l'utilisateur ; si elle est refusée, n'insiste pas. Rends compte du résultat renvoyé par le flux "
         "sans l'embellir ; en cas d'erreur, cite le code HTTP et le message."),
      "tool_ids": ["office_read", "office_send"], "knowledge_tables": [],
      "temperature": 0.2, "max_iterations": 5}),
]


def seed_tools(repo: AgentRepository) -> int:
    for spec in BUILTIN_TOOLS:
        repo.upsert_tool(spec)
    return len(BUILTIN_TOOLS)


def seed_example_agents(repo: AgentRepository, owner: str, model_endpoint: str) -> list[str]:
    existing = {a["name"] for a in repo.list_agents()}
    created = []
    for meta, cfg in EXAMPLE_AGENTS:
        if meta["name"] in existing:
            continue
        created.append(repo.create_agent(meta, {**cfg, "model_endpoint": model_endpoint}, owner, status="publie"))
    return created
