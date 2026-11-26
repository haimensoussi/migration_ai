"""EIA Core - catalogue officiel des catégories d'agents et modèles d'agents réutilisables.

Un modèle d'agent = une partie fixe (code, contrat de sortie, garde-fous, tests) + une fiche de paramètres.
Adapter un modèle à une équipe consiste à renseigner ses paramètres dans la configuration d'équipe
(config/teams/<team_id>.json), jamais à écrire du code propre à l'équipe.

Origine d'un paramètre :
- "donnees" : déduit des données découvertes (tables, SQL, granularité, profondeur d'historique) ;
- "metier"  : relevé du contexte de l'entreprise (objectifs, seuils, responsables) ; à valider par le métier.

Classification officielle DISCOVERY : 10 catégories AG01 à AG10 (décision du 25/11/2026 : Predictive Intelligence
AG02 séparé de Data Intelligence AG01 ; Simulation & Scenario retiré).

Framework des agents (étape 1 de l'EIA Factory) :
- contrat commun : statut, entrées/sorties standard (INTERFACES), points d'entrée dans le code, garde-fous ;
- 10 modèles : disponible | partiel | squelette (contrat et paramètres déclarés, pas de code) ;
- check_team : cohérence d'une composition (modèles connus, interfaces alimentées, paramètres conformes),
  brique réutilisée par le Team Builder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

CATEGORIES: dict[str, dict] = {
    "AG01": {"nom": "Data Intelligence Agent", "statut": "disponible",
             "fonctions": "Perception, exploration des données, calcul des KPI, analyse, diagnostic et détection "
                          "des anomalies"},
    "AG02": {"nom": "Predictive Intelligence Agent", "statut": "disponible",
             "fonctions": "Prévisions, tendances, anticipation des risques et projections, avec fiabilité mesurée"},
    "AG03": {"nom": "Strategic Intelligence Agent", "statut": "disponible",
             "fonctions": "Recommandations, arbitrage, optimisation et priorisation des actions"},
    "AG04": {"nom": "Execution & Automation Agent", "statut": "partiel",
             "fonctions": "Exécution des actions validées, workflows, notifications et automatisation"},
    "AG05": {"nom": "Learning & Improvement Agent", "statut": "partiel",
             "fonctions": "Apprentissage, évaluation des résultats, feedback et amélioration continue"},
    "AG06": {"nom": "Team Manager Agent", "statut": "disponible",
             "fonctions": "Coordination, planification, délégation, supervision et pilotage des équipes"},
    "AG07": {"nom": "Knowledge & Context Agent", "statut": "squelette",
             "fonctions": "Recherche documentaire, RAG, contextualisation et gestion des connaissances"},
    "AG08": {"nom": "Monitoring & Governance Agent", "statut": "partiel",
             "fonctions": "Surveillance, alerting, qualité, conformité, contrôle et traçabilité"},
    "AG09": {"nom": "Engineering & Builder Agent", "statut": "partiel",
             "fonctions": "Conception, développement et tests des agents, outils et workflows"},
    "AG10": {"nom": "Enterprise Architect Agent", "statut": "partiel",
             "fonctions": "Découverte de l'entreprise, identification des opportunités IA, conception de l'architecture EIA"},
}

# Rôles techniques du cycle (noms historiques conservés) -> catégorie officielle.
ROLE_CATEGORY = {"perception": "AG01", "analyst": "AG01", "prediction": "AG02", "alerting": "AG01",
                 "advisor": "AG03", "planner": "AG06", "staffing": "AG06"}
ORIGINS = ("donnees", "metier")
MODEL_STATUSES = ("disponible", "partiel", "squelette")

# Garde-fous communs à tous les modèles (partie fixe, non paramétrable).
GUARDRAILS = (
    "Aucun chiffre produit par un modèle de langage : les valeurs viennent des données et du code",
    "Aucune décision prise par un agent : sélection, validation, affectation et clôture restent humaines",
    "Erreurs techniques séparées des anomalies métier",
    "Chaque résultat porte sa preuve (source, requête ou règle) et respecte le contrat AgentResult",
    "Seuils, règles et plans d'action non validés restent « à valider »",
    "Droits et identité de l'utilisateur appelant ; aucune action externe sans canal validé",
)

# Interfaces standard échangées entre modèles (contrat d'assemblage du Team Builder).
INTERFACES = {
    "donnees_sources": "Tables Unity Catalog déclarées (externe)",
    "documents": "Documents et glossaires de l'entreprise (externe)",
    "decisions_humaines": "Décisions d'une personne identifiée (externe)",
    "observations": "Valeurs de KPI datées avec preuve et contrôle de qualité",
    "constats": "Constats d'analyse (Finding)",
    "previsions": "Prévisions avec fiabilité mesurée (Forecast)",
    "alertes": "Anomalies métier et erreurs techniques (Alert)",
    "recommandations": "Options proposées et priorisées (Recommendation)",
    "missions": "Missions et tâches planifiées (Mission, MissionTask)",
    "affectations_proposees": "Personnes proposées par tâche, à confirmer",
    "executions": "Suivi des actions validées et notifications",
    "bilans": "Évaluations après clôture, sans conclusion causale",
    "ajustements_proposes": "Améliorations de règles, KPI ou plans d'action, à valider",
    "contexte": "Extraits documentaires cités",
    "architecture_equipe": "Conception d'une équipe EIA (modèles et paramètres proposés)",
    "configuration_equipe": "Configuration d'équipe en brouillon, conforme au Framework",
    "controles": "Résultats de contrôle, conformité et traçabilité",
}
EXTERNAL = ("donnees_sources", "documents", "decisions_humaines")


@dataclass(frozen=True)
class ParamSpec:
    path: str                    # chemin dans la configuration d'équipe (ex. "perception.max_lag_months")
    kind: str                    # liste | entier | nombre | objet
    origin: str                  # donnees | metier
    description: str
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class AgentModel:
    code: str
    version: str
    functions: tuple[str, ...]   # fonctions internes journalisées comme étapes du cycle
    params: tuple[ParamSpec, ...]
    usage: str                   # conditions d'usage
    checks: tuple[Callable[[Any], list[str]], ...] = field(default=())
    status: str = "disponible"   # MODEL_STATUSES
    inputs: tuple[str, ...] = ()            # interfaces obligatoires
    optional_inputs: tuple[str, ...] = ()   # interfaces utilisées si disponibles
    outputs: tuple[str, ...] = ()
    entrypoints: tuple[str, ...] = ()       # "module:fonction" réellement implémentés
    guardrails: tuple[str, ...] = ()        # garde-fous propres, en plus de GUARDRAILS
    missing: str = ""                       # ce qui reste à développer (partiel / squelette)

    @property
    def name(self) -> str:
        return CATEGORIES[self.code]["nom"]

    def check(self, cfg: Any) -> list[str]:
        """Conformité des paramètres d'une configuration d'équipe au modèle (utilisé par AG08 avant validation)."""
        issues = []
        for p in self.params:
            value = _get(cfg, p.path)
            if value is None:
                if p.required:
                    issues.append(f"{self.code} : paramètre obligatoire absent : {p.path}")
                continue
            if not _kind_ok(value, p.kind):
                issues.append(f"{self.code} : {p.path} doit être de type {p.kind}")
        for fn in self.checks:
            issues += [f"{self.code} : {x}" for x in fn(cfg)]
        return issues

    def describe(self) -> dict:
        return {"code": self.code, "nom": self.name, "version": self.version, "statut": self.status,
                "fonctions": list(self.functions), "conditions_usage": self.usage,
                "entrees": list(self.inputs), "entrees_facultatives": list(self.optional_inputs),
                "sorties": list(self.outputs), "points_entree": list(self.entrypoints),
                "garde_fous": [*GUARDRAILS, *self.guardrails], "reste_a_faire": self.missing,
                "parametres": [{"chemin": p.path, "type": p.kind, "origine": p.origin, "obligatoire": p.required,
                                "defaut": p.default, "description": p.description} for p in self.params]}


def _get(cfg: Any, path: str) -> Any:
    head, *rest = path.split(".")
    cur = getattr(cfg, head, None) if not isinstance(cfg, dict) else cfg.get(head)
    for part in rest:
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _kind_ok(v: Any, kind: str) -> bool:
    return {"liste": isinstance(v, list), "objet": isinstance(v, dict), "texte": isinstance(v, str),
            "entier": isinstance(v, int) and not isinstance(v, bool),
            "nombre": isinstance(v, (int, float)) and not isinstance(v, bool)}.get(kind, True)


# ---------------- AG01 Data Intelligence ----------------

def perceived_kpis(cfg: Any) -> list[str]:
    """KPI lus par AG01 sur un cycle : suivis par l'analyse, prévus, ou utilisés par une règle active."""
    analysis = (cfg.analysis or {}).get("kpis") or []
    forecast = (cfg.forecast or {}).get("kpis") or []
    rules = [r["kpi"] for r in cfg.rules if r.get("status") != "desactive"]
    return sorted(set(analysis) | set(forecast) | set(rules))


