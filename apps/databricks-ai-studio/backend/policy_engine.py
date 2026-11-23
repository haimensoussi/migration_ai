"""Agent Mesh T206 : moteur de politiques (refus par défaut, deny prioritaire, décisions journalisées).

Modes (AI_STUDIO_POLICY_MODE) :
- off     : aucun contrôle ;
- audit   : chaque appel est évalué et les refus sont journalisés, mais rien n'est bloqué (défaut) ;
- enforce : un refus bloque l'appel ; un moteur indisponible bloque aussi (fermeture en cas d'erreur).
Les politiques de base (database/mesh_schema.sql) reproduisent les règles actuelles : en mode audit, un refus
signale donc un écart à analyser avant de passer en enforce.
"""
from __future__ import annotations

import fnmatch
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

MODES = ("off", "audit", "enforce")
ROLES = {
    "platform_admin": "Administre DISCOVERY (domaines, rôles, politiques)",
    "domain_admin": "Administre un domaine (équipes, rôles du domaine)",
    "domain_validator": "Valide les publications d'agents d'un domaine",
    "agent_developer": "Crée et modifie des agents et des outils",
    "agent_user": "Utilise les agents publiés",
    "auditor": "Consulte les journaux et les décisions (lecture seule)",
}
SCOPES = ("platform", "domain")
CONDITIONS = ("status_in", "owner_is_principal", "read_only", "domain_in")


@dataclass(frozen=True)
class Policy:
    policy_id: str
    effect: str                      # allow | deny
    actions: tuple = ("*",)
    roles: tuple = ()                # () = tous
    resources: tuple = ("*",)        # motifs type:id
    conditions: dict = field(default_factory=dict)
    priority: int = 100
    name: str = ""

    @staticmethod
    def from_row(r: dict) -> "Policy":
        def j(v, d):
            try:
                return json.loads(v) if isinstance(v, str) and v else (v if v is not None else d)
            except json.JSONDecodeError:
                return d
        return Policy(policy_id=r["policy_id"], effect=str(r["effect"]).lower(), actions=tuple(j(r.get("actions"), ["*"])),
                      roles=tuple(j(r.get("roles"), [])), resources=tuple(j(r.get("resources"), ["*"])),
                      conditions=dict(j(r.get("conditions"), {})), priority=int(r.get("priority") or 100),
                      name=r.get("name") or "")


@dataclass(frozen=True)
class Assignment:
    principal_type: str              # user | all
    principal: str
    role: str
    scope_type: str = "platform"
    scope_id: str | None = None


@dataclass
class Request:
    principal: str
    action: str                      # tool.invoke, agent.invoke, agent.publish...
    resource: str                    # type:id, ex. tool:execute_sql, tool:agent:<id>
    attrs: dict = field(default_factory=dict)   # status, owner, read_only, domain
    agent_id: str = ""
    conversation_id: str = ""


@dataclass
class Decision:
    allowed: bool
    reason: str
    policy_id: str | None = None
    enforced: bool = False           # vrai si l'appel est réellement bloqué
    mode: str = "audit"


# -- évaluation pure ---------------------------------------------------------------------------------
def roles_of(principal: str, assignments: list[Assignment], domain: str | None = None) -> set[str]:
    """Rôles actifs du principal : portée plateforme, ou portée domaine si la ressource est de ce domaine."""
    p = (principal or "").lower()
    out = set()
    for a in assignments:
        who = a.principal_type == "all" or (a.principal_type == "user" and a.principal.lower() == p and p)
        where = a.scope_type == "platform" or (a.scope_type == "domain" and domain and a.scope_id == domain)
        if who and where:
            out.add(a.role)
    return out


def _conditions_ok(cond: dict, req: Request) -> bool:
    at = req.attrs or {}
    if "status_in" in cond and at.get("status") not in cond["status_in"]:
        return False
    if cond.get("owner_is_principal") and not (at.get("owner") and str(at["owner"]).lower() == req.principal.lower()):
        return False
    if "read_only" in cond and bool(at.get("read_only")) != bool(cond["read_only"]):
        return False
    if "domain_in" in cond and at.get("domain") not in cond["domain_in"]:
        return False
    return all(k in CONDITIONS for k in cond)      # condition inconnue : la politique ne s'applique pas


def matches(p: Policy, req: Request, roles: set[str]) -> bool:
    return (any(fnmatch.fnmatchcase(req.action, a) for a in p.actions)
            and (not p.roles or bool(roles & set(p.roles)))
            and any(fnmatch.fnmatchcase(req.resource, r) for r in p.resources)
            and _conditions_ok(p.conditions, req))


