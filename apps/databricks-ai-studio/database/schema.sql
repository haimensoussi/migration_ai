-- Databricks AI Studio - schéma Unity Catalog du MVP
-- Catalogue/schéma : dataops_dev.ai_studio (modifiable : remplacer le préfixe)

CREATE SCHEMA IF NOT EXISTS dataops_dev.ai_studio
COMMENT 'Databricks AI Studio : configurations des agents, catalogue d''outils, historique des conversations et des appels d''outils';

-- Grain : 1 ligne par agent. Clé : agent_id.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.agents (
  agent_id STRING NOT NULL COMMENT 'Identifiant unique (uuid hex)',
  name STRING NOT NULL COMMENT 'Nom affiché',
  description STRING COMMENT 'Description fonctionnelle',
  icon STRING COMMENT 'Icône (emoji ou code Material)',
  category STRING COMMENT 'Catégorie métier',
  status STRING NOT NULL COMMENT 'brouillon | publie | archive',
  current_version INT NOT NULL COMMENT 'Version active (agent_versions.version)',
  owner STRING NOT NULL COMMENT 'E-mail du propriétaire',
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT agents_pk PRIMARY KEY (agent_id)
) COMMENT 'Agents créés dans AI Studio (en-tête, statut de publication)';

-- Grain : 1 ligne par version de configuration (immuable). Clé : (agent_id, version).
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.agent_versions (
  agent_id STRING NOT NULL,
  version INT NOT NULL,
  model_endpoint STRING NOT NULL COMMENT 'Endpoint Model Serving (tâche llm/v1/chat)',
  instructions STRING NOT NULL COMMENT 'Prompt système',
  tool_ids STRING NOT NULL COMMENT 'Liste JSON des tool_id autorisés',
  knowledge_tables STRING NOT NULL COMMENT 'Liste JSON des tables catalog.schema.table autorisées',
  temperature DOUBLE,
  max_iterations INT COMMENT 'Nombre maximal de tours outil/modèle',
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT agent_versions_pk PRIMARY KEY (agent_id, version),
  CONSTRAINT agent_versions_agent_fk FOREIGN KEY (agent_id) REFERENCES dataops_dev.ai_studio.agents
) COMMENT 'Versions immuables des configurations d''agents';

-- Grain : 1 ligne par outil. Clé : tool_id. L'exécuteur Python est référencé par 'executor'.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.tools (
  tool_id STRING NOT NULL,
  name STRING NOT NULL,
  category STRING NOT NULL,
  description STRING NOT NULL COMMENT 'Description donnée au modèle',
  input_schema STRING NOT NULL COMMENT 'JSON Schema des arguments',
  output_schema STRING NOT NULL COMMENT 'JSON Schema du résultat',
  executor STRING NOT NULL COMMENT 'module:fonction Python',
  identity STRING NOT NULL COMMENT 'utilisateur | application : identité d''exécution',
  requires_confirmation BOOLEAN NOT NULL COMMENT 'Validation humaine avant exécution',
  read_only BOOLEAN NOT NULL,
  status STRING NOT NULL COMMENT 'publie | planifie | indisponible',
  version STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  CONSTRAINT tools_pk PRIMARY KEY (tool_id)
) COMMENT 'Tool Catalog : métadonnées et contrats des outils exécutables';

-- Grain : 1 ligne par message. Clé : (conversation_id, message_index).
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.conversations (
  conversation_id STRING NOT NULL,
  message_index INT NOT NULL,
  agent_id STRING NOT NULL,
  agent_version INT NOT NULL,
  user_name STRING NOT NULL,
  role STRING NOT NULL COMMENT 'user | assistant | tool',
  content STRING,
  latency_ms BIGINT COMMENT 'Durée du tour (messages assistant)',
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT conversations_pk PRIMARY KEY (conversation_id, message_index)
) COMMENT 'Historique des conversations (tests et usage)';

-- Grain : 1 ligne par appel d'outil. Clé : call_id.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.tool_calls (
  call_id STRING NOT NULL,
  conversation_id STRING NOT NULL,
  agent_id STRING NOT NULL,
  tool_id STRING NOT NULL,
  arguments STRING COMMENT 'Arguments JSON',
  status STRING NOT NULL COMMENT 'succes | erreur | refuse',
  result_preview STRING COMMENT 'Extrait du résultat (4000 caractères max)',
  error STRING,
  duration_ms BIGINT,
  user_name STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT tool_calls_pk PRIMARY KEY (call_id)
) COMMENT 'Journal des appels d''outils (monitoring, audit)';

