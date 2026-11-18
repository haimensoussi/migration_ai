"""Agent Studio : agents d'une organisation, versionnés, publiés, testés et exécutés sur Model Serving.

Règles (contrôlées à l'enregistrement ET à chaque exécution) :
- Prérequis : organisation activée par le Setup Wizard, module Agent Studio activé.
- Modèle : un des endpoints autorisés à l'étape IA.
- Actions : liste blanche SaaS. Les outils de données ne sont permis qu'avec au moins une table de connaissance,
  et les tables doivent appartenir au schéma dédié de l'organisation (provisionné) : sans liste, les outils SQL de
  la plateforme liraient tout ce que voit l'utilisateur. Les outils de la plateforme (flux, jobs, HTTP, zone SNCF)
  sont exclus.
- Droits : concevoir / tester un brouillon = agents.manage ; utiliser un agent publié = agents.use et rôle au moins
  égal au rôle minimal de l'agent.
- Versions : une version publiée n'est jamais modifiée ; modifier crée un brouillon (version suivante).
- Chaque tour est journalisé (saas_executions) et sa consommation mesurée (saas_usage).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import replace

from backend.agent_runtime import AgentConfig, AgentRuntime, TurnResult
from backend.saas.models import Conflict, TenantContext, ValidationError
from backend.saas.setup_wizard import ENDPOINT, SetupWizard
from backend.tool_registry import ToolRegistry

SAAS_VIEW_TOOLS = ("render_chart", "render_kpi", "generate_report", "export_excel", "render_map")
SAAS_DATA_TOOLS = ("execute_sql", "describe_table", "get_table_profile")
SAAS_TOOLS = SAAS_VIEW_TOOLS + SAAS_DATA_TOOLS
AGENT_ID = re.compile(r"^agt_[0-9a-f]{12}$")
TABLE_NAME = re.compile(r"^[A-Za-z0-9_]{1,128}$")
USAGE_METRICS = {"prompt_tokens": "tokens_entree", "completion_tokens": "tokens_sortie"}


def _list(v) -> list[str]:
    items = v.split(",") if isinstance(v, str) else list(v or [])
    out: list[str] = []
    for x in (str(i).strip() for i in items):
        if x and x not in out:
            out.append(x)
    return out


class AgentStudio:
    def __init__(self, service, available_tools):
        """`available_tools()` : ToolSpec publiés de la plateforme (registre existant)."""
        self.svc, self.available_tools, self.wizard = service, available_tools, SetupWizard(service)

    # -- Prérequis et catalogue d'actions ----------------------------------------------------------------
    def org_setup(self, ctx: TenantContext) -> dict:
        """Prérequis lus en interne : un utilisateur sans settings.read doit pouvoir utiliser un agent publié."""
        c = self.svc.authorize(ctx, "agents.read", "agents.setup")
        st = self.wizard.state_from(self.svc.store.settings(c.tenant_id))
        if not st["active"]:
            raise ValidationError("Organisation non activée : terminez le Setup Wizard.")
        if not (st["steps"]["modules"] or {}).get("agent_studio"):
            raise ValidationError("Module Agent Studio désactivé pour cette organisation (Setup Wizard, étape Modules).")
        return st["steps"]

    def tool_catalog(self, steps: dict) -> dict:
        """Actions autorisées aux agents SaaS : liste blanche, publiées, écritures soumises à validation si exigé."""
        approval = (steps.get("securite") or {}).get("write_approval", True)
        out = {}
        for s in self.available_tools():
            if s.tool_id in SAAS_TOOLS and s.status == "publie" and (s.read_only or s.requires_confirmation
                                                                       or not approval):
                out[s.tool_id] = s
        return out

    # -- Validation -----------------------------------------------------------------------------------
    def _validate(self, ctx: TenantContext, form: dict, steps: dict) -> tuple[str, dict]:
        f = dict(form or {})
        name = str(f.get("name") or "").strip()
        if not 2 <= len(name) <= 80:
            raise ValidationError("Nom : 2 à 80 caractères.")
        description = str(f.get("description") or "").strip()
        if len(description) > 500:
            raise ValidationError("Description : 500 caractères maximum.")
        instructions = str(f.get("instructions") or "").strip()
        if not 20 <= len(instructions) <= 8000:
            raise ValidationError("Instructions système : 20 à 8 000 caractères.")
        ia = steps.get("ia") or {}
        model = str(f.get("model_endpoint") or ia.get("default_endpoint") or "").strip()
        if not ENDPOINT.match(model) or model not in (ia.get("allowed_endpoints") or []):
            raise ValidationError(f"Modèle non autorisé pour l'organisation : {model or '(vide)'}.")
        tools = _list(f.get("tool_ids"))
        catalog = self.tool_catalog(steps)
        bad = [t for t in tools if t not in catalog]
        if bad:
            raise ValidationError("Actions non autorisées pour les agents de l'organisation : " + ", ".join(bad))
        tenant = self.svc.get_tenant(ctx)
        tables = [t.lower() for t in _list(f.get("knowledge_tables"))]
        prefix = tenant.data_schema.lower() + "."
        if tables and tenant.data_schema_status != "provisionne":
            raise ValidationError(f"Schéma de données {tenant.data_schema} non provisionné : aucune table possible.")
        outside = [t for t in tables if not (t.startswith(prefix) and TABLE_NAME.match(t[len(prefix):]))]
        if outside:
            raise ValidationError(f"Tables hors du schéma de l'organisation ({tenant.data_schema}) : "
                                  + ", ".join(outside))
        if any(t in SAAS_DATA_TOOLS for t in tools) and not tables:
            raise ValidationError("Les actions de données exigent au moins une table de connaissance de l'organisation.")
        connectors = _list(f.get("connector_ids"))
        unknown = sorted(set(connectors) - self.svc.store.connector_ids(ctx.tenant_id))
        if unknown:
            raise ValidationError("Connecteurs inconnus ou inactifs : " + ", ".join(unknown))
        try:
            temperature = float(f.get("temperature", ia.get("temperature", 0.2)))
            max_iterations = int(f.get("max_iterations", 6))
        except (TypeError, ValueError):
            raise ValidationError("Température et itérations : valeurs numériques attendues.") from None
        if not 0.0 <= temperature <= 1.0 or not 1 <= max_iterations <= 10:
            raise ValidationError("Température entre 0 et 1 ; itérations entre 1 et 10.")
        min_role = f.get("min_role") or "user"
        if min_role not in self.svc.roles():
            raise ValidationError(f"Rôle minimal inconnu : {min_role}")
        return name, {"description": description, "instructions": instructions, "model_endpoint": model,
                      "tool_ids": tools, "knowledge_tables": tables, "connector_ids": connectors,
                      "temperature": round(temperature, 2), "max_iterations": max_iterations, "min_role": min_role}

    # -- Lecture --------------------------------------------------------------------------------------
    def _can_use(self, ctx: TenantContext, cfg: dict) -> bool:
        role = self.svc.roles().get(cfg.get("min_role") or "user")
        return ctx.can("agents.use") and role is not None and ctx.role.rank >= role.rank

    def list_agents(self, ctx: TenantContext) -> list[dict]:
        """Un élément par agent : dernière version, version publiée. Sans agents.manage : agents publiés utilisables."""
        c = self.svc.authorize(ctx, "agents.read", "agents.list")
        by: dict[str, list[dict]] = {}
        for v in self.svc.store.agent_versions(c.tenant_id):
            by.setdefault(v["agent_id"], []).append(v)
        out = []
        for aid, vs in by.items():
            latest = max(vs, key=lambda v: v["version"])
            pub = next((v for v in vs if v["status"] == "publie"), None)
            if not c.can("agents.manage") and not (pub and self._can_use(c, pub["config"])):
                continue
            out.append({"agent_id": aid, "name": (pub or latest)["name"], "latest": latest, "published": pub,
                        "versions": len(vs)})
        return sorted(out, key=lambda a: a["name"].lower())

    def versions(self, ctx: TenantContext, agent_id: str) -> list[dict]:
        c = self.svc.authorize(ctx, "agents.manage", "agents.versions")
        vs = self.svc.store.agent_versions(c.tenant_id, self._aid(agent_id))
        if not vs:
            raise ValidationError("Agent introuvable dans cette organisation.")
        return vs

    @staticmethod
    def _aid(agent_id: str) -> str:
        if not AGENT_ID.match(str(agent_id or "")):
            raise ValidationError("Identifiant d'agent invalide.")
        return agent_id

    # -- Écriture -------------------------------------------------------------------------------------
    def save_draft(self, ctx: TenantContext, agent_id: str | None, form: dict) -> dict:
        """Crée l'agent (v1) ou son brouillon ; un brouillon existant est mis à jour, une version publiée jamais."""
        c = self.svc.authorize(ctx, "agents.manage", "agents.save")
        steps = self.org_setup(c)
        name, cfg = self._validate(c, form, steps)
        if agent_id is None:
            aid, version = "agt_" + uuid.uuid4().hex[:12], 1
        else:
            aid = self._aid(agent_id)
            vs = self.svc.store.agent_versions(c.tenant_id, aid)
            if not vs:
                raise ValidationError("Agent introuvable dans cette organisation.")
            latest = max(vs, key=lambda v: v["version"])
            if latest["status"] == "brouillon":
                self.svc.store.update_agent_draft(c.tenant_id, aid, latest["version"], name, cfg)
                self.svc.audit(c, "agents.save", "agent", aid, version=latest["version"], mode="maj_brouillon")
                return {"agent_id": aid, "version": latest["version"], "name": name, "config": cfg}
            version = latest["version"] + 1
        if not self.svc.store.insert_agent_version(c.tenant_id, aid, version, name, cfg, c.identity.email):
            raise Conflict("Une autre modification vient de créer cette version : rechargez l'agent.")
        self.svc.audit(c, "agents.save", "agent", aid, version=version, mode="nouvelle_version")
        return {"agent_id": aid, "version": version, "name": name, "config": cfg}

    def publish(self, ctx: TenantContext, agent_id: str, version: int) -> None:
        c = self.svc.authorize(ctx, "agents.manage", "agents.publish")
        steps = self.org_setup(c)
        aid = self._aid(agent_id)
        v = next((x for x in self.svc.store.agent_versions(c.tenant_id, aid) if x["version"] == int(version)), None)
        if not v:
            raise ValidationError("Version introuvable.")
        if v["status"] == "publie":
            return
        self._validate(c, {"name": v["name"], **v["config"]}, steps)   # règles de l'organisation à jour
        self.svc.store.publish_agent_version(c.tenant_id, aid, int(version))
        self.svc.audit(c, "agents.publish", "agent", aid, version=int(version))

    def archive(self, ctx: TenantContext, agent_id: str) -> None:
        c = self.svc.authorize(ctx, "agents.manage", "agents.archive")
        aid = self._aid(agent_id)
        self.svc.store.archive_agent(c.tenant_id, aid)
        self.svc.audit(c, "agents.archive", "agent", aid)

    # -- Exécution -----------------------------------------------------------------------------------
    def runtime_config(self, ctx: TenantContext, agent_id: str, version: int | None = None):
        """(contexte frais, AgentConfig, registre filtré). version=None : version publiée (usage) ; sinon test."""
        aid = self._aid(agent_id)
        c = self.svc.authorize(ctx, "agents.read", "agents.run")
        steps = self.org_setup(c)
        vs = self.svc.store.agent_versions(c.tenant_id, aid)
        if version is None:
            v = next((x for x in vs if x["status"] == "publie"), None)
            if not v:
                raise ValidationError("Aucune version publiée pour cet agent.")
            if not self._can_use(c, v["config"]):
                self.svc.deny(c, "agents.run", "Votre rôle ne permet pas d'utiliser cet agent.", agent=aid)
        else:
            v = next((x for x in vs if x["version"] == int(version)), None)
            if not v:
                raise ValidationError("Version introuvable.")
            if v["status"] != "publie" and not c.can("agents.manage"):
                self.svc.deny(c, "agents.run", "Seuls les concepteurs testent les versions non publiées.", agent=aid)
            if v["status"] == "publie" and not self._can_use(c, v["config"]):
                self.svc.deny(c, "agents.run", "Votre rôle ne permet pas d'utiliser cet agent.", agent=aid)
        _, cfg = self._validate(c, {"name": v["name"], **v["config"]}, steps)   # revérifié à chaque exécution
        catalog = self.tool_catalog(steps)
        registry = ToolRegistry([catalog[t] for t in cfg["tool_ids"] if t in catalog])
        ac = AgentConfig(agent_id=aid, version=v["version"], name=v["name"], model_endpoint=cfg["model_endpoint"],
                         instructions=cfg["instructions"], tool_ids=list(cfg["tool_ids"]),
                         knowledge_tables=list(cfg["knowledge_tables"]), temperature=cfg["temperature"],
                         max_iterations=cfg["max_iterations"])
        return c, ac, registry, v["status"]

    def run_turn(self, ctx: TenantContext, agent_id: str, version: int | None, history: list[dict], model,
                 tool_ctx, approvals: dict | None = None, on_tool_event=None) -> TurnResult:
        """Un tour de conversation. `tool_ctx` : ToolContext aux droits de l'utilisateur (jamais du service principal)."""
        c, ac, registry, status = self.runtime_config(ctx, agent_id, version)
        tool_ctx = replace(tool_ctx, app_sql=None, platform=None, delegate=None, user_email=c.identity.email)
        rt = AgentRuntime(model, registry, tool_ctx, on_tool_event=on_tool_event)
        exec_id, mode = uuid.uuid4().hex, ("production" if version is None else "test")
        ref = f"{ac.agent_id}:v{ac.version}"
        try:
            res = rt.run(ac, history, approvals)
        except Exception as e:  # noqa: BLE001 - journalisée puis remontée telle quelle
            self.svc.store.add_execution(c.tenant_id, exec_id, "agent", ref, c.identity.email, "erreur",
                                         str(e)[:2000], {"mode": mode, "statut_version": status})
            raise
        details = {"mode": mode, "statut_version": status, "latency_ms": res.latency_ms, "usage": res.usage,
                   "outils": [{"outil": e.tool_id, "statut": e.status} for e in res.events]}
        outcome = "en_attente" if res.pending else ("erreur" if any(e.status == "erreur" for e in res.events)
                                                     and not res.final_text else "succes")
        self.svc.store.add_execution(c.tenant_id, exec_id, "agent", ref, c.identity.email, outcome, None, details)
        rows = [{"user_email": c.identity.email, "agent_id": ac.agent_id, "model": ac.model_endpoint,
                 "metric": USAGE_METRICS[k], "quantity": v} for k, v in res.usage.items() if k in USAGE_METRICS]
        if rows:
            self.svc.store.add_usage(c.tenant_id, rows)
        return res
