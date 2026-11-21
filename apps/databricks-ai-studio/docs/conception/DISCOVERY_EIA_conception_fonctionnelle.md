# DISCOVERY — Entreprise Intelligente Augmentée (EIA)
## Dossier de conception fonctionnelle

| | |
| --- | --- |
| Version | 0.3 — projet soumis à validation (v0.2 : AS-IS / TO-BE, jumeau graphique, simulation ; v0.3 : processus reportés, Tool Builder, Flux Builder et Marketplace outils et flux conservés) |
| Date | 21/11/2026 |
| Rédacteur | Genie Code, pour SOUSSI Haimen |
| Statut | **À valider.** Aucun développement EIA ne démarre avant validation de ce dossier. |
| Documents liés | `docs/maquette/DISCOVERY_EIA_maquette.html` ; `docs/audit/DISCOVERY_Agent_Mesh_Audit_Roadmap.xlsx` ; `database/mesh_schema.sql` |

Conventions : **[EXISTANT]** fonction déjà en service dans DISCOVERY ; **[ÉVOLUÉ]** fonction existante étendue ; **[NOUVEAU]** fonction à créer ; **[NATIF]** service Databricks utilisé tel quel ; **[À VALIDER]** hypothèse ou valeur non confirmée par le métier.

---

## 1. Objet et périmètre

### 1.1 Objet
Faire passer DISCOVERY d'une plateforme de création d'agents IA à une plateforme de construction et de pilotage de l'entreprise intelligente augmentée : une organisation où humains, agents IA, équipes intelligentes et flux d'automatisation travaillent ensemble, sous gouvernance.

Principe directeur : **augmenter les collaborateurs, pas les remplacer**. Chaque agent et chaque flux a un humain responsable ; toute action qui écrit, envoie ou décide est validée par un humain.

### 1.2 Périmètre
| Inclus | Exclu (à ce stade) |
| --- | --- |
| Une entreprise : SNCF Réseau, ses domaines (Supply Chain, PTE, UDR, Transverse) | Offre multi-entreprise (option SaaS abandonnée le 19/11/2026 ; le modèle `organizations` la permet plus tard) |
| Jumeau intelligent : organisation, équipes, cas d'usage, applications, objectifs, rattachements | Synchronisation automatique avec le SIRH (source à identifier) |
| Diagnostic et recommandations par l'assistant, validées par un humain | Décision automatique sans validation |
| Construction d'agents, équipes, flux depuis un plan validé | Exécution en production sans publication validée |
| Pilotage : activité, coûts (jetons), gains mesurés | Gains estimés présentés comme réels |

### 1.3 Décision du 21/11/2026 : processus reportés
La modélisation des processus métier (processus, activités) est **reportée**. Le jumeau s'organise pour l'instant par **unités, équipes et cas d'usage** (type `cas_usage` déjà géré par `transformation_items`). Les tables `processes` et `process_activities` restent décrites en annexe pour une version ultérieure.

### 1.4 Pilote proposé [À VALIDER]
Domaine **Supply Chain**, cas d'usage **Data Quality** : données déjà disponibles, règles métier à exploiter en priorité, agents Génie par filière prévus. Le pilote devient la première composante du jumeau.

---

## 2. Les six piliers et leur traduction dans DISCOVERY

