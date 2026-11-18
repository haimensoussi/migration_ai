# SNCF DQ Studio

App Databricks de pilotage de la qualite des donnees SNCF Reseau (chaine DQ v3, cadre DAMA-DMBOK).

## Lot 1

* Accueil : regles critiques en echec en premier (jamais masquees par un score moyen), indicateurs, synthese par objet, derniers runs.
* Lancer un controle : source choisie dans la liste blanche `sncf_dqv3_app.app_sources`, prefixe calcule `sncf_dqv3_<code_source>`, controle du role, trace dans `app_lancements` avant tout lancement (sans trace, pas de lancement).
* Suivi des executions : etat par tache (derniere tentative), erreurs techniques separees du bilan metier des regles, passage Bronze -> Silver.
* Analyste IA : agent outille en lecture seule (perimetre `<prefixe>_config|results|silver|gold` + Bronze de la source), regles candidates en brouillon `a_valider` jamais enregistrees, aucun lancement ni ecriture.

A venir : Resultats, Anomalies et remediation, Catalogue des regles (validation tracee dans `app_validations`), Sources.

## Identites

| Operation | Identite |
| --- | --- |
| Lecture des resultats, agent IA, modele | Utilisateur (scopes `sql`, `model-serving`) |
| Lancement du job, liste des runs | Service principal (CAN_MANAGE_RUN sur le job 1083902303793833), apres controle du role |
| Ecriture du journal des lancements | Service principal, schema `dataops_dev.sncf_dqv3_app` uniquement |

Roles : table `app_roles` (lanceur, steward, resp_metier, admin_dq) et variable `DQ_ADMINS`. Sans role : lecteur.

## Droits a accorder au service principal

```sql
GRANT USE CATALOG ON CATALOG dataops_dev TO `<client_id_du_SP>`;
GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA dataops_dev.sncf_dqv3_app TO `<client_id_du_SP>`;
```

Les utilisateurs ont besoin de `SELECT` sur `sncf_dqv3_app` et sur les schemas `<prefixe>_*` qu'ils consultent.

## Tests

```
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests
```

Contraintes : Streamlit >=1.38,<1.45 ; pas de `st.button(icon=)`.