def _ag01_refs(cfg: Any) -> list[str]:
    ids = {k.get("id"): k for k in _get(cfg, "kpis") or [] if isinstance(k, dict)}
    issues = [f"KPI suivi inconnu : {x}" for x in _get(cfg, "analysis.kpis") or [] if x not in ids]
    lag = _get(cfg, "perception.max_lag_months")
    if lag is not None and (not _kind_ok(lag, "entier") or lag < 0):
        issues.append("perception.max_lag_months doit être un entier positif ou nul")
    return issues


def _ag02_refs(cfg: Any) -> list[str]:
    ids = {k.get("id"): k for k in _get(cfg, "kpis") or [] if isinstance(k, dict)}
    issues = []
    for x in _get(cfg, "forecast.kpis") or []:
        if x not in ids:
            issues.append(f"KPI à prévoir inconnu : {x}")
        elif ids[x].get("grain") != "mois":
            issues.append(f"KPI à prévoir non mensuel : {x} (prévision impossible)")
    return issues


AG01 = AgentModel(
    code="AG01", version="1.0", functions=("perception", "analyst", "alerting"),
    usage="Toute équipe disposant d'au moins un KPI lisible.",
    params=(
        ParamSpec("sources", "objet", "donnees", "Alias -> tables Unity Catalog lues par les KPI", required=True),
        ParamSpec("kpis", "liste", "donnees", "Définitions des KPI : SQL en lecture seule, granularité, unité, sens",
                  required=True),
        ParamSpec("analysis.kpis", "liste", "metier", "KPI suivis par l'analyse (défaut : KPI des règles)"),
        ParamSpec("analysis.window_months", "entier", "metier", "Fenêtre de comparaison en mois", default=1),
        ParamSpec("perception.max_lag_months", "entier", "metier",
                  "Retard maximal toléré, en mois, par rapport au dernier mois complet (KPI mensuel : dernière "
                  "période ; KPI instantané : date de situation) ; au-delà le KPI est écarté (erreur technique, "
                  "jamais anomalie métier). À valider.", default=None),
        ParamSpec("rules", "liste", "metier", "Règles de détection des anomalies et seuils (« à valider »)", required=True),
    ),
    checks=(_ag01_refs,),
    inputs=("donnees_sources",), outputs=("observations", "constats", "alertes"),
    entrypoints=("backend.eia.agents:perception", "backend.eia.agents:analyst", "backend.eia.agents:alerting"),
    guardrails=("Un KPI non exploitable est écarté avant analyse",),
)

