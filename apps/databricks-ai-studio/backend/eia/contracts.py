"""EIA Core - contrats communs des agents transverses supervisés par HAKIM.

Aucune logique métier ici : les domaines (Sales, Finance...) sont décrits dans config/teams/*.json.
Règle de fond : tout chiffre présenté doit provenir d'un résultat d'outil (Evidence), jamais du modèle.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_ROLES = ("analyst", "prediction", "alerting", "advisor", "planner", "staffing")
SEVERITIES = ("info", "attention", "critique")
ALERT_KINDS = ("metier", "technique")          # anomalie métier ou erreur technique (jamais mélangées)
FINDING_KINDS = ("kpi", "tendance", "anomalie", "constat")
TRIGGERS = ("demande", "planifie", "evenement")

STATUSES = {
    "run": ("en_cours", "termine", "partiel", "echec"),
    "step": ("en_attente", "en_cours", "reussi", "echec", "expire", "ignore"),
    "alert": ("nouvelle", "vue", "acquittee", "resolue"),
    "recommendation": ("proposee", "selectionnee", "validee", "rejetee"),
    "mission": ("brouillon", "validee", "en_cours", "terminee", "annulee"),
    "task": ("a_faire", "en_cours", "fait", "bloque", "annule"),
    "assignment": ("proposee", "confirmee", "refusee", "annulee"),
}

# Transitions autorisées (de -> vers). Toute autre transition est refusée.
TRANSITIONS = {
    "run": {"en_cours": {"termine", "partiel", "echec"}},
    "step": {"en_attente": {"en_cours", "ignore"}, "en_cours": {"reussi", "echec", "expire"},
             "echec": {"en_cours"}, "expire": {"en_cours"}},          # reprise possible après échec / délai
    "alert": {"nouvelle": {"vue", "acquittee", "resolue"}, "vue": {"acquittee", "resolue"},
              "acquittee": {"resolue"}},
    "recommendation": {"proposee": {"selectionnee", "rejetee"}, "selectionnee": {"validee", "rejetee", "proposee"}},
    "mission": {"brouillon": {"validee", "annulee"}, "validee": {"en_cours", "annulee"},
                "en_cours": {"terminee", "annulee"}},
    "task": {"a_faire": {"en_cours", "bloque", "annule"}, "en_cours": {"fait", "bloque", "annule"},
             "bloque": {"a_faire", "en_cours", "annule"}},
    "assignment": {"proposee": {"confirmee", "refusee", "annulee"}, "confirmee": {"annulee"}},
}
# Transitions qui exigent une décision humaine explicite (utilisateur identifié + date).
HUMAN_DECISIONS = {("recommendation", "validee"), ("recommendation", "rejetee"), ("mission", "validee"),
                   ("mission", "annulee"), ("assignment", "confirmee"), ("assignment", "refusee")}

MAX_TEXT = 4000


class ContractError(ValueError):
    """Entrée ou sortie non conforme au contrat EIA."""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def fingerprint(*parts: Any) -> str:
    """Empreinte stable (dédoublonnage des alertes : même équipe, règle, périmètre et période)."""
    raw = "|".join("" if p is None else str(p).strip().lower() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def check_transition(kind: str, current: str, target: str, decided_by: str | None = None) -> None:
    if kind not in STATUSES:
        raise ContractError(f"Type d'objet inconnu : {kind}")
    if target not in STATUSES[kind]:
        raise ContractError(f"Statut inconnu pour {kind} : {target}")
    if target not in TRANSITIONS[kind].get(current, set()):
        raise ContractError(f"Transition interdite pour {kind} : {current} -> {target}")
    if (kind, target) in HUMAN_DECISIONS and not (decided_by and "@" in decided_by):
        raise ContractError(f"{kind} -> {target} exige la décision explicite d'un utilisateur identifié")


@dataclass
class Evidence:
    """Preuve d'un chiffre : outil, source et requête (ou méthode) qui l'ont produit."""
    tool: str
    source: str = ""            # tables ou alias utilisés
    query: str = ""             # SQL exécuté ou description de la méthode
    produced_at: str = ""


@dataclass
class Finding:
    kind: str                   # FINDING_KINDS
    title: str
    value: float | None = None
    unit: str = ""
    period: str = ""
    detail: str = ""
    evidence: Evidence | None = None
    id: str = field(default_factory=lambda: new_id("fd"))


@dataclass
class ForecastPoint:
    period: str
    value: float
    lower: float | None = None
    upper: float | None = None


@dataclass
class Forecast:
    metric: str
    method: str
    horizon: int
    points: list[ForecastPoint]
    history_points: int = 0
    backtest_error_pct: float | None = None     # erreur moyenne absolue en % sur la période de test
    baseline_error_pct: float | None = None     # même mesure pour la méthode naïve de référence
    reliable: bool = False
    reliability_note: str = ""
    assumptions: list[str] = field(default_factory=list)
    evidence: Evidence | None = None
    id: str = field(default_factory=lambda: new_id("fc"))


@dataclass
class Alert:
    rule_id: str
    severity: str               # SEVERITIES
    title: str
    message: str
    kind: str = "metier"        # ALERT_KINDS
    metric: str = ""
    scope: str = ""             # dimension concernée (ex. une région) ; vide = global
    period: str = ""
    observed: float | None = None
    threshold: float | None = None
    rule_status: str = "a_valider"   # statut de validation métier de la règle
    evidence: Evidence | None = None
    id: str = field(default_factory=lambda: new_id("al"))


@dataclass
class Recommendation:
    title: str
    rationale: str
    priority: int               # 1 = la plus prioritaire
    based_on: list[str]         # identifiants de Finding / Forecast / Alert
    expected_impact: str = ""   # uniquement si calculé à partir des preuves ; sinon vide
    assumptions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("rc"))


@dataclass
class MissionTask:
    title: str
    owner: str = ""             # rôle ou personne proposée (à confirmer)
    due_in_days: int | None = None
    deliverable: str = ""
    depends_on: list[str] = field(default_factory=list)
    required_skills: list[dict] = field(default_factory=list)   # [{skill, level}] issus du référentiel de l'équipe
    estimated_hours: int | None = None
    id: str = field(default_factory=lambda: new_id("mt"))


@dataclass
class Mission:
    title: str
    objective: str
    recommendation_id: str
    tasks: list[MissionTask]
    success_kpis: list[str]
    deliverables: list[str] = field(default_factory=list)
    owner: str = ""
    due_in_days: int | None = None
    id: str = field(default_factory=lambda: new_id("ms"))


@dataclass
class AgentResult:
    """Sortie standard d'un agent EIA (une étape du plan HAKIM)."""
    agent: str                  # AGENT_ROLES
    status: str                 # STATUSES["step"] final : reussi | echec | expire
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    forecasts: list[Forecast] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    missions: list[Mission] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def ids(self) -> set[str]:
        return {x.id for x in (*self.findings, *self.forecasts, *self.alerts, *self.recommendations)}


