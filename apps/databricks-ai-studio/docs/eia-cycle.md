# DISCOVERY — Cycle EIA supervisé par HAKIM

## Périmètre

Le cœur EIA est en Python indépendant de Databricks et de Streamlit. Les six rôles sont des fonctions
calculatoires déterministes ; HAKIM reste le seul superviseur IA pour expliquer les sorties et interagir
avec l'utilisateur. Il n'y a ni second orchestrateur de modèles ni agents prenant des décisions métier seuls.

Les règles, KPI, sources, compétences, pondérations et plans d'action sont dans la configuration d'équipe.
Sales utilise les données fictives Horizon Équipements. Ce lot ne crée aucune règle officielle SNCF Réseau
et ne modifie pas les sources Supply Chain/PTE/UDR. Les six plans d'action Sales, leurs charges et délais
sont des propositions de démonstration, statut `a_valider`, à revoir par les responsables métier.

## Cycle et points de décision

| Phase | Composant | Résultat | Décision humaine |
| --- | --- | --- | --- |
| PERCEIVE | analyst | Dernières valeurs des KPI, périodes et preuves d'outil | Contrats/KPI à valider par l'équipe |
| UNDERSTAND | alerting, advisor | Alertes métier séparées des erreurs techniques, recommandations liées aux alertes | Seuils et plans d'action non officiels tant que non validés |
| PREDICT | prediction | Prévisions avec méthode, backtest et avertissement de fiabilité | Interprétation assistée, aucune certitude inventée |
| PLAN | planner, staffing | Aperçus de tâches, dépendances, compétences, charges et candidats | Choix explicite de la recommandation |
| ACT | prepare_mission, suivi | Mission brouillon, affectations proposées, progression contrôlée | Sélection, validation de mission, confirmation d'affectation et clôture distinctes |
| LEARN | learn_mission | Bilan après clôture, variations par KPI/dimension contre référence figée | Acceptation du bilan, arbitrage et évolution des règles hors automatisme |

L'ordre calculatoire est analyst → prediction → alerting → advisor → planner → staffing. Les observations
sont historisées dans le cycle persistant. ACT/LEARN peuvent être différés de plusieurs jours : le cycle
ne prétend jamais avoir exécuté une action commerciale simplement parce qu'il a produit un plan.

## Outils intégrés au catalogue et à HAKIM

* `eia_apercu_cycle` : lecture des KPI et du personnel ; stockage des résultats uniquement en mémoire.
  Ses identifiants sont temporaires et ne servent pas à créer une mission persistante.
* `eia_cycle` : après confirmation runtime, journalise l'exécution, ses étapes, alertes et recommandations
  proposées. Aucun brouillon de mission créé par ce seul appel.
* `eia_preparer_mission` : après sélection humaine explicite d'une recommandation persistante et confirmation,
  crée le brouillon, ses tâches et des candidats d'affectation. Renvoie les identifiants nécessaires au suivi.
* `eia_suivi_mission` : décision humaine confirmée sur mission, tâche ou affectation ; vérifie appartenance
  à l'équipe/mission et transition. Interdit la clôture avec tâches ouvertes. La confirmation d'affectation
  exige une mission déjà validée.
* `eia_bilan_mission` : lecture seule ; avancement puis, après clôture, comparaison aux KPI de référence.

Les trois outils persistants sont `read_only=False`, `requires_confirmation=True`. Les deux autres sont
`read_only=True`. L'identité de décision vient du contexte connecté, jamais d'un argument choisi par le modèle.
Les droits Unity Catalog de l'utilisateur s'appliquent ; aucun usage implicite du service principal.
L'identification de l'utilisateur et sa confirmation ne remplacent pas une matrice métier d'habilitation :
les rôles autorisés et les droits d'écriture doivent être configurés par les responsables du projet.

## Traçabilité

* `eia_runs` : un cycle, version de configuration et plan calculatoire.
* `eia_run_steps` : six étapes, statut, durée, sortie conforme au contrat et erreurs.
* `eia_alerts` : règle, valeur, seuil, période, preuve, empreinte et occurrences pour les alertes répétées.
* `eia_recommendations` : preuves référencées, priorité, hypothèses, statut initial proposé ; référence du
  plan d'action conservée dans les hypothèses.