AG02 = AgentModel(
    code="AG02", version="1.0", functions=("prediction",), status="disponible",
    usage="KPI mensuel global avec un historique suffisant pour le test de fiabilité (sinon la prévision est "
          "signalée non fiable, sans bloquer l'analyse d'AG01).",
    params=(
        ParamSpec("forecast.kpis", "liste", "donnees", "KPI mensuels globaux à prévoir", required=True),
        ParamSpec("forecast.horizon", "entier", "metier", "Horizon de prévision en mois", default=3),
        ParamSpec("forecast.season_length", "entier", "donnees", "Longueur de saison en mois", default=12),
        ParamSpec("forecast.test_points", "entier", "donnees", "Mois réservés au test de fiabilité", default=6),
        ParamSpec("forecast.max_error_pct", "nombre", "metier", "Erreur maximale tolérée pour une prévision fiable",
                  default=15),
    ),
    checks=(_ag02_refs,),
    inputs=("observations",), outputs=("previsions",),
    entrypoints=("backend.eia.agents:prediction", "backend.eia.forecast:forecast"),
    guardrails=("Une prévision non fiable n'est jamais présentée comme certaine ; méthode et test de fiabilité "
                "joints à chaque prévision",),
)


def _active_playbooks(cfg: Any) -> list[dict]:
    return [p for p in _get(cfg, "playbooks") or [] if isinstance(p, dict) and p.get("status") != "desactive"]


