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
        tool_id="render_chart", name="Afficher un graphique", category="Visualisation",
        description=("Exécute UNE requête SQL en lecture seule et affiche le résultat en graphique dans le chat : "
                     "barres, barres_horizontales, courbe, aire, camembert, nuage ou tableau. Agréger en SQL "
                     "(GROUP BY) avant de tracer ; x = catégories ou axe horizontal, y = colonne numérique. "
                     "Renvoie un résumé (lignes, aperçu, statistiques de y) ; le graphique est affiché à "
                     "l'utilisateur. Pour une carte, utiliser render_map."),
        input_schema={"type": "object", "properties": {
            "query": {"type": "string", "description": "Requête SQL en lecture seule renvoyant les colonnes à tracer"},
            "type": {"type": "string", "enum": ["barres", "barres_horizontales", "courbe", "aire", "camembert",
                                                "nuage", "tableau"], "description": "Type de graphique"},
            "title": {"type": "string", "description": "Titre du graphique"},
            "x": {"type": "string", "description": "Colonne des catégories ou de l'axe horizontal"},
            "y": {"type": "string", "description": "Colonne numérique"},
            "color_by": {"type": "string", "description": "Colonne de regroupement (facultatif)"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Lignes au plus (200 par défaut)"}},
            "required": ["query", "type"]},
        output_schema={"type": "object"}, executor="tools.chart_tools:render_chart"),
    ToolSpec(
        tool_id="render_map", name="Afficher une carte", category="Visualisation",
        description=("Exécute UNE requête SQL en lecture seule et affiche le résultat sur une carte interactive dans le "
                     "chat. Le résultat doit contenir une colonne latitude et une colonne longitude (WGS84). "
                     "Renvoie un résumé (nombre de points, emprise, aperçu, légende) ; la carte est affichée à "
                     "l'utilisateur. 5 000 points au plus."),
        input_schema={"type": "object", "properties": {
            "query": {"type": "string", "description": "Requête SQL en lecture seule renvoyant latitude et longitude"},
            "title": {"type": "string", "description": "Titre de la carte"},
            "layer": {"type": "string", "enum": ["points", "heatmap"], "description": "Points (défaut) ou densité"},
            "color_by": {"type": "string", "description": "Colonne du résultat utilisée pour la couleur"},
            "tooltip": {"type": "array", "items": {"type": "string"}, "description": "Colonnes affichées au survol"},
            "lat_column": {"type": "string", "description": "Nom de la colonne latitude si elle n'est pas latitude/lat"},
            "lon_column": {"type": "string", "description": "Nom de la colonne longitude si elle n'est pas longitude/lon"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5000, "description": "Points maximum (défaut 5000)"}},
            "required": ["query"]},
        output_schema={"type": "object", "properties": {"nombre_points": {"type": "integer"},
                       "emprise": {"type": "object"}, "apercu": {"type": "array"}, "legende": {"type": "object"}}},
        executor="tools.map_tools:render_map"),
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
    ToolSpec(
        tool_id="office_read", name="Smart Office : consulter", category="Automatisation",
        description=("Appelle le flux Power Automate Smart Office pour une opération de consultation "
                     "(recherche ou lecture de messages). Renseigner technology, operation et query ou message_id."),
        input_schema={"type": "object", "properties": {
            "technology": {"type": "string", "description": "Technologie cible du flux (ex. outlook)"},
            "operation": {"type": "string", "description": "Opération de consultation attendue par le flux"},
            "query": {"type": "string", "description": "Critère de recherche"},
            "message_id": {"type": "string", "description": "Identifiant du message à lire"},
            "question": {"type": "string", "description": "Demande de l'utilisateur, transmise pour traçabilité"}},
            "required": ["technology", "operation"]},
        output_schema={"type": "object", "properties": {"http_status": {"type": "integer"},
                       "reponse_flux": {}}},
        executor="tools.power_automate:office_read", identity="application"),
    ToolSpec(
        tool_id="http_call", name="Appel HTTP", category="Automatisation",
        description=("Appelle une URL HTTP(S) publique et renvoie le statut, le type et le contenu de la réponse : "
                     "sert à tester un service web ou un déclencheur (ex. flux Power Automate). Chaque appel est "
                     "suspendu jusqu'à la validation de l'utilisateur. Adresses privées, redirections et en-têtes "
                     "d'identification refusés ; valeurs sensibles de l'URL masquées."),
        input_schema={"type": "object", "properties": {
            "url": {"type": "string", "description": "URL complète http:// ou https://"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]},
            "body": {"type": "object", "description": "Corps JSON (POST, PUT, PATCH)"},
            "headers": {"type": "object", "description": "En-têtes supplémentaires, sans identifiants"},
            "timeout_s": {"type": "integer", "minimum": 1, "maximum": 30}},
            "required": ["url"]},
        output_schema={"type": "object", "properties": {"statut_http": {"type": "integer"}, "reponse": {"type": "string"},
                                                        "json": {}, "duree_ms": {"type": "integer"}}},
        executor="tools.http_tools:http_call", identity="application",
        requires_confirmation=True, read_only=False),
    ToolSpec(
        tool_id="office_send", name="Smart Office : envoyer", category="Automatisation",
        description=("Appelle le flux Power Automate Smart Office pour envoyer ou répondre à un message. "
                     "L'exécution est suspendue jusqu'à l'approbation de l'utilisateur dans AI Studio."),
        input_schema={"type": "object", "properties": {
            "technology": {"type": "string", "description": "Technologie cible du flux (ex. outlook)"},
            "operation": {"type": "string", "description": "Opération d'envoi attendue par le flux"},
            "to": {"type": "string", "description": "Destinataire(s), séparés par des virgules"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "message_id": {"type": "string", "description": "Message auquel répondre (facultatif)"},
            "question": {"type": "string", "description": "Demande de l'utilisateur, transmise pour traçabilité"}},
            "required": ["technology", "operation", "to", "subject", "body"]},
        output_schema={"type": "object", "properties": {"http_status": {"type": "integer"},
                       "reponse_flux": {}}},
        executor="tools.power_automate:office_send", identity="application",
        requires_confirmation=True, read_only=False),
]