* `eia_missions`, `eia_mission_tasks` : brouillon lié à la recommandation, dépendances internes, compétences,
  heures et dates absolues. Ces tables ne sont alimentées qu'après sélection confirmée.
* `eia_assignments` : candidats proposés, rang, scores, lacunes ; aucune confirmation automatique.
* `eia_events` : observations du cycle, décisions, référence initiale des KPI et planification.

Aucune migration de schéma n'est nécessaire pour ce lot : les sorties et références supplémentaires utilisent
les champs JSON et les tables EIA existants. La suite valide le contrat en mémoire ; la compatibilité en
exécution SQL et les droits de l'App restent à vérifier lors de la recette réelle.

## Bilan LEARN et limites d'interprétation

La référence initiale est figée à la préparation du brouillon, avec preuves et version de configuration.
Après clôture humaine, le bilan compare la dernière observation de chaque KPI/dimension à cette référence.
Pour un taux en %, l'écart est en points ; aucun taux n'est moyenné entre dimensions. Aucun gain commercial
n'est déduit d'un simple changement observé.

Un KPI sans nouvelle période, une dimension manquante, une unité différente ou une version incompatible
est non évaluable. Une mission non terminée ne reçoit pas de bilan d'efficacité. Les versions doivent être
incrémentées dès que la définition d'un KPI ou sa configuration change ; ce lot compare les versions et
ne détecte pas une modification qui aurait laissé le numéro de version inchangé. Comparer deux périodes
ne prouve aucune causalité et ne valide pas automatiquement l'atteinte d'un objectif métier.

La disponibilité est estimée à partir de la capacité hebdomadaire, du pourcentage de disponibilité et de la
charge confirmée. Les simulations de missions sont alternatives et indépendantes les unes des autres ;
dans une mission, le premier candidat hypothétique réduit sa disponibilité pour les tâches suivantes.
Ce n'est pas un solveur de planning : calendrier réel, congés, contraintes locales et déficit de compétences
restent à vérifier. Une disponibilité partielle peut apparaître dans les candidats et requiert un arbitrage.

## Exploitation et limites techniques

* Une lecture par KPI est partagée entre les rôles du même cycle, y compris un échec de lecture.
* Les erreurs d'agent sont techniques et ne se transforment jamais en alertes métier.
* Le budget temporel est coopératif entre étapes ; il n'interrompt pas une requête SQL déjà lancée.
* Une erreur de lecture RH conserve les constats et recommandations des autres étapes, avec cycle partiel.
* Une relance de préparation renvoie le brouillon existant, sans duplication en exécution séquentielle normale.
  Les écritures multi-tables ne sont pas transactionnelles : concurrence et panne pendant la création
  nécessitent un contrôle/reprise technique. Ce lot ne garantit pas l'exactly-once concurrent.
* Aucun nouvel appel Power Automate : les notifications externes restent dans le moteur d'alerting existant,
  sous sa configuration validée. Aucun destinataire ni déclencheur externe n'est inventé.
* Les nouvelles pages Streamlit Missions/Notifications ne sont pas ajoutées ici : les actions sont exposées
  dans HAKIM et le catalogue, côté source. Pas de commit, push ou déploiement dans ce lot.

## Recette

`tests/test_eia_cycle.py` couvre le cycle sur données synthétiques connues : preuves, prévisions, cache,
dédoublonnage des alertes, erreurs de source/RH, échéances et dépendances, création du brouillon, refus d'un
acteur agent, confirmation d'affectation après validation, bilan sans mutation, périmètre équipe, absence
de notification, et confirmations runtime distinctes.

La suite complète de l'App a été exécutée : 513 tests réussis, dont 25 nouveaux cas EIA ; 7 avertissements
préexistants concernent `datetime.utcnow` dans l'export Excel. Aucun cycle ni mission du nouveau moteur n'a
été exécuté sur les tables réelles. La recette App/SQL sous l'identité utilisateur reste distincte des tests.