def _ag03_refs(cfg: Any) -> list[str]:
    return [] if _active_playbooks(cfg) else ["aucun plan d'action type actif : aucune recommandation possible"]


def _ag05_refs(cfg: Any) -> list[str]:
    ids = {k.get("id") for k in _get(cfg, "kpis") or [] if isinstance(k, dict)}
    out = []
    for p in _active_playbooks(cfg):
        if not p.get("success_kpis"):
            out.append(f"plan {p.get('id')} : aucun KPI de réussite, bilan impossible")
        out += [f"plan {p.get('id')} : KPI de réussite inconnu {x}" for x in p.get("success_kpis") or [] if x not in ids]
    return out


def _ag06_refs(cfg: Any) -> list[str]:
    needs = any(t.get("required_skills") for p in _active_playbooks(cfg) for t in p.get("tasks") or [])
    return ["compétences requises sans référentiel de compétences"] if needs and not _get(cfg, "skills") else []


def _policy_refs(cfg: Any) -> list[str]:
    vp = _get(cfg, "validation_policy") or {}
    out = [] if vp.get("mission_requires_validation") is True else ["la validation humaine des missions est obligatoire"]
    return out + ([] if vp.get("external_actions") in ("interdit", "sur_validation") else
                  ["actions externes : interdit | sur_validation"])


AG03 = AgentModel(
    code="AG03", version="1.0", functions=("advisor",), status="disponible",
    usage="Équipe disposant d'alertes métier et d'au moins un plan d'action type actif.",
    params=(ParamSpec("playbooks", "liste", "metier", "Plans d'action types : règles déclencheuses, justification, "
                      "KPI de réussite, tâches (« à valider »)", required=True),),
    checks=(_ag03_refs,), inputs=("alertes",), optional_inputs=("previsions", "contexte"),
    outputs=("recommandations",), entrypoints=("backend.eia.agents:advisor",),
    guardrails=("Recommandations proposées uniquement ; aucun gain chiffré sans modèle validé",),
    missing="Options comparées (2 ou 3 par situation) et nouvelles options après un refus motivé",
)

AG04 = AgentModel(
    code="AG04", version="0.5", functions=("preparer_mission", "suivi_mission", "notifications"), status="partiel",
    usage="Après une décision humaine : brouillon de mission, suivi des statuts, notifications sur canal validé.",
    params=(ParamSpec("validation_policy", "objet", "metier", "Qui valide quoi ; actions externes interdites ou sur "
                      "validation", required=True),
            ParamSpec("notifications", "objet", "metier", "Canal, destinataires et gravité minimale (désactivé par "
                      "défaut)")),
    checks=(_policy_refs,), inputs=("missions", "decisions_humaines"), outputs=("executions",),
    entrypoints=("backend.eia.engine:prepare_mission", "backend.eia.console:decide", "backend.eia.alerting:run_alerting"),
    guardrails=("N'exécute que des actions validées par une personne identifiée",),
    missing="Agent de suivi intégré au cycle : retards, blocages, surcharge, relecture des KPI en cours de mission",
)