| Pilier | Rôle dans l'EIA | Traduction fonctionnelle | État |
| --- | --- | --- | --- |
| Humains | Expertise, décision, responsabilité | Responsables d'unité, de cas d'usage, d'agent, d'outil, de flux ; valideurs par domaine | Partiel : propriétaires et valideurs d'agents existent ; humains dans l'organigramme absents |
| Données | Connaissance de l'entreprise | Tables Unity Catalog, documentation indexée, indicateurs | Existant : outils SQL/UC, Knowledge Assistants, Genie |
| Agents IA | Analyse, recommandation, exécution | Agent Builder, versions, contrats, publication validée | Existant |
| Équipes intelligentes | Collaboration humains + agents | Équipes d'agents avec chef ; équipes hybrides | Partiel : équipes d'agents seules |
| Automatisation | Exécution des tâches métier | Tool Builder, Flux Builder, Marketplace outils et flux, Lakeflow Jobs, validation humaine | Partiel : Flux existe, Jobs non intégrés |
| Gouvernance | Contrôle, sécurité, mesure | Publication validée, rôles, politiques d'accès, journaux, cockpit | Partiel : publication et journaux existent ; rôles et politiques en cours (T204, T206) |

---

## 3. Acteurs et rôles

| Rôle | Responsabilités EIA | Correspondance technique |
| --- | --- | --- |
| Administrateur plateforme | Paramètres, rôles, politiques, publication des outils qui écrivent | `role_assignments.role = platform_admin` (aujourd'hui AI_STUDIO_TOOL_ADMINS) |
| Responsable de domaine | Valide recommandations, publications et plans de son domaine | `domain_admin`, `domain_validator` ; `domain_owners` (vide aujourd'hui) |
| Responsable d'unité / de cas d'usage | Décrit son unité, ses cas d'usage, ses objectifs ; fournit la situation de départ | [NOUVEAU] rattachement au jumeau |
| Concepteur (agent developer) | Construit agents, équipes, flux à partir du plan | `agent_developer` ; propriétaire de l'agent |
| Utilisateur | Utilise agents et équipes publiés | `agent_user` (tout utilisateur authentifié) |
| Auditeur | Consulte journaux et décisions, sans modifier | `auditor` |
| Assistant HakimAI | Analyse, propose, explique ; ne décide jamais | Agent `hakimai`, droits de l'utilisateur connecté (OBO) |

---

## 4. Cycle de vie de l'entreprise augmentée

Le cycle est une boucle : « Mesurer » et « Améliorer » ramènent à « Diagnostiquer ».

| Étape | Objectif | Module | Acteur décideur | Sortie | État |
| --- | --- | --- | --- | --- | --- |
| 1. Comprendre | Décrire l'existant | Enterprise Studio | Responsable d'unité | Jumeau renseigné (unités, équipes, cas d'usage, applications) | [NOUVEAU] |
| 2. Diagnostiquer | Repérer difficultés et opportunités | Transformation | Responsable de domaine | Diagnostic avec preuves (tables, documents cités) | [ÉVOLUÉ] |
| 3. Recommander | Proposer l'architecture cible | Transformation | Responsable de domaine | AS-IS généré et confirmé, TO-BE proposé, écarts ; recommandations `propose` → `valide` / `rejete` | [ÉVOLUÉ] (transformation_items existe) |
| 3 bis. Simuler | Valider la cible avant construction | Transformation · Simulation, Jumeau | Responsable de domaine | Scénarios simulés, contrôles de gouvernance, rejeu en bac à sable, verdict | [NOUVEAU] |
| 4. Construire | Créer agents, équipes, flux | Agent Builder, Équipes, Automation Studio | Concepteur | Brouillons préremplis, liés à la recommandation | [ÉVOLUÉ] |
| 5. Déployer | Mettre en service après validation | Validation | Responsable de domaine / admin | Publication tracée (publication_requests) | [EXISTANT] |
| 6. Superviser | Suivre l'activité et les incidents | Enterprise Cockpit, Agent Mesh | Responsable d'unité | Alertes, journaux | [ÉVOLUÉ] (Monitoring) |
| 7. Mesurer | Mesurer la valeur générée | Enterprise Cockpit | Responsable de cas d'usage | Gain mesuré vs situation de départ | [NOUVEAU] |
| 8. Améliorer | Ajuster l'organisation | Transformation | Responsable de domaine | Nouveau cycle de diagnostic | [NOUVEAU] (boucle) |

---

## 5. Le jumeau intelligent de l'entreprise

### 5.1 Définition
Représentation, dans Unity Catalog, de l'organisation et de son fonctionnement : unités organisationnelles, équipes, cas d'usage, applications, objectifs et indicateurs (processus métier reportés, voir 1.3). À chaque composante peuvent être rattachés : humains, agents, équipes d'agents, flux, données, connaissances, outils.

Règles :
- **J1** Aucune composante n'est inventée : elle est saisie ou importée par son responsable, ou proposée par l'assistant et validée.
- **J2** Chaque composante a un responsable humain.
- **J3** Chaque rattachement est daté et tracé (qui, quand, pourquoi).
- **J4** Le jumeau est versionné : on peut comparer l'état avant et après une transformation.
- **J5** Les données nominatives (organigramme) sont soumises à l'accord RGPD et ne sont visibles qu'avec les droits de l'utilisateur.

### 5.2 Modèle conceptuel

```
organizations 1──n domains 1──n org_units (hiérarchie : parent_unit_id)
                                   │
          ┌────────────────────────┼────────────────────────┐
     user_teams (humains)        cas d'usage (transformation_items)   objectives 1──n kpi_definitions
          │                              │                                  │
   hybrid_team_members  ──────  twin_links (rattachements génériques)  ────  benefit_baselines / benefit_measures
   (humain | agent | équipe d'agents)    │
                     agents · teams · automation_flows · tools · applications · tables UC · connaissances
```

### 5.3 Entités

| Entité | Grain | État | Rôle |
| --- | --- | --- | --- |
| `organizations` | 1 organisation | Créée (T201), 1 ligne | Racine du jumeau |
| `domains` | 1 domaine | Créée (T201), 4 lignes | Domaines existants (liste de `agent_contracts.DOMAINES`) |
| `org_units` | 1 unité | [NOUVEAU] | Directions, départements, services ; parent pour la hiérarchie |
| `users` | 1 utilisateur | Créée (T201), vide | Humains connus de DISCOVERY |
| `user_teams`, `user_team_members` | 1 équipe / 1 appartenance | Créées (T201), vides | Équipes humaines |
| `hybrid_team_members` | 1 membre d'équipe | [NOUVEAU] | Membre humain, agent ou équipe d'agents, avec rôle (responsable, valideur, exécutant, coordinateur) |
| `processes`, `process_activities` | 1 processus / 1 activité | **Reporté** (décision du 21/11/2026) | Processus métier et leurs activités, pour une version ultérieure |
| `applications` | 1 application | [NOUVEAU] | Inventaire SI : propriétaire, domaine, connecteur disponible ou non |
| `objectives`, `kpi_definitions` | 1 objectif / 1 indicateur | [NOUVEAU] | Objectifs d'unité ou de cas d'usage ; formule, grain, source, cible [À VALIDER] |
| `automation_flows` | 1 flux | [NOUVEAU] | Catalogue unifié : flux du Flux Builder (outils `call_flow`, table `tools`) et Lakeflow Jobs ; déclencheur ; responsable |
| `twin_links` | 1 rattachement | [NOUVEAU] | Lien générique composante ↔ ressource (agent, équipe, flux, outil, table, application, connaissance) |
| `benefit_baselines`, `benefit_measures` | 1 mesure | [NOUVEAU] | Situation de départ validée et mesures après déploiement |
| `maturity_assessments` | 1 évaluation | [NOUVEAU] | Maturité par unité ou domaine, datée |
| `transformation_plans`, `transformation_items` | 1 plan / 1 élément | [EXISTANT] | Recommandations (objectif, domaine, cas_usage, agent, equipe, flux, outil ; type `processus` non utilisé pour l'instant) et décisions |
| `teams`, `team_members` | Équipes d'agents | [EXISTANT] | Non renommées ; rattachées aux unités via `twin_links` |
| `twin_versions` | 1 version du jumeau | [NOUVEAU] | Instantané daté : `as_is_propose`, `as_is_confirme`, `to_be_propose`, `to_be_valide`, `realise` ; auteur, source (HakimAI ou humain) |
| `twin_version_items` | 1 élément d'une version | [NOUVEAU] | Nœud ou lien du jumeau dans une version, avec preuve et statut (réel, hypothèse, nouveau) |
| `simulation_scenarios` | 1 scénario | [NOUVEAU] | Version TO-BE simulée, hypothèses (valeurs et source), auteur |
| `simulation_runs` | 1 exécution de simulation | [NOUVEAU] | Résultats : charge, délais, jetons, contrôles, rejeu, verdict ; modèle de calcul versionné |

---

## 6. Modules fonctionnels

### 6.1 Enterprise Studio — éditeur du jumeau [NOUVEAU]
| ID | Fonction | Priorité | Réutilise |
| --- | --- | --- | --- |
| ES-01 | Arborescence organisation → domaines → unités | P1 | Tables T201 |
| ES-02 | Import CSV d'organigramme et d'équipes, avec contrôle (doublons, parents inconnus, responsable manquant) avant chargement | P1 | Outils Excel existants |
| ES-03 | Fiche d'unité : mission, responsable, objectifs, cas d'usage, ressources rattachées | P1 | — |
| ES-04 | Équipe hybride : ajouter humain, agent, équipe d'agents, flux ; rôle de chacun | P1 | Équipes d'agents, chef d'équipe |
| ES-05 | Règles de supervision : qui valide quoi, délai, escalade | P2 | Validation humaine existante |
| ES-06 | Partage d'un agent entre unités sans duplication | P2 | Roadmap T207 |
| ES-07 | Historique et comparaison de versions du jumeau | P3 | — |

### 6.2 Enterprise Transformation — diagnostic et recommandations [ÉVOLUÉ]
| ID | Fonction | Priorité | Réutilise |
| --- | --- | --- | --- |
| ET-01 | Analyse par l'assistant des sources autorisées : jumeau, tables UC, documentation, indicateurs, flux existants | P1 | HakimAI, outils UC/SQL, Knowledge Assistants [NATIF], Genie [NATIF] |
| ET-02 | Diagnostic avec preuves citées ; distinction constat / hypothèse | P1 | `transformation_items.evidence` |
| ET-03 | Recommandations typées : cas d'usage, agent, équipe, flux, outil/connecteur, interaction entre unités | P1 | `transformation_items.item_type` |
| ET-04 | Validation, modification ou rejet motivé par le responsable de domaine | P1 | Statuts propose / valide / rejete |
| ET-05 | Plan de construction : une recommandation validée ouvre l'outil de construction prérempli et garde le lien | P1 | Agent Builder, Équipes, Flux, `TransformationService.link` |
| ET-06 | Architecture cible et roadmap générées depuis les recommandations validées | P2 | Rapports existants |
| ET-07 | Estimation des gains, toujours marquée « estimation » tant qu'aucune situation de départ n'est validée | P2 | — |
| ET-08 | **Génération de l'AS-IS** par HakimAI : cas d'usage, activités, acteurs, applications, données, irritants ; chaque élément porte sa source ou le statut « hypothèse » | P1 | HakimAI, `transformation_items`, outils UC |
| ET-09 | **Confirmation de l'AS-IS** par le responsable (confirmer, corriger) avant toute proposition | P1 | Décisions tracées |
| ET-10 | **Génération du TO-BE** : agents (créés ou réutilisés), équipes hybrides, flux, points de validation humaine, indicateurs ; variantes possibles | P1 | Catalogue d'agents et d'outils, contrats |
| ET-11 | **Tableau des écarts** AS-IS → TO-BE par activité : type de changement (automatisation, augmentation, nouvel agent, réutilisation, contrôle humain), prérequis, décision | P1 | — |
| ET-12 | **Simulation** de la cible (voir 6.7) et soumission de l'organisation cible à validation | P1 | Chat & Test (rejeu), politiques |

### 6.3 Automation Studio [ÉVOLUÉ]
| ID | Fonction | Priorité | Réutilise |
| --- | --- | --- | --- |
| AS-01 | Catalogue unifié des flux (Power Automate + Lakeflow Jobs) | P1 | Page Flux ; Jobs API [NATIF] |
| AS-02 | Déclencheurs : par un agent, planifié, sur événement (arrivée de fichier, mise à jour de table) | P1 | Lakeflow Jobs triggers [NATIF] |
| AS-03 | Flux de validation humaine | P1 | `requires_confirmation`, fiche de validation |
| AS-04 | Rattachement d'un flux à un cas d'usage et à une équipe | P1 | `twin_links` |
| AS-05 | Suivi des exécutions et des échecs | P2 | `flux_demandes`, historique des runs Jobs [NATIF] |
| AS-06 | Marketplace de flux réutilisables | P2 | Marketplace outils et flux (6.8) |
| AS-07 | Flux inter-unités (déclenché par une unité, exécuté pour une autre) | P3 | Politiques d'accès |

Contrainte : Power Automate fonctionne en exécution locale ; sur le serveur, il reste bloqué (réseau, DLP).

### 6.4 Agent Mesh [ÉVOLUÉ]
| ID | Fonction | Priorité | Réutilise |
| --- | --- | --- | --- |
| AM-01 | Rôles et politiques d'accès, refus par défaut, mode audit puis blocage | P1 | Tables T204/T206 créées, moteur à écrire |
| AM-02 | Découverte des agents par capacité et par unité | P2 | Contrats d'agents |
| AM-03 | Délégation entre équipes et superviseur global | P2 | Orchestrateur (1 niveau) |
| AM-04 | Un agent déclenche un flux d'une autre unité, sous politique | P2 | `call_flow` |
| AM-05 | Traçage complet d'une demande à travers les agents | P2 | MLflow Tracing [NATIF] |

### 6.5 Enterprise Cockpit [NOUVEAU]
| ID | Fonction | Priorité | Réutilise |
| --- | --- | --- | --- |
| EC-01 | Vue d'ensemble : agents, équipes, outils, flux, cas d'usage couverts | P1 | Monitoring, `agent_kpi_daily` |
| EC-02 | Performance : conversations, succès des outils, latence | P1 | `conversations`, `tool_calls` |
| EC-03 | Coûts : jetons par agent, par unité (T103) ; DBU quand l'accès aux tables système sera accordé | P1 | Jetons enregistrés depuis T103 |
| EC-04 | Gains : mesure vs situation de départ validée | P2 | — |
| EC-05 | Maturité de transformation par unité et domaine | P2 | — |
| EC-06 | Tableau de bord partagé hors App | P2 | Tableaux de bord AI/BI [NATIF] |

### 6.6 Jumeau intelligent — représentation graphique [NOUVEAU]
| ID | Fonction | Priorité | Réutilise |
| --- | --- | --- | --- |
| JI-01 | Graphe du jumeau : organisation, domaines, unités, équipes, humains, agents, flux, données, et leurs liens | P1 | Tables du jumeau, `teams`, `agents`, `tools` |
| JI-02 | Bascule AS-IS / TO-BE / Écarts ; éléments nouveaux distingués visuellement | P1 | `twin_versions` |
| JI-03 | Filtres par type d'élément et par domaine | P1 | — |
| JI-04 | Fiche d'un élément : type, statut (réel, hypothèse, nouveau), responsable, liens, source | P1 | — |
| JI-05 | Comparaison de deux versions (ex. TO-BE validé vs réalisé) | P2 | — |

### 6.7 Simulation de l'organisation cible [NOUVEAU]

Objectif : vérifier qu'une organisation cible est faisable, gouvernée et utile **avant** de la construire. La simulation ne remplace pas la décision humaine.

| ID | Volet | Contenu | Règle |
| --- | --- | --- | --- |
| SI-01 | Charge et coût | Modèle déterministe : charge humaine AS-IS = volume × temps manuel ; TO-BE = volume × (1 − part agent) × temps manuel + volume × part agent × temps de validation ; jetons = volume × part agent × jetons par traitement | Hypothèses saisies avec leur source ; résultat étiqueté « estimation » |
| SI-02 | Contrôles de gouvernance | Responsable pour chaque agent et flux ; validation humaine des envois ; outils couverts par une politique ; données lisibles avec les droits de l'utilisateur ; responsable de domaine désigné ; flux exécutables dans l'environnement cible | Un contrôle en échec bloque la soumission |
| SI-03 | Rejeu en bac à sable | Les agents TO-BE en brouillon rejouent des cas réels ou préparés dans Chat & Test ; aucun envoi ni écriture réels | Résultat comparé à la réponse attendue définie par le métier |
| SI-04 | Scénarios | Plusieurs jeux d'hypothèses (ex. prudent, proposé), comparables | Chaque scénario est enregistré et versionné |
| SI-05 | Verdict et soumission | Verdict « prêt » ou « non prêt » avec la liste des bloquants ; soumission au responsable de domaine | La validation crée le plan de construction et la version `to_be_valide` |
| SI-06 | Boucle de valeur | Après déploiement, la valeur mesurée est comparée à la simulation | Écart affiché dans le Cockpit ; alimente le diagnostic suivant |

Limites : SI-01 est un modèle de capacité simple, pas une simulation à événements discrets ; sa pertinence dépend de la situation de départ mesurée. Une simulation plus fine (files d'attente, variabilité) est une évolution possible après le pilote.

### 6.8 Tool Builder, Flux Builder et Marketplace outils et flux [EXISTANT, conservés]
| ID | Fonction | État | Composant actuel |
| --- | --- | --- | --- |
| TB-01 | Tool Builder : décrire le besoin, fiche proposée par le copilote, vérification, test avec les droits de l'utilisateur, publication | [EXISTANT] | `ToolDesigner`, `ToolBuilder` (page Catalogue d'outils) |
| TB-02 | Publication des outils qui écrivent ou envoient réservée aux administrateurs des outils | [EXISTANT] | AI_STUDIO_TOOL_ADMINS |
| FB-01 | Flux Builder : fiche du flux, contrat d'échange JSON, vérification, test, confirmation humaine pour l'envoi | [EXISTANT] | `FluxService`, page Flux, outils `call_flow` |
| FB-02 | Suivi des demandes de flux | [EXISTANT] | `flux_suivi`, table `flux_demandes` |
| MK-01 | Marketplace : onglets Agents, Outils, Flux publiés ; ajout d'un outil ou d'un flux à un agent | [ÉVOLUÉ] (agents déjà présents) | Page Marketplace, Catalogue d'outils |
| MK-02 | Publication de flux Lakeflow Jobs réutilisables dans la Marketplace | [NOUVEAU] | Jobs API [NATIF] |

Le TO-BE proposé par Transformation réutilise en priorité les outils et flux publiés dans la Marketplace ; un outil ou flux manquant ouvre le Tool Builder ou le Flux Builder prérempli.

---

## 7. Indicateurs à définir [À VALIDER]

Aucune cible ni formule n'est officielle tant que le responsable métier ne l'a pas validée.

| Indicateur | Formule proposée | Grain | Source | Limite |
| --- | --- | --- | --- | --- |
| Couverture des cas d'usage | cas d'usage validés ayant ≥ 1 agent ou flux publié / cas d'usage validés | domaine, jour | `transformation_items`, `twin_links` | Dépend de l'exhaustivité des cas d'usage recensés |
| Maturité de transformation | à définir (ex. couverture × part des cas d'usage avec indicateur suivi) | unité, mois | `maturity_assessments` | Formule à arbitrer |
| Taux de succès des outils | appels `succes` / appels | agent, jour | `tool_calls` | Faibles volumes peu significatifs |
| Coût en jetons | somme `total_tokens` | agent, unité, jour | `conversations` (depuis T103) | Sous-agents délégués non comptés aujourd'hui |
| Gain de temps | (temps de départ − temps mesuré) × volume | cas d'usage, mois | `benefit_*` | Exige une situation de départ mesurée |
| Retour sur investissement | gains mesurés / coûts (jetons + DBU + charge) | domaine, trimestre | `benefit_*`, coûts | DBU indisponibles sans tables système |

Règle d'affichage : une valeur estimée est toujours étiquetée « estimation » ; un score moyen n'est jamais affiché sans le nombre d'éléments en échec ou critiques.

---

## 8. Interfaces

Navigation cible (maquette `docs/maquette/DISCOVERY_EIA_maquette.html`) :

| Groupe | Pages |
| --- | --- |
| Entreprise intelligente | Parcours EIA, Enterprise Cockpit, Transformation (Analyse, AS-IS, TO-BE, Écarts, Simulation), Jumeau intelligent, Enterprise Studio, Automation Studio, Agent Mesh |
| Construire | HakimAI, Agent Builder, Mes agents, Équipes, Tool Builder, Flux Builder, Marketplace outils et flux, Chat & Test |
| Gouverner | Validation, Assessment Center, Monitoring, Paramètres |

Les pages existantes sont conservées. Les nouvelles pages ouvrent les pages existantes préremplies plutôt que de dupliquer leurs fonctions.

---

## 9. Règles de gestion transverses

| ID | Règle |
| --- | --- |
| RG-01 | L'assistant agit avec les droits Unity Catalog de l'utilisateur connecté ; un refus d'accès est affiché tel quel. |
| RG-02 | Une recommandation n'est jamais construite sans décision humaine tracée (`decided_by`, `decided_at`). |
| RG-03 | Un agent, une équipe ou un flux n'est utilisable par d'autres qu'après publication validée. |
| RG-04 | Toute action qui écrit ou envoie demande une confirmation humaine à l'exécution. |
| RG-05 | Une modification d'un élément publié repasse par validation (appliqué au chef d'équipe depuis T102). |
| RG-06 | Chaque composante du jumeau, agent et flux a un responsable humain. |
| RG-07 | Aucune suppression physique : archivage ou révocation, avec trace. |
| RG-08 | Les gains et le retour sur investissement ne sont calculés qu'à partir d'une situation de départ validée. |
| RG-09 | Les erreurs techniques (outil, réseau, droits) sont distinguées des résultats métier dans tous les journaux. |
| RG-10 | Un AS-IS généré par HakimAI n'est utilisé pour proposer un TO-BE qu'après confirmation par son responsable. |
| RG-11 | Une organisation cible n'est soumise à validation que si la simulation ne présente aucun contrôle bloquant. |
| RG-12 | Le rejeu en bac à sable n'effectue aucune écriture ni aucun envoi réel. |

---

## 10. Exigences non fonctionnelles

| Thème | Exigence |
| --- | --- |
| Sécurité | OBO pour les données ; compte de l'App limité aux tables de configuration ; isolation par domaine (limite actuelle : DATAOPS_USERS a tous les droits sur `dataops_dev`) |
| Conformité | Accord RGPD pour l'organigramme nominatif ; accord RSSI pour Power Automate et la voix |
| Traçabilité | Journaux existants + décisions de politiques + rattachements du jumeau |
| Performance | Pages du jumeau < 3 s pour quelques centaines d'unités [À VALIDER] |
| Exploitation | Exécution serveur (Databricks App) et locale (PC) |
| Natif d'abord | Jobs, AI/BI, Genie, Knowledge Assistants, Vector Search, MLflow plutôt que des développements spécifiques |

---

## 11. Plan de développement progressif

| Lot | Contenu | Prérequis | Critère de fin |
| --- | --- | --- | --- |
| L0 — Validation | Validation de ce dossier, choix du pilote, sources du jumeau, décisions D1 à D6 | — | Dossier validé et signé |
| L1 — Socle Mesh | Rôles et moteur de politiques en mode audit (T204, T206) | L0 | 0 refus inattendu sur 1 semaine d'usage |
| L2 — Jumeau | `org_units`, `applications`, `twin_links` (processus reportés) ; Enterprise Studio (ES-01 à ES-04) ; import CSV | L0, sources disponibles | Pilote Supply Chain modélisé et validé par son responsable |
| L3 — Transformation | ET-01 à ET-05, ET-08 à ET-11 : AS-IS généré et confirmé, TO-BE, écarts, plan de construction lié ; JI-01 à JI-04 | L2 | AS-IS du pilote confirmé ; 1 recommandation validée → 1 agent construit et publié, lien conservé |
| L3 bis — Simulation | ET-12, SI-01 à SI-05 | L3, L1 (contrôles de politiques) | 1 organisation cible simulée, sans bloquant, soumise et validée |
| L4 — Automation | AS-01 à AS-04 : catalogue unifié, Jobs, rattachement aux cas d'usage ; MK-01 | L2 | 1 flux planifié et 1 flux déclenché par un agent rattachés à un cas d'usage et visibles dans la Marketplace |
| L5 — Cockpit | EC-01 à EC-03 puis EC-04 et EC-05 | L2, L3 ; situation de départ pour EC-04 | Cockpit du pilote recetté ; gains affichés uniquement s'ils sont mesurés |
| L6 — Extension | PTE, UDR ; Mesh multi-niveaux (AM-02 à AM-05) ; marketplace de flux | L1 à L5 | Deux domaines supplémentaires modélisés |

Aucune charge n'est indiquée : elle sera estimée après validation du périmètre (la roadmap Mesh existante chiffre déjà L1 et une partie de L6).

---

## 12. Décisions attendues

| ID | Décision | Options | Recommandation |
| --- | --- | --- | --- |
| D1 | Périmètre entreprise | Mono-entreprise SNCF Réseau / multi-entreprise | Mono-entreprise, modèle extensible |
| D2 | Pilote | Supply Chain Data Quality / autre | Supply Chain Data Quality |
| D3 | Source de l'organigramme | Import CSV / SIRH / saisie manuelle | Import CSV pour le pilote |
| D4 | Processus métier | Reportés / modélisés dès le pilote | **Reportés (décidé le 21/11/2026)** |
| D5 | Ordre des lots | Socle Mesh d'abord / Jumeau d'abord | Socle Mesh (L1) puis Jumeau (L2) |
| D6 | Méthode de mesure des gains | Indicateurs, responsable, situation de départ | À définir avec le responsable du pilote |

## 13. Informations manquantes

- Existence et format d'un organigramme exploitable ; accord RGPD.
- Liste des cas d'usage Supply Chain prioritaires et leur responsable.
- Inventaire des applications du domaine pilote.
- Indicateurs métier suivis aujourd'hui et leur source.
- Responsables de domaine (`domain_owners` est vide).
- Accès aux tables système pour les coûts en DBU.

## 14. Critères de validation du dossier

- Les six piliers et les huit étapes du cycle sont couverts par au moins une fonction.
- Le modèle de simulation SI-01 et la liste des contrôles SI-02 sont acceptés.
- Chaque fonction est classée existant / évolué / nouveau / natif.
- Les règles RG-01 à RG-12 sont acceptées par le Data Office.
- Les décisions D1 à D6 sont prises.
- Le pilote a un responsable métier nommé.
