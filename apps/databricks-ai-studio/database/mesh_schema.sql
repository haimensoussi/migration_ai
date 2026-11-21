-- DISCOVERY Agent Mesh : fondation organisationnelle, rôles et politiques (roadmap T201, T204, T206).
-- Catalogue existant dataops_dev (décision du 2026-11-21 : pas de catalogue dédié). Script idempotent.
-- Les tables teams / team_members (équipes d'AGENTS) ne sont pas renommées : les équipes HUMAINES
-- sont dans user_teams / user_team_members.

-- T201 : organisation -------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.organizations (
  org_id STRING NOT NULL COMMENT 'Identifiant (code court)',
  name STRING NOT NULL,
  status STRING NOT NULL COMMENT 'actif | archive',
  created_by STRING NOT NULL, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL,
  CONSTRAINT organizations_pk PRIMARY KEY (org_id)
) COMMENT 'Agent Mesh T201 : organisations (grain : 1 ligne par organisation)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.domains (
  domain_id STRING NOT NULL COMMENT 'Identifiant (code court, ex. supply_chain)',
  org_id STRING NOT NULL COMMENT 'Organisation -> organizations',
  name STRING NOT NULL COMMENT 'Libellé utilisé dans les fiches contrat (agent_contracts.domaine)',
  description STRING,
  status STRING NOT NULL COMMENT 'actif | archive',
  created_by STRING NOT NULL, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL,
  CONSTRAINT domains_pk PRIMARY KEY (domain_id),
  CONSTRAINT domains_org_fk FOREIGN KEY (org_id) REFERENCES dataops_dev.ai_studio.organizations
) COMMENT 'Agent Mesh T201 : domaines métier (grain : 1 ligne par domaine)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.users (
  email STRING NOT NULL COMMENT 'E-mail en minuscules (identité Databricks)',
  display_name STRING,
  org_id STRING COMMENT 'Organisation -> organizations',
  status STRING NOT NULL COMMENT 'actif | inactif',
  source STRING NOT NULL COMMENT 'connexion (première utilisation) | manuel (administrateur)',
  first_seen_at TIMESTAMP NOT NULL, last_seen_at TIMESTAMP NOT NULL,
  CONSTRAINT users_pk PRIMARY KEY (email)
) COMMENT 'Agent Mesh T201 : utilisateurs connus de DISCOVERY (grain : 1 ligne par utilisateur)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.user_teams (
  user_team_id STRING NOT NULL COMMENT 'Identifiant (32 hex)',
  domain_id STRING NOT NULL COMMENT 'Domaine -> domains',
  name STRING NOT NULL,
  description STRING,
  status STRING NOT NULL COMMENT 'actif | archive',
  owner STRING NOT NULL,
  created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL,
  CONSTRAINT user_teams_pk PRIMARY KEY (user_team_id),
  CONSTRAINT user_teams_domain_fk FOREIGN KEY (domain_id) REFERENCES dataops_dev.ai_studio.domains
) COMMENT 'Agent Mesh T201 : équipes HUMAINES par domaine (≠ teams = équipes d''agents)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.user_team_members (
  user_team_id STRING NOT NULL COMMENT 'Équipe -> user_teams',
  email STRING NOT NULL COMMENT 'Utilisateur -> users',
  role_in_team STRING NOT NULL COMMENT 'membre | responsable',
  added_by STRING NOT NULL, added_at TIMESTAMP NOT NULL,
  CONSTRAINT user_team_members_pk PRIMARY KEY (user_team_id, email)
) COMMENT 'Agent Mesh T201 : appartenance aux équipes humaines (grain : 1 ligne par équipe et utilisateur)';

-- T204 : rôles --------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.role_assignments (
  assignment_id STRING NOT NULL COMMENT 'Identifiant (32 hex)',
  principal_type STRING NOT NULL COMMENT 'user | all (tout utilisateur authentifié)',
  principal STRING NOT NULL COMMENT 'E-mail en minuscules, ou * pour all',
  role STRING NOT NULL COMMENT 'platform_admin | domain_admin | domain_validator | agent_developer | agent_user | auditor',
  scope_type STRING NOT NULL COMMENT 'platform | domain',
  scope_id STRING COMMENT 'domain_id si scope_type = domain',
  status STRING NOT NULL COMMENT 'actif | revoque',
  granted_by STRING NOT NULL, granted_at TIMESTAMP NOT NULL,
  revoked_by STRING, revoked_at TIMESTAMP,
  CONSTRAINT role_assignments_pk PRIMARY KEY (assignment_id)
) COMMENT 'Agent Mesh T204 : attributions de rôles (grain : 1 ligne par attribution ; jamais supprimée, révoquée)';