AG05 = AgentModel(
    code="AG05", version="0.5", functions=("bilan_mission",), status="partiel",
    usage="Après clôture humaine d'une mission ; comparaison à la référence figée, même version de configuration.",
    params=(ParamSpec("playbooks", "liste", "metier", "KPI de réussite de chaque plan d'action", required=True),),
    checks=(_ag05_refs,), inputs=("missions", "observations"), outputs=("bilans",),
    entrypoints=("backend.eia.engine:learn_mission", "backend.eia.engine:observe"),
    guardrails=("Variation observée, jamais causalité ; aucune règle ni seuil modifié automatiquement",),
    missing="Bilans consolidés par plan d'action et ajustements proposés « à valider » (sortie ajustements_proposes)",
)

AG06 = AgentModel(
    code="AG06", version="1.0", functions=("planner", "staffing"), status="disponible",
    usage="Équipe avec plans d'action détaillés en tâches ; délégation si un référentiel de compétences existe.",
    params=(ParamSpec("skills", "liste", "metier", "Référentiel de compétences de l'équipe"),
            ParamSpec("staffing", "objet", "metier", "Pondérations compétences / disponibilité, nombre de candidats, "
                      "horizon (« à valider »)"),
            ParamSpec("playbooks", "liste", "metier", "Tâches, charges, délais et compétences requises", required=True)),
    checks=(_ag06_refs,), inputs=("recommandations",), optional_inputs=("decisions_humaines",),
    outputs=("missions", "affectations_proposees"),
    entrypoints=("backend.eia.agents:planner", "backend.eia.agents:staffing"),
    guardrails=("Critères professionnels uniquement ; affectations proposées, confirmées par un responsable",),
)

AG08 = AgentModel(
    code="AG08", version="0.5", functions=("alertes_techniques", "suivi_alertes", "controle_equipe"), status="partiel",
    usage="Toute équipe : cycle de vie des alertes, erreurs techniques, traçabilité, contrôle de conformité.",
    params=(ParamSpec("rules", "liste", "metier", "Règles avec statut de validation et rôle responsable", required=True),
            ParamSpec("validation_policy", "objet", "metier", "Politique de validation de l'équipe", required=True)),
    checks=(_policy_refs,), optional_inputs=("alertes", "executions", "configuration_equipe"), outputs=("controles",),
    entrypoints=("backend.eia.alerting:technical_alert", "backend.eia.console:decide_alert",
                 "backend.eia.console:alert_summary", "backend.eia.agent_models:check_team"),
    guardrails=("Contrôle de code uniquement ; un contrôle en échec bloque la phase, jamais contourné par un agent",),
    missing="Contrôles de passage du Team Builder (qualité des sources, cohérence, recette en aperçu)",
)

AG07 = AgentModel(
    code="AG07", version="0.1", functions=("recherche_documentaire",), status="squelette",
    usage="Quand des documents d'entreprise validés sont disponibles (cadrage, glossaire, procédures).",
    params=(ParamSpec("knowledge.sources", "liste", "metier", "Documents ou index autorisés, avec propriétaire",
                      required=True),),
    inputs=("documents",), outputs=("contexte",),
    guardrails=("Chaque extrait est cité avec sa source ; aucun document hors périmètre autorisé",),
    missing="Indexation et recherche (choix technique à arbitrer), sources documentaires à désigner",
)

AG09 = AgentModel(
    code="AG09", version="0.5", functions=("tester_equipe", "ajuster_equipe", "construire_equipe"), status="partiel",
    usage="Team Builder, phase 3 : recette en aperçu de l'architecture proposée, puis brouillon versionné.",
    params=(ParamSpec("team_builder.max_forecasts", "entier", "donnees",
                      "Prévisions retenues au plus après ajustement de recette", default=3),),
    inputs=("architecture_equipe",), outputs=("configuration_equipe",),
    entrypoints=("backend.eia.team_builder:recette", "backend.eia.team_builder:adjust",
                 "backend.eia.team_builder:build"),
    guardrails=("Produit des brouillons ; la mise en service est une décision humaine après contrôles AG08 réussis",
                "Ne publie ni ne donne de droits ; recette sans écriture"),
    missing="Génération d'outils, de flux et de tableaux de bord ; tests de non-régression automatisés par équipe",
)