-- Grain : 1 ligne par génération assistée par IA (agent, puis outils). Clé : generation_id.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.generation_log (
  generation_id STRING NOT NULL,
  kind STRING NOT NULL COMMENT 'agent | outil',
  user_name STRING NOT NULL,
  prompt STRING NOT NULL COMMENT 'Demande en langage naturel',
  scope STRING COMMENT 'Périmètre de données suggéré',
  model_endpoint STRING NOT NULL,
  proposal STRING COMMENT 'Proposition brute du modèle (JSON)',
  draft STRING COMMENT 'Brouillon validé (JSON)',
  warnings STRING COMMENT 'Avertissements de validation (JSON)',
  status STRING NOT NULL COMMENT 'propose | erreur',
  error STRING,
  latency_ms BIGINT,
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT generation_log_pk PRIMARY KEY (generation_id)
) COMMENT 'Traçabilité des générations du copilote de conception';


-- Outils créés dans DISCOVERY (copilote d'outils) : configuration déclarative et propriétaire.
ALTER TABLE dataops_dev.ai_studio.tools ADD COLUMNS (
  config STRING COMMENT 'Outils créés : configuration déclarative JSON (requête paramétrée, fonction UC)',
  owner STRING COMMENT 'Outils créés : propriétaire (e-mail) ; vide pour les outils intégrés');

-- Grain : 1 ligne par version d'outil créé. Clé : (tool_id, version).
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.tool_versions (
  tool_id STRING NOT NULL,
  version INT NOT NULL,
  spec STRING NOT NULL COMMENT 'Définition complète de l''outil (JSON)',
  test_result STRING COMMENT 'Résultat du test de validation (JSON)',
  note STRING COMMENT 'Commentaire de version',
  created_by STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  CONSTRAINT tool_versions_pk PRIMARY KEY (tool_id, version)
) COMMENT 'Historique des versions des outils créés dans DISCOVERY (grain : 1 ligne par version)';


-- Identité des agents (prénom = name) : nom d'appel @, rôle, accroche, exemples, anciens noms
ALTER TABLE dataops_dev.ai_studio.agents ADD COLUMNS (handle STRING COMMENT 'Nom d''appel @ (unique)',
  persona STRING COMMENT 'Rôle affiché après le prénom', tagline STRING COMMENT 'Accroche de la liste @',
  call_examples STRING COMMENT 'Liste JSON des exemples', aliases STRING COMMENT 'Liste JSON des anciens noms');

-- Équipes d'agents
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.teams (
  team_id STRING NOT NULL COMMENT 'Identifiant unique (uuid hex)',
  name STRING NOT NULL COMMENT 'Nom affiché de l''équipe',
  handle STRING NOT NULL COMMENT 'Nom d''appel @ (unique avec ceux des agents)',
  mission STRING COMMENT 'Mission en une phrase (affichée dans la liste @)',
  filiere STRING COMMENT 'Supply Chain | PTE | UDR | Transverse',
  icon STRING COMMENT 'Icône Material',
  lead_agent_id STRING COMMENT 'Agent chef d''équipe (obligatoire au-delà d''un membre)',
  human_owner STRING COMMENT 'Responsable humain (Data Owner / Data Steward), e-mail ou vide = à désigner',
  status STRING NOT NULL COMMENT 'brouillon | publie | archive',
  owner STRING NOT NULL COMMENT 'Créateur de l''équipe dans DISCOVERY',
  created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL,
  CONSTRAINT teams_pk PRIMARY KEY (team_id)
) COMMENT 'Équipes d''agents DISCOVERY (grain : 1 ligne par équipe)';
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.team_members (
  team_id STRING NOT NULL, agent_id STRING NOT NULL,
  role STRING NOT NULL COMMENT 'chef | membre',
  is_primary BOOLEAN COMMENT 'Équipe principale de l''agent',
  position INT COMMENT 'Ordre d''affichage',
  added_by STRING, added_at TIMESTAMP,
  CONSTRAINT team_members_pk PRIMARY KEY (team_id, agent_id)
) COMMENT 'Appartenance des agents aux équipes (grain : 1 ligne par équipe et agent)';
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.team_history (
  team_id STRING NOT NULL, changed_at TIMESTAMP NOT NULL, changed_by STRING NOT NULL,
  action STRING NOT NULL COMMENT 'creation | modification | publication | retrait | archivage',
  detail STRING COMMENT 'Description lisible du changement', snapshot STRING COMMENT 'État complet après changement (JSON)'
) COMMENT 'Historique des modifications d''équipes (grain : 1 ligne par changement)';


-- HakimAI lot 2 : journal d'audit des actions écrites et demandes de publication
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.copilot_actions (
  action_id STRING NOT NULL COMMENT 'Identifiant unique de l action',
  conversation_id STRING COMMENT 'Conversation HakimAI',
  user_name STRING NOT NULL COMMENT 'Utilisateur pour qui l action est faite',
  tool_id STRING NOT NULL COMMENT 'Outil HakimAI (creer_agent, archiver...)',
  object_type STRING COMMENT 'agent, outil, equipe',
  object_id STRING COMMENT 'Identifiant de l objet concerne',
  arguments STRING COMMENT 'Arguments valides par l utilisateur (JSON)',
  before_state STRING COMMENT 'Etat avant (JSON, si existant)',
  after_state STRING COMMENT 'Etat apres (JSON)',
  status STRING NOT NULL COMMENT 'succes, erreur, refuse, en_attente (demande de publication), traitee',
  error STRING COMMENT 'Message d erreur',
  created_at TIMESTAMP NOT NULL COMMENT 'Horodatage',
  CONSTRAINT copilot_actions_pk PRIMARY KEY (action_id)
) COMMENT 'Journal d audit des actions ecrites par HakimAI (lot 2) et demandes de publication';

-- HakimAI Transformation (lot A : cadrage, découverte, cartographie). HakimAI propose, le propriétaire décide.
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.transformation_plans (
  plan_id STRING NOT NULL COMMENT 'Identifiant du plan (tp_ + 12 hex)',
  name STRING NOT NULL COMMENT 'Nom du plan',
  owner STRING NOT NULL COMMENT 'Propriétaire (seul à modifier et décider)',
  status STRING NOT NULL COMMENT 'en_cours | archive',
  context STRING COMMENT 'Cadrage JSON : secteur, objectifs, irritants, contraintes, perimetre',
  discovery STRING COMMENT 'Dernière découverte JSON : structure et statistiques agrégées, jamais de lignes',
  created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL,
  CONSTRAINT transformation_plans_pk PRIMARY KEY (plan_id)
) COMMENT 'HakimAI Transformation : plans de transformation (grain : 1 ligne par plan)';

CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.transformation_items (
  plan_id STRING NOT NULL COMMENT 'Plan -> transformation_plans',
  item_id STRING NOT NULL COMMENT 'Identifiant (ti_ + 12 hex)',
  item_type STRING NOT NULL COMMENT 'objectif | domaine | processus (lot A) ; cas_usage | agent | equipe | flux | outil (lot B)',
  name STRING NOT NULL COMMENT 'Nom de l élément',
  payload STRING COMMENT 'Contenu JSON : description, hypotheses, domaine',
  evidence STRING COMMENT 'Preuves JSON : tables découvertes citées',
  status STRING NOT NULL COMMENT 'propose | valide | rejete',
  origin STRING NOT NULL COMMENT 'hakim | utilisateur',
  created_by STRING NOT NULL, created_at TIMESTAMP NOT NULL,
  decided_by STRING COMMENT 'Auteur de la décision humaine', decided_at TIMESTAMP, decision_note STRING,
  CONSTRAINT transformation_items_pk PRIMARY KEY (plan_id, item_id)
) COMMENT 'HakimAI Transformation : éléments proposés et décisions (grain : 1 ligne par élément)';


-- Rubrique Flux (lot 1) : boite d'echange entre les agents et les flux Power Automate
CREATE TABLE IF NOT EXISTS dataops_dev.ai_studio.flux_demandes (
  demande_id STRING NOT NULL COMMENT 'Identifiant unique de la demande (32 hex)',
  flux_id STRING NOT NULL COMMENT 'Flux appele (tool_id flux_...)',
  flux_version STRING COMMENT 'Version du flux au moment de la demande',
  conversation_id STRING COMMENT 'Conversation d origine (banc-de-test pour un essai)',
  agent_id STRING COMMENT 'Agent demandeur (vide pour le banc de test)',
  user_name STRING NOT NULL COMMENT 'Utilisateur pour qui la demande est faite',
  parametres STRING COMMENT 'Parametres transmis au flux, valeurs fixes incluses (JSON)',
  statut STRING NOT NULL COMMENT 'en_attente | en_cours | terminee | erreur',
  reponse STRING COMMENT 'Reponse ecrite par le flux (JSON de preference)',
  erreur STRING COMMENT 'Message d erreur ecrit par le flux',
  test BOOLEAN COMMENT 'Demande du banc de test',
  created_at TIMESTAMP NOT NULL COMMENT 'Depot de la demande',
  pris_en_charge_at TIMESTAMP COMMENT 'Prise en charge par le flux',
  termine_at TIMESTAMP COMMENT 'Reponse ou erreur',
  CONSTRAINT flux_demandes_pk PRIMARY KEY (demande_id)
) COMMENT 'Demandes des agents aux flux Power Automate (grain : 1 ligne par demande). Ecrite par le service principal de l App, lue et mise a jour par Power Automate (connecteur Azure Databricks)';
