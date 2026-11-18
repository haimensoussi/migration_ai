"""Setup Wizard : configuration initiale d'une organisation en 6 étapes, enregistrée au fil de l'eau.

Persistance : une clé saas_settings par étape (setup.<etape>), écrite en une seule opération ; l'avancement est
déduit des clés présentes (pas de compteur séparé qui pourrait diverger). L'activation écrit setup.status.
Droits : lecture = settings.read, écriture et activation = settings.manage, appliqués par TenantService.
Les contrôles de ressources (entrepôt, modèle, schéma) sont injectés (SetupChecker) : la logique reste testable.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Callable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.saas.models import TenantContext, ValidationError, norm_email

STEPS = (("organisation", "Organisation"), ("infrastructure", "Infrastructure"), ("ia", "Intelligence artificielle"),
         ("securite", "Sécurité"), ("modules", "Modules"), ("validation", "Validation"))
DATA_STEPS = tuple(s for s, _ in STEPS[:-1])     # étapes à saisir ; la 6e contrôle et active

MODULES = {
    "agent_studio": ("Agent Studio", ""),
    "agent_marketplace": ("Agent Marketplace", ""),
    "tool_marketplace": ("Tool Marketplace", ""),
    "workflow_marketplace": ("Workflow Marketplace", "Appels sortants (Power Automate, HTTP) bloqués par le réseau "
                             "serverless tant que les domaines ne sont pas autorisés."),
    "knowledge": ("Data & Knowledge (RAG)", "Nécessite le schéma de données provisionné ; la recherche vectorielle "
                  "(ressource payante) sera soumise à validation."),
    "finops": ("FinOps", "Coûts estimés à partir de la consommation mesurée par l'application."),
}
LANGUAGES = ("fr", "en")
WAREHOUSE_ID = re.compile(r"^[0-9a-f]{16}$")
ENDPOINT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,62}$")
DOMAIN = re.compile(r"^(?=.{4,100}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$")


def _text(d: dict, k: str, lo: int, hi: int, label: str) -> str:
    v = str(d.get(k) or "").strip()
    if not lo <= len(v) <= hi:
        raise ValidationError(f"{label} : {lo} à {hi} caractères.")
    return v


def _int(d: dict, k: str, lo: int, hi: int, label: str) -> int:
    try:
        v = int(d.get(k))
    except (TypeError, ValueError):
        raise ValidationError(f"{label} : nombre entier attendu.") from None
    if not lo <= v <= hi:
        raise ValidationError(f"{label} : entre {lo} et {hi}.")
    return v


def _list(v) -> list[str]:
    items = v.split(",") if isinstance(v, str) else list(v or [])
    out = []
    for x in (str(i).strip() for i in items):
        if x and x not in out:
            out.append(x)
    return out


def _organisation(d: dict, roles) -> dict:
    tz = str(d.get("timezone") or "").strip()
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError(f"Fuseau horaire inconnu : {tz!r}") from None
    lang = d.get("language")
    if lang not in LANGUAGES:
        raise ValidationError(f"Langue non prise en charge : {lang!r}")
    return {"display_name": _text(d, "display_name", 2, 120, "Nom affiché"),
            "contact_email": norm_email(d.get("contact_email")), "language": lang, "timezone": tz}


def _infrastructure(d: dict, roles) -> dict:
    wid = str(d.get("warehouse_id") or "").strip().lower()
    if not WAREHOUSE_ID.match(wid):
        raise ValidationError("Identifiant d'entrepôt SQL invalide (16 caractères hexadécimaux).")
    return {"warehouse_id": wid, "max_rows": _int(d, "max_rows", 10, 5000, "Lignes maximum par requête"),
            "sql_timeout_s": _int(d, "sql_timeout_s", 10, 600, "Délai SQL (s)")}


def _ia(d: dict, roles) -> dict:
    default = str(d.get("default_endpoint") or "").strip()
    if not ENDPOINT.match(default):
        raise ValidationError("Nom d'endpoint de modèle invalide.")
    allowed = _list(d.get("allowed_endpoints"))
    bad = [e for e in allowed if not ENDPOINT.match(e)]
    if bad:
        raise ValidationError(f"Endpoints invalides : {', '.join(bad)}")
    if default not in allowed:
        allowed.insert(0, default)
    try:
        temp = float(d.get("temperature"))
    except (TypeError, ValueError):
        raise ValidationError("Température : nombre attendu.") from None
    if not 0.0 <= temp <= 1.0:
        raise ValidationError("Température : entre 0 et 1.")
    return {"default_endpoint": default, "allowed_endpoints": allowed, "temperature": round(temp, 2),
            "max_tokens": _int(d, "max_tokens", 256, 32000, "Jetons de sortie maximum")}


def _securite(d: dict, roles) -> dict:
    role = d.get("default_member_role")
    if role not in roles or role == "owner":
        raise ValidationError("Rôle par défaut invalide (le rôle propriétaire ne peut pas être attribué par défaut).")
    domains = [x.lower().lstrip("@") for x in _list(d.get("allowed_domains"))]
    bad = [x for x in domains if not DOMAIN.match(x)]
    if not domains or bad:
        raise ValidationError("Domaines e-mail autorisés : au moins un domaine valide" +
                              (f" (invalides : {', '.join(bad)})" if bad else "") + ".")
    return {"default_member_role": role, "allowed_domains": domains,
            "write_approval": bool(d.get("write_approval", True))}


def _modules(d: dict, roles) -> dict:
    unknown = set(d) - set(MODULES)
    if unknown:
        raise ValidationError(f"Modules inconnus : {', '.join(sorted(unknown))}")
    out = {m: bool(d.get(m, False)) for m in MODULES}
    if not any(out.values()):
        raise ValidationError("Activez au moins un module.")
    return out


VALIDATORS: dict[str, Callable[[dict, dict], dict]] = {
    "organisation": _organisation, "infrastructure": _infrastructure, "ia": _ia, "securite": _securite,
    "modules": _modules}


class SetupChecker(Protocol):
    """Contrôles de ressources réelles. Chaque méthode renvoie (ok, détail) ; une exception = erreur technique."""
    def warehouse(self, warehouse_id: str) -> tuple[bool, str]: ...
    def endpoint(self, name: str) -> tuple[bool, str]: ...
    def schema(self, full_name: str) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class Check:
    check_id: str
    label: str
    status: str          # ok | echec | erreur (technique) | avertissement
    blocking: bool
    detail: str = ""

    @property
    def blocks(self) -> bool:
        return self.blocking and self.status in ("echec", "erreur")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class SetupWizard:
    def __init__(self, service, now: Callable[[], str] = _now):
        self.svc, self.now = service, now

    # -- Lecture -----------------------------------------------------------------------------------
    def state(self, ctx: TenantContext) -> dict:
        return self.state_from(self.svc.get_settings(ctx))

    @staticmethod
    def state_from(s: dict) -> dict:
        """État déduit des paramètres déjà lus (l'appelant a contrôlé les droits)."""
        steps = {k: s.get(f"setup.{k}") for k in DATA_STEPS}
        status = s.get("setup.status") or {}
        activated_at = status.get("activated_at", "")
        changed = [k for k, v in steps.items() if v and activated_at and v.get("_saved_at", "") > activated_at]
        done = [k for k in DATA_STEPS if steps[k]]
        nxt = next((k for k in DATA_STEPS if not steps[k]), "validation")
        return {"steps": steps, "done": done, "next": nxt, "active": status.get("state") == "active",
                "activated_at": activated_at, "activated_by": status.get("activated_by", ""),
                "changed_since_activation": changed}

    # -- Écriture ----------------------------------------------------------------------------------
    def save_step(self, ctx: TenantContext, step: str, data: dict) -> dict:
        if step not in VALIDATORS:
            raise ValidationError(f"Étape inconnue : {step}")
        st = self.state(ctx)
        missing = [k for k in DATA_STEPS[:DATA_STEPS.index(step)] if not st["steps"][k]]
        if missing:
            raise ValidationError(f"Complétez d'abord : {', '.join(dict(STEPS)[k] for k in missing)}.")
        clean = VALIDATORS[step](dict(data or {}), self.svc.roles())
        clean |= {"_saved_at": self.now(), "_saved_by": ctx.identity.email}
        self.svc.put_setting(ctx, f"setup.{step}", clean)
        return clean

    # -- Contrôles et activation -----------------------------------------------------------------------
    def checks(self, ctx: TenantContext, checker: SetupChecker) -> list[Check]:
        st = self.state(ctx)
        s = st["steps"]
        out = [Check("etapes", "Étapes 1 à 5 complétées", "ok" if len(st["done"]) == len(DATA_STEPS) else "echec", True,
                     "" if len(st["done"]) == len(DATA_STEPS) else
                     "Manquantes : " + ", ".join(dict(STEPS)[k] for k in DATA_STEPS if not s[k]))]

        def probe(cid, label, fn, arg, blocking):
            try:
                ok, detail = fn(arg)
                out.append(Check(cid, label, "ok" if ok else ("echec" if blocking else "avertissement"), blocking, detail))
            except Exception as e:  # noqa: BLE001 - erreur technique, distincte d'un échec de contrôle
                out.append(Check(cid, label, "erreur", blocking, f"Erreur technique : {e}"))

        if s["infrastructure"]:
            probe("entrepot", f"Entrepôt SQL {s['infrastructure']['warehouse_id']} accessible", checker.warehouse,
                  s["infrastructure"]["warehouse_id"], True)
        if s["ia"]:
            probe("modele", f"Modèle par défaut {s['ia']['default_endpoint']} prêt", checker.endpoint,
                  s["ia"]["default_endpoint"], True)
            for e in s["ia"]["allowed_endpoints"]:
                if e != s["ia"]["default_endpoint"]:
                    probe(f"modele:{e}", f"Modèle autorisé {e} prêt", checker.endpoint, e, False)
        tenant = self.svc.get_tenant(ctx)   # relu : le statut du schéma peut avoir changé depuis l'ouverture
        knowledge = bool(s["modules"] and s["modules"].get("knowledge"))
        if tenant.data_schema_status != "provisionne":
            out.append(Check("schema", f"Schéma de données {tenant.data_schema} provisionné",
                             "echec" if knowledge else "avertissement", knowledge,
                             "Non provisionné : demandez-le à l'administrateur de la plateforme."))
        else:
            probe("schema", f"Schéma de données {tenant.data_schema} accessible", checker.schema, tenant.data_schema,
                  knowledge)
        if s["securite"] and ctx.can("users.read"):
            domains = set(s["securite"]["allowed_domains"])
            outside = [m.user_email for m in self.svc.list_members(ctx)
                       if m.status == "actif" and m.user_email.split("@")[-1] not in domains]
            out.append(Check("domaines", "Membres actifs dans les domaines autorisés",
                             "avertissement" if outside else "ok", False,
                             ("Hors domaines : " + ", ".join(outside)) if outside else ""))
        if s["modules"]:
            for m, (label, prereq) in MODULES.items():
                if s["modules"].get(m) and prereq and m != "knowledge":
                    out.append(Check(f"module:{m}", f"Prérequis {label}", "avertissement", False, prereq))
        return out

    def activate(self, ctx: TenantContext, checker: SetupChecker) -> list[Check]:
        """Active l'organisation si aucun contrôle bloquant n'échoue ; renvoie les contrôles dans tous les cas."""
        result = self.checks(ctx, checker)
        blocking = [c for c in result if c.blocks]
        if blocking:
            raise ValidationError("Activation impossible : " + " ; ".join(f"{c.label} ({c.detail or c.status})"
                                                                          for c in blocking))
        self.svc.put_setting(ctx, "setup.status", {
            "state": "active", "activated_at": self.now(), "activated_by": ctx.identity.email,
            "checks": [{"id": c.check_id, "status": c.status} for c in result]})
        return result