AG10 = AgentModel(
    code="AG10", version="0.5", functions=("kpi_candidats", "architecture"), status="partiel",
    usage="Team Builder, phases 1 et 2 : après découverte des sources (profil du Transformation Center).",
    params=(ParamSpec("team_builder.max_kpis", "entier", "donnees", "KPI retenus au plus par équipe proposée",
                      default=12),),
    inputs=("observations",), optional_inputs=("contexte",), outputs=("architecture_equipe",),
    entrypoints=("backend.eia.team_builder:kpi_candidates", "backend.eia.team_builder:design"),
    guardrails=("Propose une architecture ; tout élément métier reste « à valider »",
                "Sans règles ni plans d'action fournis par le métier : équipe de surveillance, aucun seuil inventé"),
    missing="Opportunités IA et cible du Transformation Center ; règles d'alerte proposées à partir de l'historique",
)

MODELS: dict[str, AgentModel] = {m.code: m for m in (AG01, AG02, AG03, AG04, AG05, AG06, AG07, AG08, AG09, AG10)}

# Compositions de référence.
BUSINESS_TEAM = ("AG01", "AG02", "AG03", "AG06", "AG04", "AG05", "AG08")     # équipe métier (ex. Sales)
FACTORY_TEAM = ("AG01", "AG10", "AG09", "AG08")                      # EIA Factory / Team Builder


def team_models(cfg: Any) -> list[str]:
    """Modèles d'une équipe : déclarés dans la configuration, complétés par la catégorie de chaque rôle actif.

    Compatibilité : une configuration antérieure à la séparation d'AG02 (rôle prediction déclaré sous AG01)
    reçoit AG02 sans modification des données enregistrées.
    """
    declared = list(_get(cfg, "models") or [])
    implied = sorted({ROLE_CATEGORY[r] for r in _get(cfg, "agents") or [] if r in ROLE_CATEGORY})
    if not declared:
        return implied
    return declared + [c for c in implied if c not in declared]


def check_composition(codes: list[str], allow_skeleton: bool = False) -> list[str]:
    """Cohérence d'une composition : modèles connus et utilisables, interfaces obligatoires alimentées."""
    issues = []
    for code in codes:
        meta = CATEGORIES.get(code)
        if not meta:
            issues.append(f"catégorie inconnue : {code}")
        elif meta.get("fusionne_dans"):
            issues.append(f"{code} est fusionné dans {meta['fusionne_dans']}")
        elif MODELS[code].status == "squelette" and not allow_skeleton:
            issues.append(f"{code} n'est pas encore opérationnel (squelette)")
    models = [MODELS[x] for x in codes if x in MODELS]
    produced = set(EXTERNAL).union(*(m.outputs for m in models)) if models else set(EXTERNAL)
    for m in models:
        issues += [f"{m.code} : entrée {i} produite par aucun modèle de l'équipe" for i in m.inputs if i not in produced]
    return issues


def check_team(cfg: Any, allow_skeleton: bool = False) -> list[str]:
    """Contrôle AG08 d'une configuration d'équipe : composition, interfaces et paramètres de chaque modèle."""
    codes = team_models(cfg)
    issues = check_composition(codes, allow_skeleton)
    for code in codes:
        if code in MODELS:
            issues += MODELS[code].check(cfg)
    return issues


def catalog() -> list[dict]:
    """Les 10 catégories officielles avec leur modèle d'agent réutilisable."""
    return [{"code": code, **meta, "modele": MODELS[code].describe() if code in MODELS else None}
            for code, meta in CATEGORIES.items()]


def category_of(role: str) -> str | None:
    return ROLE_CATEGORY.get(role)
