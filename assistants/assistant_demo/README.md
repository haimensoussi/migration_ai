# Paquet d'assistant `assistant_demo`

Exemple **fictif** d'assistant HORIZON multi-Actions, au format pivot proposé pour la migration vers Databricks
(un assistant -> un agent `ResponsesAgent` avec outils -> un endpoint Model Serving).

| Fichier | Rôle | Devient |
| --- | --- | --- |
| `assistant.yaml` | Manifeste : prompt, Action LLM, orchestration, Actions, config, tests | Structure du projet généré |
| `prompt_system.md` | Prompt système, repris mot pour mot | `system_prompt` de `model_config.yml` |
| `llm.action` (workspace) | Action `llm_call` réelle (code SNCF, non copié dans Git) | Boucle de l'agent |
| `actions/analyser_texte.py` | Action métier fictive | Outil `analyser_texte` |
| `actions/estimer_cout.py` | Action métier fictive (grille FinOps de `llm_call`) | Outil `estimer_cout` |
| `config/horizon_config.yaml` | Contexte HORIZON et préférences | `model_config.yml` |
| `tests/cas_attendus.yaml` | Valeurs attendues calculées à la main | `tests.json` |

Règles : un dossier par assistant, un fichier par Action, aucun secret dans le dépôt.
