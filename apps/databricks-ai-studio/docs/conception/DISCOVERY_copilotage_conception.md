# DISCOVERY — Équipe de copilotage supervisée par HakimAI

Dossier de conception fonctionnelle et technique — version 0.1 (2026-11-23) — **statut : à valider**

Aucun code n'est développé à ce stade. Toute implémentation suivra la validation de ce dossier, avec aperçu et accord explicite avant chaque commit et chaque déploiement.

---

## 0. Décisions prises

| # | Décision | Source | Date |
| --- | --- | --- | --- |
| D1 | Cible prioritaire : niveau EIA **L3 — Entreprise copilotée** ; architecture préparée pour L4/L5 | Utilisateur | 2026-11-23 |
| D2 | **HakimAI supervise l'équipe de copilotage IA** (chef d'équipe) | Utilisateur | 2026-11-23 |
| D3 | Les agents de copilotage sont des **agents système définis dans le code** (comme HakimAI et l'EIA Transformation Factory), hors Marketplace, non modifiables par les utilisateurs | Choix par défaut validé | 2026-11-23 |
| D4 | Cas pilote : **Data Quality Supply Chain** (le cas « coûts informatiques » est bloqué faute d'accès à `system.billing`) | Choix par défaut validé | 2026-11-23 |
| D5 | Valideur humain par défaut : **Data Office** | Choix par défaut validé | 2026-11-23 |
| D6 | Rester sur `dataops_dev.ai_studio` (pas de catalogue dédié) ; privilégier le natif Databricks | Décisions antérieures | 2026-11-21 |
| D7 | Processus métier reportés (jumeau organisé par unités, équipes, cas d'usage) | Décision antérieure | 2026-11-21 |

---

## 1. Objet et périmètre

Ce dossier définit :

1. l'**équipe de copilotage IA** : HakimAI (chef) et 8 agents système ;
2. sa relation avec l'**équipe de pilotage humaine** (Data Office) et les **équipes métier IA** ;
3. les **moteurs** qui garantissent les règles (Intelligence, Mission, Agent Mesh, Autopilot, Gouvernance, Learning) ;
4. le **modèle de données** des signaux, recommandations et missions ;
5. le **cas pilote** Data Quality Supply Chain ;
6. le **plan d'incréments** et les critères d'acceptation.

Hors périmètre de cette version : niveau L4/L5 en production, processus métier, multi-cloud (interfaces seulement prévues), équipes Sales et HR.

---

## 2. Principes directeurs

| # | Principe | Conséquence |
| --- | --- | --- |
| P1 | **Les agents raisonnent, les moteurs garantissent** | Les agents proposent (analyses, recommandations, plans, choix d'équipes). Les moteurs Python détiennent l'état et appliquent les règles : statuts, validations, niveau d'autonomie, politiques. |
| P2 | **Plafond L3** | Aucune action à effet (écriture, flux, job) sans validation humaine enregistrée. |
| P3 | **HakimAI ne valide jamais** | Il prépare, coordonne et synthétise ; la décision appartient à l'équipe de pilotage humaine. |
| P4 | **Traçabilité de bout en bout** | Signal → recommandation → mission → tâche → exécution → résultat, chaque lien est une clé enregistrée. |
| P5 | **Réutiliser avant de créer** | Annuaire Agent Mesh, outils publiés, publication/validation, Transformation, chaîne DQ v3. |
| P6 | **Constat ≠ exigence** | Un écart statistique détecté n'est pas une règle métier ; toute règle ou tout seuil proposé est marqué « à valider ». |
| P7 | **Séparer erreur technique et anomalie métier** | Les signaux portent un type distinct (`technique` / `metier`). |
| P8 | **Moteurs indépendants de Databricks** | Les moteurs métier n'importent pas le SDK Databricks ; ils passent par des interfaces (SQL, modèles, jobs, flux). |

---

## 3. Acteurs

### 3.1 Trois niveaux

| Niveau | Qui | Rôle |
| --- | --- | --- |
| Pilotage humain | Data Office (valideur par défaut), responsables de filière Supply Chain / PTE / UDR, Data Owners, Data Stewards | Fixe les objectifs, arbitre, **valide** recommandations et missions, accorde l'autonomie |
| Copilotage IA | HakimAI (chef) + 8 agents système | Observe, comprend, anticipe, recommande, prépare les missions, coordonne |
| Exécution IA | Équipes métier publiées (ex. « Qualité des données » : Jules, Clara, Victor) et futures équipes de la AI Teams Marketplace | Réalisent les tâches des missions avec leurs outils |

### 3.2 RACI du cycle de copilotage

R = réalise, A = approuve / responsable final, C = consulté, I = informé.

| Activité | HakimAI | Agents copilotage | Équipes métier IA | Data Office | Resp. filière / Data Owner | Data Steward | Admin plateforme |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Détecter les signaux | I | R | C | I | I | I | |
| Diagnostiquer | C | R | C | I | C | C | |
| Recommander | R (synthèse) | R | C | A | C | C | |
| Créer une mission | R (proposition) | R | I | A | C | I | |
| Nommer les responsables | C | R (proposition) | I | A | R | C | |
| Exécuter une tâche | I | C | R | I | C | R | |
| Valider une action à effet | I | I | I | A | R | C | |
| Mesurer les résultats | I | R | C | I | I | I | |
| Clôturer la mission | R (proposition) | C | I | A | C | I | |
| Accorder un niveau d'autonomie | I | I | I | A | C | | R |
| Administrer politiques et rôles | | | | C | I | | R/A |

---

## 4. L'équipe de copilotage

### 4.1 HakimAI — chef de copilotage

| Élément | Contenu |
| --- | --- |
| Rôle | Coordonne le cycle, répartit le travail entre les 8 agents, synthétise, s'adresse à l'équipe de pilotage humaine |
| Conserve | Ses fonctions actuelles : guide, outils de lecture, création de brouillons (agents, outils, équipes), Transformation, `trouver_agents`, `demander_a_equipe` |
| Nouveaux outils | `lancer_cycle`, `lister_signaux`, `proposer_recommandation`, `proposer_mission`, `suivre_mission`, `consulter_resultats` |
| Ne peut pas | Valider une recommandation, une mission ou une action ; modifier un niveau d'autonomie ; publier |
| Identité | Celle de l'utilisateur (OBO) pour la lecture ; compte de l'App pour l'écriture des tables de copilotage, via les moteurs uniquement |

### 4.2 Les 8 agents système

| Agent (identifiant) | Étape du cycle | Mission | Entrées | Sorties | Outils (existants / à créer) | Effet |
| --- | --- | --- | --- | --- | --- | --- |
| Sentinelle (`cop_sentinelle`) | PERCEIVE | Lire les résultats et événements, détecter les écarts | Résultats DQ, KPI, journaux d'exécution | `signals` | `execute_sql`, `describe_table` / **KPI Monitor**, **Anomaly Detector** | Lecture |
| Analyste diagnostic (`cop_diagnostic`) | UNDERSTAND | Qualifier le signal, quantifier, chercher des causes possibles | Signal, données sources | Diagnostic attaché au signal | `get_table_profile`, `execute_sql`, `render_kpi`, `render_chart` | Lecture |
| Prévisionniste (`cop_prevision`) | PREDICT | Projeter l'évolution si rien n'est fait | Historique KPI | Prévision avec intervalle et méthode | Réutilise les modèles de l'équipe Prévision (MLflow) / **Forecast Studio** | Lecture |
| Stratège (`cop_stratege`) | PLAN | Proposer 1 à 3 options comparées (gain, effort, risque) | Diagnostic, prévision | `recommendations` (+ `scenarios`) | `generate_report` / **Scenario Simulator** | Lecture |
| Planificateur de missions (`cop_planificateur`) | PLAN | Transformer une recommandation validée en mission | Recommandation validée | Brouillon `missions` + `mission_tasks` | **Mission Builder** | Brouillon |
| Répartiteur Mesh (`cop_repartiteur`) | ACT (préparation) | Proposer l'équipe IA, les outils et les responsables humains de chaque tâche | Tâches, annuaire | Affectations proposées | `mesh_org` (recherche par capacité), `trouver_agents` | Brouillon |
| Contrôleur gouvernance (`cop_gouvernance`) | Transverse | Vérifier politiques, droits, niveau d'autonomie avant toute étape | Demande d'action | Décision tracée (`policy_decisions`) | `policy_engine` (mode audit puis enforce) | Lecture |
| Analyste des résultats (`cop_resultats`) | LEARN | Mesurer l'écart avant/après, capitaliser | Indicateurs de réussite | `outcomes` | `execute_sql`, `render_kpi`, Monitoring | Lecture |

Règle commune : aucun des 8 agents n'a d'outil à effet direct. Les écritures passent par les moteurs (P1).

### 4.3 Coordination et limite de délégation

L'orchestrateur actuel (`backend/orchestrator.py`) délègue sur **1 niveau, 4 délégations au maximum**. La chaîne « HakimAI → agent de copilotage → équipe métier » demanderait 2 niveaux.

**Choix proposé : le relais passe par le moteur Mission, pas par des délégations imbriquées.**

* HakimAI délègue à ses 8 agents (1 niveau, conforme à l'existant ; limite portée à 8 pour l'équipe système, à valider).
* Les équipes métier ne sont jamais appelées par un agent de copilotage : elles reçoivent des **tâches** du moteur Mission, exécutées après validation.
* Avantages : pas de récursivité, état persistant, reprise possible, validation naturelle à chaque tâche.

---

## 5. Cycle d'intelligence

### 5.1 Déroulé

| Étape | Agent | Moteur | Point de validation humaine |
| --- | --- | --- | --- |
| PERCEIVE | Sentinelle | Intelligence | — |
| UNDERSTAND | Analyste diagnostic | Intelligence | — |
| PREDICT | Prévisionniste | Intelligence | — |
| PLAN (options) | Stratège | Intelligence | **V1 : validation de la recommandation** |
| PLAN (mission) | Planificateur + Répartiteur | Mission + Agent Mesh | **V2 : validation de la mission et des responsables** |
| ACT | Équipes métier IA, humains | Autopilot + Mission | **V3 : validation de chaque action à effet (L3)** |
| LEARN | Analyste des résultats | Learning | **V4 : clôture de la mission** |

Le Contrôleur gouvernance intervient avant chaque passage d'étape.

### 5.2 Déclencheurs

| Mode | Mécanisme | Incrément |
| --- | --- | --- |
| À la demande | HakimAI (`lancer_cycle`) ou bouton du Mission Center | 2 |
| Planifié | Job Databricks (serverless), sur le modèle des Jobs de pilotage existants | 3 |
| Sur événement | Fin d'un run de la chaîne DQ v3 (tâche finale du job ou déclencheur sur table, à vérifier) | 3 |

Le cycle planifié s'arrête à la création de **brouillons** (signaux, recommandations) : il n'agit jamais seul.

---

## 6. Niveaux d'autonomie et validations

### 6.1 Classes d'effet des outils

| Classe | Exemples | L1-L2 | L3 | L4 (préparé, non activé) |
| --- | --- | --- | --- | --- |
| `lecture` | `execute_sql` (SELECT), profils, KPI, graphiques | Libre | Libre | Libre |
| `brouillon` | Créer signal, recommandation, mission brouillon | Libre | Libre | Libre |
| `ecriture` | Écrire une action corrective, une description de colonne | Interdit | Validation V3 | Pré-autorisé par `autonomy_grants` |
| `action` | Déclencher un flux, un job | Interdit | Validation V3 | Pré-autorisé par `autonomy_grants` |

### 6.2 Règles de validation

| Règle | Contenu |
| --- | --- |
| RV-01 | Une recommandation validée (V1) est un préalable à toute mission issue du copilotage |
| RV-02 | La validation V2 porte sur la mission entière : objectif, tâches, responsables, échéances, indicateurs |
| RV-03 | Toute tâche de classe `ecriture` ou `action` exige V3, même dans une mission validée |
| RV-04 | Le valideur ne peut pas être l'auteur (HakimAI ou agent) ; principe des quatre yeux si le demandeur est humain |
| RV-05 | Refus = statut `rejete` + motif obligatoire, conservé pour l'apprentissage |
| RV-06 | Une validation expire si la mission est modifiée après coup (nouvelle version = nouvelle validation) |
| RV-07 | Valideur par défaut : Data Office ; délégation possible au responsable de filière via `role_assignments` (rôle `domain_validator`) |

---

## 7. Modèle de données

Toutes les tables sont dans `dataops_dev.ai_studio`, écrites par le compte de l'App via les moteurs. Identifiants : préfixe + 12 hexadécimaux (convention existante `tp_`, `ti_`).

### 7.1 Nouvelles tables

| Table | Grain | Clé | Colonnes principales | Statuts |
| --- | --- | --- | --- | --- |
| `signals` | 1 écart détecté | `signal_id` (`sg_`) | `source_type` (dq_run, kpi, job…), `source_ref`, `domain`, `object_fqn`, `signal_type` (technique / metier), `severity`, `metric`, `observed`, `reference`, `evidence` (JSON : requête, extrait), `cycle_id`, `detected_at`, `fingerprint` | nouveau, qualifie, ecarte, traite |
| `recommendations` | 1 recommandation | `reco_id` (`rc_`) | `signal_ids` (JSON), `title`, `rationale`, `options` (JSON : gain, effort, risque), `chosen_option`, `forecast` (JSON), `impacted_domains`, `priority`, `author_agent`, `cycle_id` | brouillon, propose, valide, rejete, obsolete |
| `missions` | 1 mission (versionnée) | `mission_id` (`ms_`) + `version` | `title`, `objective`, `origin_type` (utilisateur, evenement, recommandation, transformation), `origin_ref`, `domain`, `owner_human`, `sponsor`, `priority`, `due_date`, `deliverables` (JSON), `success_indicators` (JSON), `autonomy_level` (L3 par défaut) | brouillon, propose, validee, en_cours, en_attente, terminee, cloturee, annulee |
| `mission_tasks` | 1 tâche | `task_id` (`mt_`) | `mission_id`, `title`, `assignee_type` (humain, equipe_ia, agent_ia), `assignee_ref`, `tools` (JSON), `effect_class`, `depends_on` (JSON), `due_date`, `deliverable`, `result` (JSON) | a_faire, en_attente_validation, prete, en_cours, terminee, echec, annulee |
| `mission_events` | 1 événement | `event_id` | `mission_id`, `task_id`, `event_type`, `actor`, `payload`, `created_at` | (journal immuable) |
| `mission_approvals` | 1 décision humaine | `approval_id` | `target_type` (recommandation, mission, tache, cloture), `target_ref`, `target_version`, `decision` (valide, rejete), `decided_by`, `note`, `decided_at` | — |
| `copilot_cycles` | 1 exécution du cycle | `cycle_id` (`cy_`) | `trigger` (demande, planifie, evenement), `scope` (domaines, objets), `started_at`, `ended_at`, `status`, `counts` (JSON), `model_tokens` | en_cours, termine, echec |
| `outcomes` | 1 mesure de résultat | `outcome_id` | `mission_id`, `indicator`, `baseline`, `target`, `measured`, `measured_at`, `verdict` (atteint, partiel, non_atteint) | — |
| `autonomy_grants` | 1 autorisation (préparation L4) | `grant_id` | `scope` (domaine, outil, classe d'effet), `max_level`, `granted_by`, `valid_from`, `valid_to`, `conditions` | actif, revoque |

Tables **reportées** (Enterprise Twin) : `twin_nodes`, `twin_edges`. En attendant, le jumeau est reconstitué à la volée depuis `domains`, `teams`, `team_members`, `agents`, `transformation_items`, `missions`.

### 7.2 Tables existantes réutilisées

| Table | Usage |
| --- | --- |
| `domains`, `teams`, `team_members`, `agents` | Annuaire pour le Répartiteur Mesh |
| `role_assignments`, `agent_policies`, `policy_decisions` | Gouvernance (aujourd'hui 0 décision : moteur non branché) |
| `transformation_plans`, `transformation_items` | Origine possible d'une mission (`origin_type = transformation`) |
| `copilot_actions` | Journal des actions de HakimAI (conservé) |
| `publication_requests`, `domain_owners` | Modèle du circuit de validation à reproduire |
| `conversations`, `tool_calls`, `agent_kpi_daily` | Traçabilité et mesure |

### 7.3 Règles d'historisation

* `mission_events` et `mission_approvals` : ajout seul, jamais de mise à jour ni de suppression.
* `missions` : nouvelle ligne par version ; la version validée est figée.
* `signals` : dédoublonnage par `fingerprint` (même source, même objet, même métrique, même jour).
* Pas de suppression physique ; annulation par statut.

### 7.4 Sécurité

* Écriture des tables de copilotage par le compte de l'App uniquement (droit MODIFY déjà accordé sur le schéma).
* Lecture des données métier avec l'identité de l'utilisateur (OBO) : un agent ne voit que ce que l'utilisateur voit.
* Le cycle planifié tourne avec l'identité du job : son périmètre de lecture doit être limité au pilote (à définir).

---

## 8. Moteurs

Module proposé : `backend/copilot/` (Python pur, sans import du SDK Databricks — P8).

| Moteur | Fichier proposé | Responsabilités | Fonctions principales |
| --- | --- | --- | --- |
| Intelligence | `intelligence.py` | Signaux, diagnostics, prévisions, recommandations | `run_cycle(scope, trigger)`, `record_signal()`, `qualify_signal()`, `propose_recommendation()` |
| Mission | `missions.py` | Cycle de vie, versions, tâches, dépendances, validations | `create_from_recommendation()`, `submit()`, `approve()`, `reject()`, `next_ready_tasks()`, `close()` |
| Agent Mesh | `backend/mesh_org.py` (existant) | Recherche par capacité, affectations | Réutilisé ; ajout `suggest_assignment(task)` |
| Autopilot | `autopilot.py` | Enchaînement du cycle, respect du niveau d'autonomie, exceptions | `advance(mission_id)`, `execute_task(task_id)` (après V3), `handle_failure()` |
| Gouvernance | `backend/policy_engine.py` (existant) | Politiques, rôles, décisions tracées | Branchement de `PolicyGate.check()` en mode **audit** |
| Learning | `learning.py` | Mesure, comparaison, retours | `measure(mission_id)`, `feedback_stats()` |
| Équipe système | `team.py` | Définition des 8 agents (instructions, outils, limites) | `COPILOT_AGENTS`, `copilot_team()` |

Interfaces (ports) utilisées par les moteurs : `SqlPort` (déjà `sql_client`), `ModelPort` (déjà `model_client`), `JobPort`, `FlowPort` (déjà `flux`). Seule l'implémentation Databricks est prévue ; la stratégie Azure reste à valider.

### 8.1 Contrat d'outil v2 (extension du `ToolSpec` actuel)

| Champ ajouté | Rôle |
| --- | --- |
| `input_schema`, `output_schema` | Contrat d'entrée et de sortie vérifiable |
| `effect_class` | lecture, brouillon, ecriture, action (section 6.1) |
| `max_autonomy` | Niveau maximal auquel l'outil peut être appelé sans validation |
| `identity_mode` | utilisateur (OBO) ou application |
| `usable_by` | humain, agent, les deux |

Rétrocompatibilité : valeurs par défaut déduites de l'existant (`read_only`, `requires_confirmation`, `identity`).

---

## 9. Interfaces utilisateur

| Page | Contenu | Incrément |
| --- | --- | --- |
| Mission Center (nouvelle) | Liste et fiche de mission : objectif, origine, tâches, dépendances, responsables, échéances, livrables, indicateurs, historique, boutons Valider/Refuser selon le rôle | 1 |
| Intelligence Center (nouvelle) | Signaux par domaine et criticité, recommandations à valider, prévisions, cycles exécutés | 3 |
| HakimAI (existante) | Nouvelles commandes : lancer un cycle, présenter une recommandation, proposer une mission ; fiches Valider/Refuser déjà existantes | 2 |
| Agent Mesh (existante) | Vue de l'équipe de copilotage et de ses délégations | 2 |
| Monitoring (existante) | Coûts en jetons et durée par cycle | 4 |

Aperçu HTML de ces pages à produire avant développement (ajout à `docs/maquette/DISCOVERY_EIA_maquette.html`).

---

## 10. Cas pilote : Data Quality Supply Chain

### 10.1 Sources disponibles (vérifiées le 2026-11-23)

| Source | Contenu vérifié | Usage pilote |
| --- | --- | --- |
| Chaîne DQ v3, préfixe `sncf_dqv3_demo` | `results` : `dq_run` (10), `dq_rule_results` (16), `dq_anomalies` (43), `dq_remediation_actions` (0), `dq_dama_score`, profils ; `gold` : `dq_kpi_daily` + 6 vues (`v_dq_kpi_courant`, `v_dq_anomalies_courantes`…) | **Source principale de la Sentinelle** (résultats déjà calculés, règles « à valider ») |
| Chaîne DQ v3, préfixe `sncf_dqv3_ddr` | Résultats sur `description_du_reseau_bronze` | Extension après le pilote (données réelles) |
| `dataops_dev.ai_studio.data_demo_sc_commandes` (177) et `data_demo_sc_fournisseurs` (24) | Données de démonstration Supply Chain | Diagnostic et mesure par les agents |
| Plan de transformation `tp_3d58ed262f5c` « Pilote Supply Chain Data Quality » | 2 objectifs et 2 domaines validés ; 5 cas d'usage (2 validés, 3 proposés) ; agents Nadia, Karim et « Équipe Supply Chain Data Quality » proposés | Origine des objectifs de mission |

Toutes ces données sont **fictives ou de démonstration** ; aucun seuil officiel SNCF Réseau n'est défini.

### 10.2 Scénario de démonstration

1. **PERCEIVE** — La Sentinelle lit le dernier run DQ v3 et crée des signaux (ex. référentiel fournisseurs : 8 commandes citent un code absent ; 6 dates de livraison antérieures à la commande ; 4 montants incohérents — constats du plan pilote).
2. **UNDERSTAND** — L'Analyste diagnostic quantifie (part des commandes, fournisseurs concernés), distingue erreur technique et anomalie métier, propose des causes possibles marquées « hypothèse ».
3. **PREDICT** — Le Prévisionniste projette l'évolution du taux de conformité si l'historique le permet ; sinon il l'indique (10 runs seulement en démo).
4. **PLAN** — Le Stratège propose 2 options : corriger à la source / mettre en quarantaine et documenter. **V1 par le Data Office.**
5. **Mission** — Le Planificateur crée « Fiabiliser le référentiel fournisseurs Supply Chain », 4 tâches : extraire la liste des codes inconnus (équipe IA Qualité des données, lecture) ; qualifier avec le Data Steward (humain) ; enregistrer les actions correctives dans `dq_remediation_actions` (écriture, V3) ; relancer la chaîne DQ v3 (action, V3). Le Répartiteur propose les responsables. **V2 par le Data Office.**
6. **ACT** — Les tâches de lecture s'exécutent ; les tâches à effet attendent V3.
7. **LEARN** — L'Analyste des résultats compare le taux de rapprochement fournisseurs avant/après ; la mission est clôturée (V4).

### 10.3 Correspondance DAMA-DMBOK (cadre méthodologique) — implémentation DISCOVERY / Databricks

Conformément à vos instructions, DAMA-DMBOK est utilisé comme cadre de gouvernance, distinct des choix techniques.

| ID | Domaine DAMA | Pratique | Étape du cycle | Rôle responsable | Livrable | Composant technique |
| --- | --- | --- | --- | --- | --- | --- |
| CP-01 | Data Quality | Mesure et contrôle continu | PERCEIVE | Responsable Data Quality | Signaux tracés | Chaîne DQ v3 + `signals` |
| CP-02 | Data Quality | Analyse des causes | UNDERSTAND | Data Steward | Diagnostic | Agent Analyste diagnostic |
| CP-03 | Data Governance | Décision et arbitrage | PLAN (V1, V2) | Data Office | Recommandation et mission validées | `mission_approvals` |
| CP-04 | Data Quality | Remédiation | ACT | Data Owner / Data Steward | Actions correctives | `mission_tasks` → `dq_remediation_actions` |
| CP-05 | Data Quality | Vérification de l'efficacité | LEARN | Responsable Data Quality | Mesure avant/après | `outcomes` |
| CP-06 | Metadata Management | Traçabilité règle → résultat → action | Transverse | Data Steward | Chaîne de liens | Clés `signal_id` → `reco_id` → `mission_id` → `task_id` |
| CP-07 | Data Security | Moindre privilège | Transverse | Admin plateforme | Décisions tracées | OBO + `policy_engine` |
| CP-08 | Reference and Master Data | Référentiel fournisseurs | ACT | Data Owner Supply Chain | Référentiel corrigé (hors DISCOVERY) | Source amont (à identifier) |

### 10.4 Points à confirmer pour le pilote

* Accès du compte de l'App aux schémas `sncf_dqv3_demo_*` (non vérifié ; aujourd'hui seul `ai_studio` est accordé).
* Qui écrit dans `dq_remediation_actions` : DISCOVERY (compte de l'App) ou la chaîne DQ v3 elle-même.
* Le droit de relancer le job DQ v3 (1083902303793833) depuis DISCOVERY (outil `run_job` aujourd'hui « planifié »).
* Nom de la personne Data Office et du Data Steward Supply Chain qui valideront.

---

## 11. Existant réutilisé et à créer

| Élément | Statut | Action |
| --- | --- | --- |
| HakimAI (`backend/hakim.py`, outils HakimAI) | Développé | Étendre (outils de copilotage) |
| Orchestrateur (1 niveau, 4 délégations) | Développé | Paramétrer la limite pour l'équipe système |
| Annuaire Agent Mesh (`mesh_org.py`) | Développé | Ajouter `suggest_assignment` |
| Outils lecture / visualisation (19 publiés) | Développé | Réutiliser |
| Circuit de validation (publication, fiches Valider/Refuser) | Développé | S'en inspirer pour `mission_approvals` |
| Transformation (incréments 1-2) | Partiel | Origine possible des missions |
| Moteur de politiques (`policy_engine.py`) | Écrit, non branché | Brancher en audit |
| Modèles de prévision (équipe Prévision, MLflow) | Partiel | Réutiliser pour le Prévisionniste |
| Chaîne DQ v3 (job, résultats, vues Gold, alertes) | Développé (hors App) | Source de la Sentinelle |
| `run_job` | Planifié (non disponible) | À développer (incrément 4) |
| Tables et moteurs de copilotage | Absent | À créer |
| Mission Center, Intelligence Center | Absent | À créer |
| KPI Monitor, Anomaly Detector, Mission Builder | Absent | À créer |
| Assessment Center | Page vide | Hors périmètre de cette version |

---

## 12. Plan d'incréments

Chaque incrément : aperçu, tests (suite existante + nouveaux), accord explicite avant commit et déploiement.

| Incrément | Contenu | Critères d'acceptation |
| --- | --- | --- |
| **1. Socle Mission** | DDL des tables §7.1 (fichier `database/copilot_schema.sql`) ; moteur Mission ; page Mission Center (création manuelle, validation V2, historique) | Mission créée, validée, versionnée ; validation refusée à l'auteur (RV-04) ; journal `mission_events` complet ; tests unitaires du cycle de statuts |
| **2. Équipe de copilotage** | `backend/copilot/team.py` (8 agents système) ; nouveaux outils HakimAI ; cycle **à la demande** jusqu'à la recommandation (V1) puis mission brouillon | Sur le pilote : au moins 1 signal tracé à sa source, 1 recommandation avec 2 options, 1 mission brouillon complète ; aucun outil à effet chez les agents |
| **3. Intelligence Center + planification** | KPI Monitor, Anomaly Detector (sur résultats DQ v3) ; Job planifié ; page Intelligence Center | Le job crée des signaux sans doublon (`fingerprint`) ; aucun effet hors brouillons ; durée et jetons tracés dans `copilot_cycles` |
| **4. Exécution sous validation** | Autopilot `execute_task` ; V3 ; `run_job` ; écriture des actions correctives ; Learning (`outcomes`) | Aucune tâche à effet sans V3 enregistrée ; mesure avant/après produite ; mission clôturée (V4) |
| **5. Gouvernance** | `policy_engine` branché en audit ; contrat d'outil v2 | Chaque passage d'étape produit une ligne `policy_decisions` ; 0 écart non expliqué avant d'envisager enforce |

Vérification finale : rejouer le scénario §10.2 de bout en bout et contrôler la chaîne de clés signal → recommandation → mission → tâches → résultat.

---

## 13. Risques et questions ouvertes

| # | Risque / question | Impact | Proposition |
| --- | --- | --- | --- |
| R1 | Accès App aux schémas DQ v3 non accordé | Bloque la Sentinelle | Demander GRANT SELECT sur `sncf_dqv3_demo_results` et `_gold` au compte de l'App |
| R2 | Pas d'accès au catalogue `system` (billing, audit) | Bloque FinOps et l'audit natif | Garder les journaux applicatifs ; cas FinOps reporté |
| R3 | Données du pilote fictives, peu d'historique (10 runs) | Prévisions peu significatives | Afficher la limite ; ne pas présenter de prévision sans historique suffisant |
| R4 | Coût en jetons d'un cycle à 9 agents | Coût et latence | Budget de jetons par cycle, agents appelés seulement si nécessaire |
| R5 | Arrêts inexpliqués du compute de l'App (23/11) | Disponibilité | Le cycle planifié tourne dans un Job, pas dans l'App |
| Q1 | Limite de délégation de HakimAI portée à 8 ? | — | À valider |
| Q2 | Le cycle planifié tourne avec quelle identité ? | Sécurité | Compte de service du job, périmètre limité au pilote |
| Q3 | Nom des valideurs Data Office et Data Steward Supply Chain | Circuit V1-V4 | À fournir |
| Q4 | Faut-il fusionner les incréments 3-5 de Transformation dans le Mission Center ? | Planning | À arbitrer |
