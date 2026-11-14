"""Orchestration multi-agents DISCOVERY (superviseur -> agents spécialisés).

Un agent devient superviseur lorsque sa liste d'outils contient des entrées « agent:<agent_id> ».
Le superviseur reçoit un outil dynamique `ask_agent` dont l'argument `agent` est restreint (enum)
aux agents délégués valides. Garde-fous :
- un seul niveau de délégation (un superviseur ne peut pas être délégué) ;
- nombre maximal de délégations par tour ;
- chaque agent délégué s'exécute avec sa propre configuration (outils, tables autorisées) et
  l'identité de l'utilisateur ;
- les outils soumis à validation humaine ne sont jamais exécutés par délégation ;
- chaque appel d'outil d'un agent délégué est journalisé sous l'identifiant de cet agent.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from backend.agent_runtime import AgentConfig, AgentRuntime, ToolEvent
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec

AGENT_PREFIX = "agent:"
ASK_AGENT = "ask_agent"
MAX_DELEGATIONS = 4
SUB_MAX_ITERATIONS = 6

SUPERVISOR_GUIDE = """
## Rôle de superviseur (orchestration DISCOVERY)
- Tu coordonnes des agents spécialisés grâce à l'outil ask_agent ; n'utilise que les agents proposés.
- Découpe la demande et confie à chaque agent une question autonome et précise, avec le contexte utile.
- Au plus {max_delegations} délégations par demande ; n'interroge pas deux fois un agent pour la même chose.
- Rédige une synthèse unique en indiquant, pour chaque partie, l'agent qui l'a produite (« Selon <agent> »).
- N'invente aucun résultat. Si un agent échoue, est indisponible ou demande une validation humaine, dis-le tel quel.
- Si aucun agent n'est pertinent, réponds avec tes propres outils ou indique la limite.
""".strip()


def sub_agent_ids(tool_ids: list[str] | None) -> list[str]:
    return [t[len(AGENT_PREFIX):] for t in (tool_ids or []) if str(t).startswith(AGENT_PREFIX)]


def is_supervisor(cfg: AgentConfig) -> bool:
    return bool(sub_agent_ids(cfg.tool_ids))


def plain_tools(tool_ids: list[str] | None) -> list[str]:
    return [t for t in (tool_ids or []) if not str(t).startswith(AGENT_PREFIX)]


@dataclass
class SubAgent:
    cfg: AgentConfig
    description: str


class Orchestrator:
    def __init__(self, model, base_registry: ToolRegistry, ctx_factory: Callable[[], ToolContext],
                 load_agent: Callable[[str], tuple[dict, AgentConfig] | None],
                 on_sub_event: Callable[[str, ToolEvent], None] | None = None,
                 max_delegations: int = MAX_DELEGATIONS):
        self.model, self.base, self.ctx_factory, self.load_agent = model, base_registry, ctx_factory, load_agent
        self.on_sub_event, self.max_delegations = on_sub_event, max_delegations

    def _resolve(self, cfg: AgentConfig) -> tuple[dict[str, SubAgent], list[str]]:
        subs, warnings = {}, []
        for aid in dict.fromkeys(sub_agent_ids(cfg.tool_ids)):
            if aid == cfg.agent_id:
                warnings.append("Un agent ne peut pas se déléguer à lui-même : entrée ignorée.")
                continue
            got = None
            try:
                got = self.load_agent(aid)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Agent délégué {aid} illisible : {e}")
                continue
            if not got:
                warnings.append(f"Agent délégué {aid} introuvable, archivé ou non accessible : ignoré.")
                continue
            meta, scfg = got
            if is_supervisor(scfg):
                warnings.append(f"« {scfg.name} » est lui-même superviseur : un seul niveau de délégation est autorisé.")
                continue
            label, n = scfg.name or aid, 2
            while label in subs:
                label, n = f"{scfg.name} ({n})", n + 1
            subs[label] = SubAgent(scfg, (meta.get("description") or "").strip())
        return subs, warnings

    def prepare(self, cfg: AgentConfig, on_tool_event: Callable[[ToolEvent], None] | None = None
                ) -> tuple[AgentRuntime, AgentConfig, list[str]]:
        """Renvoie (runtime, configuration d'exécution, avertissements) pour un tour de conversation."""
        subs, warnings = self._resolve(cfg)
        if not subs:
            if sub_agent_ids(cfg.tool_ids):
                warnings.append("Aucun agent délégué valide : l'agent répond seul.")
            return (AgentRuntime(self.model, self.base, self.ctx_factory(), on_tool_event=on_tool_event),
                    replace(cfg, tool_ids=plain_tools(cfg.tool_ids)), warnings)

        catalogue = "; ".join(f"« {k} » : {v.description or 'sans description'}" for k, v in subs.items())
        spec = ToolSpec(
            tool_id=ASK_AGENT, name="Déléguer à un agent", category="Orchestration",
            description=("Confie une question précise à un agent spécialisé DISCOVERY et renvoie sa réponse. "
                         f"Agents disponibles : {catalogue}"),
            input_schema={"type": "object", "properties": {
                "agent": {"type": "string", "enum": list(subs), "description": "Nom exact de l'agent délégué"},
                "question": {"type": "string", "description": "Question autonome, avec le contexte nécessaire"}},
                "required": ["agent", "question"]},
            output_schema={"type": "object"}, executor="tools.orchestration:ask_agent",
            identity="utilisateur", requires_confirmation=False, read_only=True)
        registry = ToolRegistry(list(self.base.specs.values()) + [spec])
        count = {"n": 0}

        def delegate(agent: str, question: str) -> dict:
            if count["n"] >= self.max_delegations:
                raise ToolError(f"Limite de {self.max_delegations} délégations atteinte pour cette demande.")
            count["n"] += 1
            sub = subs[agent]
            scfg = replace(sub.cfg, tool_ids=plain_tools(sub.cfg.tool_ids),
                           max_iterations=min(sub.cfg.max_iterations or SUB_MAX_ITERATIONS, SUB_MAX_ITERATIONS))
            sid = sub.cfg.agent_id
            log = (lambda ev: self.on_sub_event(sid, ev)) if self.on_sub_event else None
            res = AgentRuntime(self.model, self.base, self.ctx_factory(), on_tool_event=log).run(
                scfg, [{"role": "user", "content": question}])
            outils = [{"outil": e.tool_id, "statut": e.status} for e in res.events]
            if res.pending:
                return {"agent": sub.cfg.name, "statut": "validation_requise", "outils": outils,
                        "message": (f"L'agent « {sub.cfg.name} » demande une validation humaine pour l'outil "
                                    f"{res.pending['tool']} : cette action n'est pas exécutée par délégation. "
                                    "Utilisez directement cet agent dans Chat & Test.")}
            return {"agent": sub.cfg.name, "statut": "succes", "reponse": res.final_text or "",
                    "outils": outils, "latence_ms": res.latency_ms}

        ctx = self.ctx_factory()
        ctx.delegate = delegate
        guide = SUPERVISOR_GUIDE.format(max_delegations=self.max_delegations)
        run_cfg = replace(cfg, tool_ids=plain_tools(cfg.tool_ids) + [ASK_AGENT],
                          instructions=f"{(cfg.instructions or '').rstrip()}\n\n{guide}")
        return AgentRuntime(self.model, registry, ctx, on_tool_event=on_tool_event), run_cfg, warnings
