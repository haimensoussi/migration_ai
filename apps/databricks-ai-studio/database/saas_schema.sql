-- DISCOVERY AI Studio - SaaS multi-entreprises : tables de configuration partagées (isolation hybride).
-- Grain et clés indiqués en commentaire. Les données métier et documents d'une entreprise vont dans son
-- schéma dédié (saas_tenants.data_schema), jamais dans ces tables.
-- Écrites uniquement par le service principal de l'App via backend/saas (contrôles côté serveur).
-- Idempotent : CREATE TABLE IF NOT EXISTS + MERGE des rôles.

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_tenants (
  tenant_id STRING NOT NULL COMMENT 'Identifiant technique de l entreprise (32 hex)',
  slug STRING NOT NULL COMMENT 'Code court unique (a-z, 0-9, _), sert au nom du schéma dédié',
  name STRING NOT NULL COMMENT 'Raison sociale affichée',
  status STRING NOT NULL COMMENT 'actif | suspendu',
  plan STRING COMMENT 'Offre souscrite (essai | standard | entreprise)',
  admin_email STRING NOT NULL COMMENT 'Premier propriétaire (rôle owner)',
  data_schema STRING NOT NULL COMMENT 'Schéma Unity Catalog dédié aux données de l entreprise',
  data_schema_status STRING NOT NULL COMMENT 'a_provisionner | provisionne',
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_tenants_pk PRIMARY KEY (tenant_id)
) COMMENT 'Entreprises clientes (grain : 1 ligne par entreprise)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_roles (
  role_id STRING NOT NULL COMMENT 'owner | admin | builder | user | viewer',
  name STRING NOT NULL,
  rank INT NOT NULL COMMENT 'Niveau hiérarchique (plus grand = plus de droits)',
  permissions STRING NOT NULL COMMENT 'Liste JSON des permissions',
  description STRING,
  CONSTRAINT saas_roles_pk PRIMARY KEY (role_id)
) COMMENT 'Rôles applicatifs communs à toutes les entreprises (référence, grain : 1 ligne par rôle)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_users (
  tenant_id STRING NOT NULL,
  user_email STRING NOT NULL COMMENT 'Identité vérifiée (userName Databricks, minuscules)',
  role_id STRING NOT NULL,
  status STRING NOT NULL COMMENT 'actif | desactive',
  added_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_users_pk PRIMARY KEY (tenant_id, user_email)
) COMMENT 'Appartenance des utilisateurs aux entreprises (grain : 1 ligne par entreprise et utilisateur)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_settings (
  tenant_id STRING NOT NULL,
  setting_key STRING NOT NULL,
  setting_value STRING COMMENT 'Valeur JSON',
  updated_by STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_settings_pk PRIMARY KEY (tenant_id, setting_key)
) COMMENT 'Paramètres par entreprise (grain : 1 ligne par entreprise et clé)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_agents (
  tenant_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  version INT NOT NULL,
  name STRING NOT NULL,
  status STRING NOT NULL COMMENT 'brouillon | publie | archive',
  config STRING COMMENT 'Configuration JSON (instructions, modèle, outils, connaissances)',
  source_agent_id STRING COMMENT 'Agent de la marketplace installé, le cas échéant',
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_agents_pk PRIMARY KEY (tenant_id, agent_id, version)
) COMMENT 'Agents d une entreprise (grain : 1 ligne par agent et version)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_connectors (
  tenant_id STRING NOT NULL,
  connector_id STRING NOT NULL,
  connector_type STRING NOT NULL COMMENT 'uc_table | http | power_automate | ...',
  name STRING NOT NULL,
  config STRING COMMENT 'Configuration JSON sans secret',
  secret_ref STRING COMMENT 'Référence scope/clé de secret, jamais la valeur',
  status STRING NOT NULL,
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_connectors_pk PRIMARY KEY (tenant_id, connector_id)
) COMMENT 'Connecteurs d une entreprise (grain : 1 ligne par connecteur)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_tools (
  tenant_id STRING NOT NULL,
  tool_id STRING NOT NULL,
  version STRING NOT NULL,
  status STRING NOT NULL COMMENT 'installe | desactive',
  config STRING COMMENT 'Paramètres JSON propres à l entreprise',
  installed_by STRING NOT NULL,
  installed_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_tools_pk PRIMARY KEY (tenant_id, tool_id)
) COMMENT 'Actions de la marketplace installées par une entreprise (grain : 1 ligne par entreprise et action)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_workflows (
  tenant_id STRING NOT NULL,
  workflow_id STRING NOT NULL,
  name STRING NOT NULL,
  workflow_type STRING NOT NULL,
  config STRING COMMENT 'Configuration JSON sans secret',
  status STRING NOT NULL,
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_workflows_pk PRIMARY KEY (tenant_id, workflow_id)
) COMMENT 'Workflows d une entreprise (grain : 1 ligne par workflow)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_conversations (
  tenant_id STRING NOT NULL,
  conversation_id STRING NOT NULL,
  agent_id STRING,
  user_email STRING NOT NULL,
  title STRING,
  messages STRING COMMENT 'Messages JSON',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_conversations_pk PRIMARY KEY (tenant_id, conversation_id)
) COMMENT 'Conversations (grain : 1 ligne par conversation)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_executions (
  tenant_id STRING NOT NULL,
  execution_id STRING NOT NULL,
  execution_type STRING NOT NULL COMMENT 'agent | outil | workflow',
  ref_id STRING,
  user_email STRING NOT NULL,
  status STRING NOT NULL COMMENT 'en_cours | succes | erreur | refuse',
  started_at TIMESTAMP NOT NULL,
  ended_at TIMESTAMP,
  error STRING,
  details STRING COMMENT 'JSON',
  CONSTRAINT saas_executions_pk PRIMARY KEY (tenant_id, execution_id)
) COMMENT 'Exécutions (grain : 1 ligne par exécution)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_usage (
  tenant_id STRING NOT NULL,
  usage_id STRING NOT NULL,
  usage_date DATE NOT NULL,
  user_email STRING,
  agent_id STRING,
  model STRING,
  metric STRING NOT NULL COMMENT 'tokens_entree | tokens_sortie | requetes_sql | ...',
  quantity DOUBLE NOT NULL,
  recorded_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_usage_pk PRIMARY KEY (tenant_id, usage_id)
) COMMENT 'Consommation mesurée par l application (grain : 1 ligne par mesure)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.saas_audit_logs (
  audit_id STRING NOT NULL,
  tenant_id STRING COMMENT 'NULL pour une action de plateforme',
  actor_email STRING NOT NULL,
  action STRING NOT NULL,
  target_type STRING,
  target_id STRING,
  outcome STRING NOT NULL COMMENT 'succes | refuse | erreur',
  details STRING COMMENT 'JSON sans secret',
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT saas_audit_logs_pk PRIMARY KEY (audit_id)
) COMMENT 'Journal d audit append-only (grain : 1 ligne par action, refus inclus)';

MERGE INTO dataops_dev.ai_studio.saas_roles t
USING (SELECT * FROM VALUES
  ('owner', 'Propriétaire', 50, '["tenant.read","tenant.manage","users.read","users.manage","settings.read","settings.manage","agents.read","agents.manage","agents.use","audit.read"]', 'Tous les droits sur l entreprise'),
  ('admin', 'Administrateur', 40, '["tenant.read","users.read","users.manage","settings.read","settings.manage","agents.read","agents.manage","agents.use","audit.read"]', 'Administre utilisateurs, paramètres et agents'),
  ('builder', 'Concepteur', 30, '["tenant.read","users.read","settings.read","agents.read","agents.manage","agents.use"]', 'Conçoit et teste les agents'),
  ('user', 'Utilisateur', 20, '["tenant.read","agents.read","agents.use"]', 'Utilise les agents publiés'),
  ('viewer', 'Lecteur', 10, '["tenant.read","agents.read"]', 'Consultation seule')
  AS v(role_id, name, rank, permissions, description)) s
ON t.role_id = s.role_id
WHEN MATCHED THEN UPDATE SET name = s.name, rank = s.rank, permissions = s.permissions, description = s.description
WHEN NOT MATCHED THEN INSERT *;