-- T206 : politiques ---------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.agent_policies (
  policy_id STRING NOT NULL,
  name STRING NOT NULL,
  description STRING,
  effect STRING NOT NULL COMMENT 'allow | deny (deny l''emporte)',
  actions STRING NOT NULL COMMENT 'JSON : liste de motifs d''action (ex. ["tool.invoke"], ["*"])',
  roles STRING NOT NULL COMMENT 'JSON : rôles concernés ([] = tous)',
  resources STRING NOT NULL COMMENT 'JSON : motifs type:id (ex. ["tool:*"], ["tool:agent:*"])',
  conditions STRING NOT NULL COMMENT 'JSON : status_in, owner_is_principal, read_only, domain_in',
  priority INT NOT NULL COMMENT 'Ordre d''évaluation (petit = prioritaire)',
  status STRING NOT NULL COMMENT 'actif | inactif',
  created_by STRING NOT NULL, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL,
  CONSTRAINT agent_policies_pk PRIMARY KEY (policy_id)
) COMMENT 'Agent Mesh T206 : politiques d''accès (refus par défaut si aucune politique allow ne correspond)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.policy_decisions (
  decision_id STRING NOT NULL,
  decided_at TIMESTAMP NOT NULL,
  principal STRING NOT NULL,
  action STRING NOT NULL,
  resource STRING NOT NULL COMMENT 'type:id',
  allowed BOOLEAN NOT NULL COMMENT 'Résultat de l''évaluation',
  enforced BOOLEAN NOT NULL COMMENT 'Vrai si l''action a réellement été bloquée (mode enforce)',
  mode STRING NOT NULL COMMENT 'audit | enforce',
  policy_id STRING COMMENT 'Politique déterminante (vide : refus par défaut ou moteur indisponible)',
  reason STRING,
  agent_id STRING, conversation_id STRING,
  CONSTRAINT policy_decisions_pk PRIMARY KEY (decision_id)
) COMMENT 'Agent Mesh T206 : journal des décisions (refus toujours ; autorisations si journalisation complète)';

-- Données initiales : reprennent l'existant (aucun objet ni seuil inventé) ---------------------------
-- Organisation et domaines = liste DOMAINES de backend/agent_contracts.py
MERGE INTO dataops_dev.ai_studio.organizations d USING (SELECT 'sncf_reseau' AS org_id) s ON d.org_id = s.org_id
WHEN NOT MATCHED THEN INSERT (org_id, name, status, created_by, created_at, updated_at)
  VALUES ('sncf_reseau', 'SNCF Réseau', 'actif', 'mesh_schema.sql', current_timestamp(), current_timestamp());

MERGE INTO dataops_dev.ai_studio.domains d
USING (SELECT * FROM VALUES ('supply_chain', 'Supply Chain'), ('pte', 'PTE'), ('udr', 'UDR'), ('transverse', 'Transverse')
       AS v(domain_id, name)) s ON d.domain_id = s.domain_id
WHEN NOT MATCHED THEN INSERT (domain_id, org_id, name, description, status, created_by, created_at, updated_at)
  VALUES (s.domain_id, 'sncf_reseau', s.name, NULL, 'actif', 'mesh_schema.sql', current_timestamp(), current_timestamp());

-- Rôles : tout utilisateur authentifié = agent_user (comportement actuel) ; administrateurs = AI_STUDIO_TOOL_ADMINS
MERGE INTO dataops_dev.ai_studio.role_assignments d
USING (SELECT * FROM VALUES
         ('seed-all-agent-user', 'all', '*', 'agent_user'),
         ('seed-admin-phsi10251', 'user', 'phsi10251@commun.ad.sncf.fr', 'platform_admin')
       AS v(assignment_id, principal_type, principal, role)) s ON d.assignment_id = s.assignment_id
WHEN NOT MATCHED THEN INSERT (assignment_id, principal_type, principal, role, scope_type, scope_id, status, granted_by,
                              granted_at)
  VALUES (s.assignment_id, s.principal_type, s.principal, s.role, 'platform', NULL, 'actif', 'mesh_schema.sql',
          current_timestamp());

-- Politiques de base : reproduisent les règles actuelles (le mode audit doit donc relever 0 refus en usage normal)
MERGE INTO dataops_dev.ai_studio.agent_policies d
USING (SELECT * FROM VALUES
  ('POL-001', 'Administrateurs plateforme', 'Les administrateurs DISCOVERY peuvent tout faire.', 'allow',
   '["*"]', '["platform_admin"]', '["*"]', '{}', 100),
  ('POL-002', 'Outils publiés', 'Tout utilisateur peut faire appeler par un agent un outil publié (confirmation humaine inchangée).',
   'allow', '["tool.invoke"]', '["agent_user"]', '["tool:*"]', '{"status_in": ["publie"]}', 200),
  ('POL-003', 'Outils de son propriétaire', 'Le propriétaire d''un outil créé peut l''exécuter en brouillon.',
   'allow', '["tool.invoke"]', '[]', '["tool:*"]', '{"owner_is_principal": true}', 210),
  ('POL-004', 'Outils retirés', 'Un outil retiré n''est jamais exécuté.', 'deny',
   '["tool.invoke"]', '[]', '["tool:*"]', '{"status_in": ["retire"]}', 10)
  AS v(policy_id, name, description, effect, actions, roles, resources, conditions, priority)) s
ON d.policy_id = s.policy_id
WHEN NOT MATCHED THEN INSERT (policy_id, name, description, effect, actions, roles, resources, conditions, priority, status,
                              created_by, created_at, updated_at)
  VALUES (s.policy_id, s.name, s.description, s.effect, s.actions, s.roles, s.resources, s.conditions, s.priority, 'actif',
          'mesh_schema.sql', current_timestamp(), current_timestamp());
