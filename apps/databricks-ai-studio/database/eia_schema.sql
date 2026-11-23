-- DISCOVERY EIA Core - tables des exécutions HAKIM, alertes, recommandations et missions
-- Schéma : dataops_dev.ai_studio (écriture par le compte de l'application via backend/eia/store.py)
-- Idempotent : CREATE TABLE IF NOT EXISTS. Pas de suppression physique : les objets changent de statut.

-- Grain : 1 ligne par exécution du cycle EIA. Clé : run_id.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.eia_runs (
  run_id STRING NOT NULL COMMENT 'Identifiant (run_ + 12 hex)',
  team_id STRING NOT NULL COMMENT 'Équipe métier (config/teams/<team_id>.json)',
  trigger STRING NOT NULL COMMENT 'demande | planifie | evenement',
  request STRING COMMENT 'Demande de l''utilisateur ou motif du déclenchement',
  requested_by STRING NOT NULL COMMENT 'E-mail de l''utilisateur ou identité du job',
  status STRING NOT NULL COMMENT 'en_cours | termine | partiel | echec',
  plan STRING COMMENT 'Plan d''exécution (JSON : étapes, agents, dépendances)',
  summary STRING COMMENT 'Synthèse consolidée par HAKIM',
  error STRING COMMENT 'Erreur technique éventuelle',
  started_at TIMESTAMP NOT NULL,
  ended_at TIMESTAMP,
  CONSTRAINT eia_runs_pk PRIMARY KEY (run_id)
) COMMENT 'EIA : exécutions du cycle supervisées par HAKIM';

-- Grain : 1 ligne par étape (agent) d'une exécution. Clé : (run_id, step_id).
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.eia_run_steps (
  run_id STRING NOT NULL,
  step_id STRING NOT NULL COMMENT 'Identifiant de l''étape dans le plan',
  agent STRING NOT NULL COMMENT 'analyst | prediction | alerting | advisor | planner',
  status STRING NOT NULL COMMENT 'en_attente | en_cours | reussi | echec | expire | ignore',
  attempts INT COMMENT 'Nombre de tentatives (reprises incluses)',
  depends_on STRING COMMENT 'JSON : étapes amont',
  output STRING COMMENT 'JSON : AgentResult (constats, prévisions, alertes, recommandations)',
  issues STRING COMMENT 'JSON : écarts au contrat détectés par HAKIM',
  error STRING COMMENT 'Erreur technique éventuelle',
  started_at TIMESTAMP,
  ended_at TIMESTAMP,
  duration_ms INT,
  CONSTRAINT eia_run_steps_pk PRIMARY KEY (run_id, step_id),
  CONSTRAINT eia_run_steps_run_fk FOREIGN KEY (run_id) REFERENCES dataops_dev.ai_studio.eia_runs
) COMMENT 'EIA : étapes des exécutions (un agent par étape)';

-- Grain : 1 ligne par alerte dédoublonnée (empreinte équipe + règle + périmètre + période). Clé : alert_id.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.eia_alerts (
  alert_id STRING NOT NULL COMMENT 'Identifiant (al_ + 12 hex)',
  team_id STRING NOT NULL,
  run_id STRING COMMENT 'Dernière exécution ayant détecté l''alerte',
  rule_id STRING NOT NULL COMMENT 'Règle de la configuration d''équipe',
  rule_status STRING NOT NULL COMMENT 'Statut de validation métier de la règle : a_valider | valide',
  kind STRING NOT NULL COMMENT 'metier | technique (jamais mélangés)',
  severity STRING NOT NULL COMMENT 'info | attention | critique',
  title STRING NOT NULL,
  message STRING,
  metric STRING COMMENT 'KPI concerné',
  scope STRING COMMENT 'Dimension concernée (ex. région), vide = global',
  period STRING COMMENT 'Période évaluée',
  observed DOUBLE COMMENT 'Valeur observée',
  threshold DOUBLE COMMENT 'Seuil franchi',
  evidence STRING COMMENT 'JSON : outil, source et requête ayant produit la valeur',
  fingerprint STRING NOT NULL COMMENT 'Empreinte de dédoublonnage',
  status STRING NOT NULL COMMENT 'nouvelle | vue | acquittee | resolue',
  occurrences INT NOT NULL COMMENT 'Nombre de détections de la même alerte non résolue',
  first_seen_at TIMESTAMP NOT NULL,
  last_seen_at TIMESTAMP NOT NULL,
  decided_by STRING COMMENT 'Utilisateur ayant changé le statut',
  decided_at TIMESTAMP,
  CONSTRAINT eia_alerts_pk PRIMARY KEY (alert_id)
) COMMENT 'EIA : alertes internes (notifications DISCOVERY), dédoublonnées par empreinte';

-- Grain : 1 ligne par recommandation proposée. Clé : reco_id.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.eia_recommendations (
  reco_id STRING NOT NULL COMMENT 'Identifiant (rc_ + 12 hex)',
  team_id STRING NOT NULL,
  run_id STRING NOT NULL COMMENT 'Exécution d''origine -> eia_runs',
  title STRING NOT NULL,
  rationale STRING NOT NULL COMMENT 'Justification fondée sur les preuves',
  priority INT NOT NULL COMMENT '1 = la plus prioritaire',
  based_on STRING NOT NULL COMMENT 'JSON : identifiants des constats, prévisions et alertes cités',
  expected_impact STRING COMMENT 'Impact estimé uniquement s''il est calculé à partir des données',
  assumptions STRING COMMENT 'JSON : hypothèses',
  risks STRING COMMENT 'JSON : risques',
  status STRING NOT NULL COMMENT 'proposee | selectionnee | validee | rejetee',
  created_at TIMESTAMP NOT NULL,
  decided_by STRING,
  decided_at TIMESTAMP,
  decision_note STRING,
  CONSTRAINT eia_recommendations_pk PRIMARY KEY (reco_id)
) COMMENT 'EIA : recommandations de l''Advisor Agent et décisions de l''utilisateur';

-- Grain : 1 ligne par mission. Clé : mission_id. Toujours créée en brouillon, validee seulement par un utilisateur.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.eia_missions (
  mission_id STRING NOT NULL COMMENT 'Identifiant (ms_ + 12 hex)',
  team_id STRING NOT NULL,
  reco_id STRING NOT NULL COMMENT 'Recommandation d''origine -> eia_recommendations',
  title STRING NOT NULL,
  objective STRING NOT NULL,
  owner STRING COMMENT 'Responsable proposé (rôle ou personne, à confirmer)',
  due_date STRING COMMENT 'Échéance proposée (AAAA-MM-JJ)',
  deliverables STRING COMMENT 'JSON : livrables',
  success_kpis STRING NOT NULL COMMENT 'JSON : KPI de réussite (identifiants de la configuration d''équipe)',
  status STRING NOT NULL COMMENT 'brouillon | validee | en_cours | terminee | annulee',
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  validated_by STRING COMMENT 'Utilisateur ayant validé la mission',
  validated_at TIMESTAMP,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT eia_missions_pk PRIMARY KEY (mission_id),
  CONSTRAINT eia_missions_reco_fk FOREIGN KEY (reco_id) REFERENCES dataops_dev.ai_studio.eia_recommendations
) COMMENT 'EIA : missions (Mission Center), issues de recommandations sélectionnées';

-- Grain : 1 ligne par tâche de mission. Clé : (mission_id, task_id).
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.eia_mission_tasks (
  mission_id STRING NOT NULL,
  task_id STRING NOT NULL COMMENT 'Identifiant (mt_ + 12 hex)',
  title STRING NOT NULL,
  owner STRING COMMENT 'Responsable proposé',
  due_date STRING COMMENT 'Échéance proposée (AAAA-MM-JJ)',
  deliverable STRING,
  depends_on STRING COMMENT 'JSON : tâches préalables',
  status STRING NOT NULL COMMENT 'a_faire | en_cours | fait | bloque | annule',
  updated_by STRING,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT eia_mission_tasks_pk PRIMARY KEY (mission_id, task_id),
  CONSTRAINT eia_mission_tasks_mission_fk FOREIGN KEY (mission_id) REFERENCES dataops_dev.ai_studio.eia_missions
) COMMENT 'EIA : tâches des missions';

-- Grain : 1 ligne par événement (journal immuable, ajout seul). Clé : event_id.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.eia_events (
  event_id STRING NOT NULL,
  object_type STRING NOT NULL COMMENT 'run | alert | recommendation | mission | task',
  object_id STRING NOT NULL,
  event_type STRING NOT NULL COMMENT 'Création ou nouveau statut',
  actor STRING NOT NULL COMMENT 'Utilisateur ou agent',
  payload STRING COMMENT 'JSON : détails',
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT eia_events_pk PRIMARY KEY (event_id)
) COMMENT 'EIA : journal des décisions et changements de statut (traçabilité)';
