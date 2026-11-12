# CoriskAI — paquet d'assistant (code d'origine CORISK.IA)

Analyste des risques projets SNCF Réseau. Le paquet repose **uniquement sur le code d'origine** du dossier
`actions/` (fonctions Python simples, pas d'Actions HORIZON `RunContext`) : `assistant.yaml` déclare le rôle de
chaque fichier, le migrateur lit tout le reste dans le code (paquet `source_kind: functions`).

## Rôle des fichiers

| Fichier | Rôle dans la source | Devient dans Databricks |
| --- | --- | --- |
| `actions/agent_risk_chat.py` | Agent : prompt, appel LLM (temperature 0.1, max_tokens 1500), 12 passages au plus, sources | `agent.py` (code recopié, ResponsesAgent) |
| `actions/ingest_project.py` | Découpage 1200/200, `chunk_id` sha256 `projet:fichier:page:n` (enregistrement « à faire ») | Indexation du Job : table des segments + index Vector Search |
| `actions/extract_project_pdf.py` | Texte par page d'un PDF du Volume (`fitz`) | `ai_parse_document` dans l'indexation du Job |
| `actions/build_agent_risk.py` | Configuration (nom « CORISK Risk Analyst », endpoint, prompt) | `model_config.yml` |
| `tests/cas_attendus.yaml` | — | 4 cas : 3 issus du comportement source, 1 de l'ajout de la migration |

Les fichiers `*.py` à la racine du dossier sont des copies identiques de ceux de `actions/` (non utilisés).

## Transformations et ajouts de la migration

* `os.environ.get('DATABRICKS_LLM_ENDPOINT')` -> configuration (`agent.env` dans `assistant.yaml`).
* Messages en dictionnaires -> `ChatMessage` (`serving_endpoints.query` refuse les dictionnaires).
* **Ajout** : recherche des passages dans Vector Search, filtrée par `project_id`, quand l'appelant ne fournit pas
  `context_chunks` (la source reçoit toujours les passages de l'appelant).

## Dépendances (déduites du code, créées et vérifiées par le Job au déploiement)

| Objet | Nom (préfixe `corisk`, à valider) |
| --- | --- |
| Volume des PDF | `dataops_dev.knowledge.corisk_documents`, rangement `<project_id>/<fichier>.pdf` |
| Table des segments | `dataops_dev.knowledge.corisk_chunks` (colonnes du dictionnaire de `ingest_project`) |
| Index Vector Search | `dataops_dev.knowledge.corisk_chunks_index`, filtre `project_id`, 12 résultats |
| Endpoint Vector Search | `corisk_vs` (STANDARD, facturé en continu tant qu'il existe) |
| Endpoint d'embedding | `databricks-gte-large-en` (existant ; modèle anglais, à évaluer pour du français) |

## Points à valider

* Valeur de `DATABRICKS_LLM_ENDPOINT` (absente du code) : `databricks-claude-sonnet-4-6` proposé.
* Filtre par `project_id` de la recherche ajoutée, modèle d'embedding, noms des objets.
* PDF de projet de test non confidentiel, pour un test de recherche de bout en bout.

## Migration

Dans l'App de migration, parcours « Assistant (dépôt Git) », lien :
`https://github.com/haimensoussi/migration_ai/tree/main/apps/CoriskAI`
