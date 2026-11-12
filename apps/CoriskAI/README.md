# CoriskAI — paquet d'assistant HORIZON (démonstration)

**Démonstration.** Assistant CORISK.IA d'analyse des risques projets, reconstitué au format HORIZON à partir des
modules de ce dossier pour tester le migrateur sur un cas RAG. Ce n'est pas le code HORIZON réel de CORISK.IA.

## Contenu

| Fichier | Rôle |
| --- | --- |
| `assistant.yaml` | Manifeste : prompt, Action LLM, orchestration, Actions, configuration, tests, **dépendances** |
| `prompt_system.md` | Prompt de `agent_risk_chat.py` (mot pour mot) + consignes d'utilisation des outils |
| `actions/rechercher_passages.py` | Outil : recherche des passages d'un projet (HORIZON : index FAISS + segments sur disque) |
| `actions/calculer_criticite.py` | Outil : criticité = probabilité x impact et niveau (**grille de démonstration, à valider**) |
| `config/horizon_config.yaml` | Contexte, services externes désactivés, modèles autorisés |
| `tests/cas_attendus.yaml` | 18 cas d'Actions + 4 conversations |
| `extract_project_pdf.py`, `ingest_project.py` | **Hors paquet** : chaîne d'indexation (PDF -> segments), à compléter |
| `agent_risk_chat.py`, `build_agent_risk.py` | **Hors paquet** : version d'origine, remplacée par l'agent généré |

L'Action LLM est l'Action `llm_call` réelle, lue dans le workspace (non copiée dans Git).

## Dépendances (à valider)

| Objet | Nom proposé | Créé par |
| --- | --- | --- |
| Volume des PDF | `dataops_dev.knowledge.corisk_documents` | Job (Volume vide) ; PDF déposés après validation du Data Owner |
| Table des segments | `dataops_dev.knowledge.corisk_chunks` | Chaîne d'indexation (Data Engineer) |
| Index Vector Search | `dataops_dev.knowledge.corisk_chunks_index`, filtré par `project_id` | Data Engineer |
| Endpoint Vector Search | `corisk_vs_endpoint` | Administrateur |
| Endpoint d'embedding | `databricks-gte-large-en` (existant) | — |

Tant que la table et l'index n'existent pas, la génération et les tests sont possibles mais le **déploiement
est refusé** (étape « 4. Dépendances » de l'App).

## Points à valider

* Grille de criticité (niveaux et seuils) : démonstration `demo-0`, à valider par le métier.
* Noms et emplacement des objets Unity Catalog.
* PDF de projet de test (non confidentiel) et risques attendus, pour les cas nominaux de recherche.

## Migration

Dans l'App de migration, parcours « Assistant (dépôt Git) », lien :
`https://github.com/haimensoussi/migration_ai/tree/main/apps/CoriskAI`