def to_dict(obj: Any) -> Any:
    return asdict(obj)


def to_json(obj: Any) -> str:
    return json.dumps(asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj, ensure_ascii=False, default=str)


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_result(r: AgentResult, known_ids: set[str] | None = None) -> list[str]:
    """Contrôle d'une sortie d'agent. Liste vide = conforme. `known_ids` : preuves produites par les étapes amont."""
    issues: list[str] = []
    if r.agent not in AGENT_ROLES:
        issues.append(f"agent inconnu : {r.agent}")
    if r.status not in ("reussi", "echec", "expire"):
        issues.append(f"statut final invalide : {r.status}")
    if r.status == "reussi" and r.errors:
        issues.append("statut reussi avec des erreurs")
    if len(r.summary) > MAX_TEXT:
        issues.append("synthèse trop longue")
    for f in r.findings:
        if f.kind not in FINDING_KINDS:
            issues.append(f"constat {f.id} : type inconnu {f.kind}")
        if f.value is not None and (not _num(f.value) or f.evidence is None or not f.evidence.tool):
            issues.append(f"constat {f.id} : valeur sans preuve d'outil")
    for fc in r.forecasts:
        if fc.horizon < 1 or len(fc.points) != fc.horizon:
            issues.append(f"prévision {fc.id} : horizon et nombre de points incohérents")
        if fc.evidence is None or not fc.method:
            issues.append(f"prévision {fc.id} : méthode ou preuve manquante")
        if fc.reliable and fc.backtest_error_pct is None:
            issues.append(f"prévision {fc.id} : déclarée fiable sans test sur l'historique")
        if not fc.reliable and not fc.reliability_note:
            issues.append(f"prévision {fc.id} : non fiable sans explication")
        for p in fc.points:
            if not _num(p.value) or (p.lower is not None and p.upper is not None and not p.lower <= p.value <= p.upper):
                issues.append(f"prévision {fc.id} : point {p.period} incohérent")
    for a in r.alerts:
        if a.severity not in SEVERITIES:
            issues.append(f"alerte {a.id} : gravité inconnue {a.severity}")
        if a.kind not in ALERT_KINDS:
            issues.append(f"alerte {a.id} : type inconnu {a.kind}")
        if a.kind == "metier" and (a.evidence is None or a.observed is None):
            issues.append(f"alerte {a.id} : alerte métier sans valeur observée ni preuve")
    refs = (known_ids or set()) | r.ids()
    for rc in r.recommendations:
        if not rc.based_on:
            issues.append(f"recommandation {rc.id} : aucune preuve citée")
        missing = [x for x in rc.based_on if x not in refs]
        if missing:
            issues.append(f"recommandation {rc.id} : preuves inconnues {missing}")
        if rc.priority < 1:
            issues.append(f"recommandation {rc.id} : priorité invalide")
    for m in r.missions:
        if not m.tasks or not m.success_kpis or not m.recommendation_id:
            issues.append(f"mission {m.id} : tâches, KPI de réussite et recommandation d'origine obligatoires")
        tids = {t.id for t in m.tasks}
        for t in m.tasks:
            if any(d not in tids or d == t.id for d in t.depends_on):
                issues.append(f"mission {m.id} : dépendance invalide pour la tâche {t.id}")
    return issues