def evaluate(policies: list[Policy], assignments: list[Assignment], req: Request) -> Decision:
    """Refus par défaut ; un deny applicable l'emporte sur tout allow ; à effet égal, la plus petite priorité décide."""
    roles = roles_of(req.principal, assignments, (req.attrs or {}).get("domain"))
    hits = sorted((p for p in policies if matches(p, req, roles)), key=lambda p: (p.priority, p.policy_id))
    deny = next((p for p in hits if p.effect == "deny"), None)
    if deny:
        return Decision(False, f"Refusé par la politique {deny.policy_id} ({deny.name or 'sans nom'}).", deny.policy_id)
    allow = next((p for p in hits if p.effect == "allow"), None)
    if allow:
        return Decision(True, f"Autorisé par la politique {allow.policy_id}.", allow.policy_id)
    return Decision(False, "Aucune politique n'autorise cette action (refus par défaut)."
                    + ("" if roles else " Aucun rôle attribué."))


# -- stockage ---------------------------------------------------------------------------------------
class MemoryPolicyStore:
    def __init__(self, policies=(), assignments=()):
        self.policies, self.assignments, self.decisions = list(policies), list(assignments), []

    def load(self):
        return self.policies, self.assignments

    def log(self, req: Request, d: Decision) -> None:
        self.decisions.append((req, d))


class SqlPolicyStore:
    """Tables agent_policies, role_assignments, policy_decisions (compte de l'App)."""

    def __init__(self, sql, table):
        self.sql, self.t = sql, table

    def load(self):
        pol = self.sql.query(f"SELECT * FROM {self.t('agent_policies')} WHERE status = 'actif'")["rows"]
        asg = self.sql.query(f"SELECT principal_type, principal, role, scope_type, scope_id FROM "
                             f"{self.t('role_assignments')} WHERE status = 'actif'")["rows"]
        return ([Policy.from_row(r) for r in pol],
                [Assignment(r["principal_type"], r["principal"], r["role"], r["scope_type"], r.get("scope_id")) for r in asg])

    def log(self, req: Request, d: Decision) -> None:
        self.sql.execute(f"""
            INSERT INTO {self.t('policy_decisions')} (decision_id, decided_at, principal, action, resource, allowed,
              enforced, mode, policy_id, reason, agent_id, conversation_id)
            VALUES (:id, current_timestamp(), :p, :a, :r, CAST(:al AS BOOLEAN), CAST(:en AS BOOLEAN), :m,
                    CAST(:pol AS STRING), CAST(:re AS STRING), CAST(:ag AS STRING), CAST(:c AS STRING))""",
            {"id": uuid.uuid4().hex, "p": req.principal or "inconnu", "a": req.action, "r": req.resource[:500],
             "al": d.allowed, "en": d.enforced, "m": d.mode, "pol": d.policy_id, "re": d.reason[:1000],
             "ag": req.agent_id or None, "c": req.conversation_id or None})


# -- point de contrôle ------------------------------------------------------------------------------
class PolicyGate:
    """Évalue une demande avec cache des politiques (ttl secondes) ; journalise les refus (et les accords si log_allows)."""

    def __init__(self, store, mode: str = "audit", ttl: float = 60.0, log_allows: bool = False):
        if mode not in MODES:
            raise ValueError(f"Mode de politique inconnu : {mode!r} (off | audit | enforce)")
        self.store, self.mode, self.ttl, self.log_allows = store, mode, ttl, log_allows
        self._cache: tuple[float, Any] | None = None
        self._lock = threading.Lock()

    def _rules(self):
        with self._lock:
            if self._cache is None or time.monotonic() - self._cache[0] > self.ttl:
                self._cache = (time.monotonic(), self.store.load())
            return self._cache[1]

    def check(self, req: Request) -> Decision:
        if self.mode == "off":
            return Decision(True, "Contrôle désactivé (mode off).", mode="off")
        try:
            policies, assignments = self._rules()
            d = evaluate(policies, assignments, req)
        except Exception as e:  # noqa: BLE001 - tables absentes, entrepôt indisponible
            d = Decision(self.mode != "enforce", f"Moteur de politiques indisponible ({type(e).__name__}).")
        d.mode = self.mode
        d.enforced = self.mode == "enforce" and not d.allowed
        if not d.allowed or self.log_allows:
            try:
                self.store.log(req, d)
            except Exception:  # noqa: BLE001 - la journalisation ne bloque pas l'appel
                pass
        return d


def tool_request(spec, ctx) -> Request:
    """Demande tool.invoke pour un outil exécuté par un agent (ressource tool:<tool_id>)."""
    return Request(principal=(getattr(ctx, "user_email", "") or "").lower(), action="tool.invoke",
                   resource=f"tool:{spec.tool_id}",
                   attrs={"status": spec.status, "owner": spec.owner or None, "read_only": spec.read_only},
                   agent_id=getattr(ctx, "agent_id", "") or "", conversation_id=getattr(ctx, "conversation_id", "") or "")
