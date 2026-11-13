# Databricks AI Studio (MVP)

Studio de création d'agents IA inspiré de Copilot Studio, hébergé dans Databricks Apps (Streamlit).

## Architecture

| Couche | Implémentation |
| --- | --- |
| Interface | Streamlit (`app.py`, `views/`, `ui/`), navigation `st.navigation` |
| Logique métier | `backend/` (indépendant de Streamlit) |
| Moteur agentique | `backend/agent_runtime.py` : modèle -> appel d'outil -> observation -> poursuite, itérations bornées, validation humaine des outils sensibles |
| Modèles | Model Serving, endpoints `llm/v1/chat` avec appel d'outils (défaut `databricks-claude-sonnet-4-6`) |
| Outils | Contrats dans `tools/catalog.py`, exécuteurs dans `tools/`, métadonnées dans la table `tools` |
| SQL | API Statement Execution (REST), paramètres nommés, timeout avec annulation |
| Persistance | Tables Delta `dataops_dev.ai_studio` (`database/schema.sql`) |

## Identités

- Service principal de l'App : lit et écrit uniquement les tables de configuration `dataops_dev.ai_studio`.
- Utilisateur connecté (autorisation « on-behalf-of-user ») : modèles et outils. Les droits Unity Catalog de
  l'utilisateur s'appliquent. Sans jeton utilisateur, l'exécution est refusée (aucun repli sur le service principal).

## Outils du MVP

| Outil | Statut | Remarque |
| --- | --- | --- |
| list_tables, describe_table, get_table_profile | publié | SHOW TABLES / DESCRIBE TABLE EXTENDED |
| execute_sql | publié | lecture seule, 1 instruction, 200 lignes max, limité aux tables de l'agent |
| get_job_status | publié | API Jobs avec le jeton utilisateur |
| run_job | planifié | validation humaine obligatoire |
| search_documents, generate_sql | planifié | phase 2 |
| get_billing_usage, get_table_lineage | indisponible | accès au catalogue `system` requis |

## Déploiement

1. Créer le schéma et les tables : exécuter `database/schema.sql`.
2. Créer l'App depuis le dépôt Git (dossier `apps/databricks-ai-studio`) avec les ressources :
   - `sql-warehouse` : SQL warehouse, droit CAN_USE ;
   - `default-model` : endpoint `databricks-claude-sonnet-4-6`, droit CAN_QUERY.
3. Autorisation utilisateur (user_api_scopes) : `sql`, `serving.serving-endpoints`.
4. Droits du service principal de l'App : `USE CATALOG` sur `dataops_dev`, `USE SCHEMA`, `SELECT`, `MODIFY` sur `dataops_dev.ai_studio`.
5. Page Paramètres : « Synchroniser le catalogue d'outils », puis « Créer les agents d'exemple ».

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests
```

Tests unitaires : garde SQL, contrats et registre d'outils, liste blanche des tables, boucle agentique
(modèle simulé), limite d'itérations, pause et reprise après validation humaine.

## Phases suivantes

- Phase 2 : Knowledge Studio (Volumes, `ai_parse_document`, Vector Search), Marketplace, Assessment Center (MLflow).
- Phase 3 : publication des agents en endpoints Model Serving (`ResponsesAgent`), traces MLflow, consommation, gestion fine des versions.
