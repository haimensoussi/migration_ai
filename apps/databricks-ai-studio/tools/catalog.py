"""Contrats des outils (source de vérité du code). Le catalogue Delta est initialisé à partir de cette liste."""
from __future__ import annotations

from backend.tool_registry import ToolSpec

_TABLE = {"type": "string", "description": "Nom complet catalog.schema.table"}

BUILTIN_TOOLS: list[ToolSpec] = [
    ToolSpec(
        tool_id="list_tables", name="Lister les tables", category="Unity Catalog",
        description=("Liste les tables d'un schéma Unity Catalog accessibles à l'utilisateur. Sans catalogue ni "
                     "schéma : zone de données de la plateforme (dataops_dev.ai_studio, tables data_*)."),
        input_schema={"type": "object", "properties": {
            "catalog": {"type": "string", "description": "Catalogue (facultatif : zone de données par défaut)"},
            "schema": {"type": "string", "description": "Schéma (facultatif : zone de données par défaut)"}}},
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
        tool_id="flux_suivi", name="Suivre une demande de flux", category="Flux",
        description=("Lit l'état d'une demande déposée auprès d'un flux Power Automate (outil flux_...) : "
                     "en_attente, en_cours, terminee (avec la réponse du flux), erreur ou expiree. Ne lit que les "
                     "demandes de l'utilisateur. Tant qu'il n'y a pas de réponse, ne pas inventer de résultat."),
        input_schema={"type": "object", "properties": {
            "demande_id": {"type": "string", "description": "Identifiant renvoyé par l'outil de flux"}},
            "required": ["demande_id"]},
        output_schema={"type": "object"}, executor="tools.flow_tools:flux_suivi"),
    ToolSpec(
        tool_id="render_kpi", name="Afficher des indicateurs", category="Visualisation",
        description=("Exécute UNE requête SQL en lecture seule et affiche des cartes d'indicateurs dans le chat. "
                     "Une ligne = un indicateur (12 au plus) : colonne valeur (numérique), colonne libelle (facultative), "
                     "colonne reference (facultative, ex. année précédente) pour l'écart et la tendance. "
                     "format pourcentage : valeurs déjà en % (91.2), écarts en points. sens indique si une hausse est "
                     "favorable. Valeurs, écarts et tendances sont calculés par l'application : les reprendre tels quels."),
        input_schema={"type": "object", "properties": {
            "query": {"type": "string", "description": "Requête SQL en lecture seule, une ligne par indicateur"},
            "valeur": {"type": "string", "description": "Colonne de la valeur (numérique)"},
            "titre": {"type": "string", "description": "Titre du bloc d'indicateurs"},
            "libelle": {"type": "string", "description": "Colonne du libellé de chaque indicateur (facultatif)"},
            "reference": {"type": "string", "description": "Colonne de la valeur de référence (facultatif)"},
            "format": {"type": "string", "enum": ["nombre", "decimal", "pourcentage"], "description": "Format des valeurs"},
            "unite": {"type": "string", "description": "Unité affichée (ex. voyageurs, trains), hors pourcentage"},
            "sens": {"type": "string", "enum": ["hausse_favorable", "baisse_favorable", "neutre"],
                     "description": "Interprétation d'une hausse (neutre par défaut)"},
            "libelle_reference": {"type": "string", "description": "Libellé de la référence (ex. 2024)"}},
            "required": ["query", "valeur"]},
        output_schema={"type": "object"}, executor="tools.report_tools:render_kpi"),
    ToolSpec(
        tool_id="render_smartart", name="Afficher un schéma (SmartArt)", category="Visualisation",
        description=("Affiche sous la réponse un schéma qui en illustre la structure : processus (étapes ordonnées), "
                     "cycle (boucle d'amélioration), hierarchie (organisation, décomposition ; parent = texte exact "
                     "d'un autre élément), relation (éléments et liens libellés), matrice (4 quadrants, axes "
                     "facultatifs). Utiliser seulement quand le schéma clarifie la réponse, avec des éléments déjà "
                     "établis (données lues, documents, réponse) : aucun chiffre ni fait inventé. Textes courts."),
        input_schema={"type": "object", "properties": {
            "type": {"type": "string", "enum": ["processus", "cycle", "hierarchie", "relation", "matrice"],
                     "description": "Forme du schéma"},
            "titre": {"type": "string", "description": "Titre du schéma"},
            "elements": {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {
                "texte": {"type": "string", "description": "Libellé court (60 caractères au plus)"},
                "detail": {"type": "string", "description": "Précision facultative (140 caractères au plus)"},
                "parent": {"type": "string", "description": "hierarchie : texte exact de l'élément parent"}},
                "required": ["texte"]}, "description": "Éléments dans l'ordre (matrice : 4, haut-gauche, haut-droite, "
                                                       "bas-gauche, bas-droite)"},
            "liens": {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {
                "de": {"type": "string"}, "vers": {"type": "string"}, "libelle": {"type": "string"}},
                "required": ["de", "vers"]}, "description": "relation : liens entre textes d'éléments"},
            "axe_x": {"type": "string", "description": "matrice : libellé de l'axe horizontal"},
            "axe_y": {"type": "string", "description": "matrice : libellé de l'axe vertical"}},
            "required": ["type", "titre", "elements"]},
        output_schema={"type": "object"}, executor="tools.smartart_tools:render_smartart"),
    ToolSpec(
        tool_id="generate_report", name="Générer un rapport", category="Visualisation",
        description=("Assemble un rapport téléchargeable (HTML et Markdown) : titre, introduction, sections, conclusion. "
                     "Chaque section a un titre, un texte et, au besoin, une requête SQL en lecture seule affichée en "
                     "tableau ou en graphique (type, x, y, couleur comme render_chart). Les requêtes figurent en "
                     "annexe. Calculer d'abord les chiffres (execute_sql, render_chart, render_kpi) et ne reprendre "
                     "dans les textes que ces chiffres. Pas de carte dans le rapport."),
        input_schema={"type": "object", "properties": {
            "titre": {"type": "string", "description": "Titre du rapport"},
            "introduction": {"type": "string"},
            "sections": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
                "titre": {"type": "string"}, "texte": {"type": "string"},
                "requete": {"type": "string", "description": "Requête SQL en lecture seule (facultative)"},
                "type": {"type": "string", "enum": ["tableau", "barres", "barres_horizontales", "courbe", "aire",
                                                    "camembert", "nuage"]},
                "x": {"type": "string"}, "y": {"type": "string"}, "couleur": {"type": "string"}},
                "required": ["titre"]}},
            "conclusion": {"type": "string"}},
            "required": ["titre", "sections"]},
        output_schema={"type": "object"}, executor="tools.report_tools:generate_report"),
    ToolSpec(
        tool_id="export_excel", name="Exporter en Excel", category="Visualisation",
        description=("Produit un fichier Excel (.xlsx) téléchargeable : une feuille par requête SQL en lecture seule "
                     "(10 feuilles au plus), en-têtes figés et filtrables, nombres et dates typés, plus une feuille "
                     "Informations (date, utilisateur, requête et nombre de lignes de chaque feuille). À utiliser quand "
                     "l'utilisateur demande un export, un fichier Excel ou un tableur. Les nombres de lignes renvoyés "
                     "sont calculés par l'application : les reprendre tels quels et signaler toute feuille tronquée. "
                     "Une feuille peut aussi être un tableau rédigé (colonnes, lignes ; 500 lignes au plus) pour un "
                     "contenu qui n'est pas dans les tables (spécification, plan de test) : il est marqué « non issu "
                     "des données ». Les chiffres issus des données passent toujours par une requête."),
        input_schema={"type": "object", "properties": {
            "titre": {"type": "string", "description": "Titre du fichier (sert aussi au nom du fichier)"},
            "feuilles": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
                "nom": {"type": "string", "description": "Nom de la feuille (31 caractères au plus)"},
                "requete": {"type": "string", "description": "Requête SQL en lecture seule (feuille de données)"},
                "colonnes": {"type": "array", "items": {"type": "string"},
                             "description": "Feuille rédigée : noms des colonnes (facultatif si lignes sont des objets)"},
                "lignes": {"type": "array", "maxItems": 500, "items": {"type": "object"},
                           "description": "Feuille rédigée, à la place de requete : une ligne = un objet colonne -> valeur"}},
                "required": ["nom"]}},
            "limite": {"type": "integer", "minimum": 1, "maximum": 20000,
                       "description": "Lignes au plus par feuille (5000 par défaut)"}},
            "required": ["titre", "feuilles"]},
        output_schema={"type": "object"}, executor="tools.excel_tools:export_excel"),
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

# EIA : catalogue public, mêmes contrats et garde-fous que les outils de HAKIM.
from tools.eia_kpi_tools import EIA_KPI_TOOLS  # noqa: E402
from tools.eia_staff_tools import EIA_STAFF_TOOLS  # noqa: E402
from tools.eia_cycle_tools import EIA_CYCLE_TOOLS  # noqa: E402
from tools.eia_factory_tools import EIA_FACTORY_TOOLS  # noqa: E402

BUILTIN_TOOLS += EIA_KPI_TOOLS + EIA_STAFF_TOOLS + EIA_CYCLE_TOOLS + EIA_FACTORY_TOOLS
