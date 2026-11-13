"""Contrats des outils (source de vérité du code). Le catalogue Delta est initialisé à partir de cette liste."""
from __future__ import annotations

from backend.tool_registry import ToolSpec

_TABLE = {"type": "string", "description": "Nom complet catalog.schema.table"}

BUILTIN_TOOLS: list[ToolSpec] = [
    ToolSpec(
        tool_id="list_tables", name="Lister les tables", category="Unity Catalog",
        description="Liste les tables d'un schéma Unity Catalog accessibles à l'utilisateur.",
        input_schema={"type": "object", "properties": {
            "catalog": {"type": "string", "description": "Catalogue"},
            "schema": {"type": "string", "description": "Schéma"}}, "required": ["catalog", "schema"]},
        output_schema={"type": "object", "properties": {"schema": {"type": "string"}, "nombre": {"type": "integer"},
                       "tables": {"type": "array"}}},
        executor="tools.uc_tools:list_tables"),
    ToolSpec(
        tool_id="describe_table", name="Décrire une table", category="Unity Catalog",
        description="Renvoie les colonnes (nom, type, commentaire) et les propriétés d'une table.",
        input_schema={"type": "object", "properties": {"table": _TABLE}, "required": ["table"]},
        output_schema={"type": "object", "properties": {"table": {"type": "string"}, "colonnes": {"type": "array"},
                       "details": {"type": "object"}}},
        executor="tools.uc_tools:describe_table"),
    ToolSpec(
        tool_id="get_table_profile", name="Profiler une table", category="Qualité des données",
        description="Calcule le nombre de lignes, le taux de valeurs nulles et le nombre approximatif de valeurs distinctes par colonne.",
        input_schema={"type": "object", "properties": {"table": _TABLE,
                      "max_columns": {"type": "integer", "minimum": 1, "maximum": 60,
                                      "description": "Nombre maximal de colonnes profilées (défaut 30)"}},
                      "required": ["table"]},
        output_schema={"type": "object", "properties": {"n_lignes": {"type": "integer"}, "profil": {"type": "array"}}},
        executor="tools.uc_tools:get_table_profile"),
    ToolSpec(
        tool_id="execute_sql", name="Exécuter une requête SQL", category="SQL",
        description="Exécute UNE requête SQL en lecture seule (SELECT, WITH, SHOW, DESCRIBE) avec les droits de l'utilisateur. Utiliser des noms complets catalog.schema.table.",
        input_schema={"type": "object", "properties": {
            "query": {"type": "string", "description": "Requête SQL Databricks en lecture seule"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Lignes maximum (défaut 100)"}},
            "required": ["query"]},
        output_schema={"type": "object", "properties": {"colonnes": {"type": "array"}, "lignes": {"type": "array"},
                       "tronque": {"type": "boolean"}}},
        executor="tools.sql_tools:execute_sql"),
    ToolSpec(
        tool_id="get_job_status", name="Suivre un Job", category="Jobs",
        description="Donne l'état d'une exécution de Job (run_id) ou des 5 dernières exécutions d'un Job (job_id).",
        input_schema={"type": "object", "properties": {"run_id": {"type": "integer"}, "job_id": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"execution": {"type": "object"},
                       "dernieres_executions": {"type": "array"}}},
        executor="tools.job_tools:get_job_status"),
    ToolSpec(
        tool_id="run_job", name="Déclencher un Job", category="Jobs",
        description="Déclenche un Job autorisé (liste blanche) après validation humaine.",
        input_schema={"type": "object", "properties": {"job_id": {"type": "integer"},
                      "parameters": {"type": "object"}}, "required": ["job_id"]},
        output_schema={"type": "object", "properties": {"run_id": {"type": "integer"}}},
        executor="tools.planned:not_available", requires_confirmation=True, read_only=False, status="planifie"),
    ToolSpec(
        tool_id="search_documents", name="Rechercher des documents", category="Connaissances",
        description="Recherche dans un index Databricks Vector Search (phase 2, Knowledge Studio).",
        input_schema={"type": "object", "properties": {"index": {"type": "string"}, "query": {"type": "string"},
                      "k": {"type": "integer"}}, "required": ["index", "query"]},
        output_schema={"type": "object", "properties": {"passages": {"type": "array"}}},
        executor="tools.planned:not_available", status="planifie"),
    ToolSpec(
        tool_id="generate_sql", name="Générer du SQL", category="SQL",
        description="Génère une requête SQL à partir d'une question en langage naturel (phase 2).",
        input_schema={"type": "object", "properties": {"question": {"type": "string"},
                      "tables": {"type": "array"}}, "required": ["question"]},
        output_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
        executor="tools.planned:not_available", status="planifie"),
    ToolSpec(
        tool_id="get_billing_usage", name="Consommations Databricks", category="FinOps",
        description="Consommations DBU (system.billing.usage). Indisponible : accès au catalogue system requis.",
        input_schema={"type": "object", "properties": {"days": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"usage": {"type": "array"}}},
        executor="tools.planned:not_available", status="indisponible"),
    ToolSpec(
        tool_id="get_table_lineage", name="Lignage d'une table", category="Gouvernance",
        description="Lignage amont/aval (system.access.table_lineage). Indisponible : accès au catalogue system requis.",
        input_schema={"type": "object", "properties": {"table": _TABLE}, "required": ["table"]},
        output_schema={"type": "object", "properties": {"amont": {"type": "array"}, "aval": {"type": "array"}}},
        executor="tools.planned:not_available", status="indisponible"),
]
