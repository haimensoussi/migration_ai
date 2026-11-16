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

import time
from dataclasses import dataclass, replace
from typing import Callable

from backend.agent_runtime import AgentConfig, AgentRuntime, ToolEvent
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec

AGENT_PREFIX = "agent:"
ASK_AGENT = "ask_agent"
MAX_DELEGATIONS = 6        # échanges agent -> agent par demande de l'utilisateur
MAX_SECONDS = 120          # au-delà, plus aucun nouvel échange n'est lancé
SUB_MAX_ITERATIONS = 6

SUPERVISOR_GUIDE = """
## Rôle de superviseur (orchestration DISCOVERY)
- Tu échanges avec des agents partenaires grâce à l'outil ask_agent ; n'utilise que les agents proposés.
- Découpe la demande et pose à chaque agent une question autonome et précise, avec le contexte utile.
- Tu peux relancer un agent pour préciser sa réponse : il garde le fil de vos échanges pendant cette demande.
- Si un agent a produit une carte (champ « cartes »), elle est affichée à l'utilisateur : mentionne-la (titre, nombre de points) sans recopier les coordonnées.
- Au plus {max_delegations} échanges par demande ; ne repose pas une question déjà traitée.
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
    label: str = ""          # « Victor, le veilleur » pour l'affichage


class Orchestrator:
    def __init__(self, model, base_registry: ToolRegistry, ctx_factory: Callable[[], ToolContext],
                 load_agent: Callable[[str], tuple[dict, AgentConfig] | None],
                 on_sub_event: Callable[[str, ToolEvent], None] | None = None,
                 max_delegations: int = MAX_DELEGATIONS, max_seconds: float = MAX_SECONDS):
        self.model, self.base, self.ctx_factory, self.load_agent = model, base_registry, ctx_factory, load_agent
        self.on_sub_event, self.max_delegations, self.max_seconds = on_sub_event, max_delegations, max_seconds

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
            from backend import personas
            shown = personas.display({**meta, "name": scfg.name})
            desc = " ".join(x for x in ((meta.get("tagline") or "").strip(), (meta.get("description") or "").strip()) if x)
            subs[label] = SubAgent(scfg, (f"{shown} ({personas.AI_BADGE}). " if shown != scfg.name else "") + desc, shown)
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
            description=("Pose une question à un agent partenaire DISCOVERY et renvoie sa réponse. Tu peux le "
                         "relancer : il garde le fil des questions précédentes de cette demande. "
                         f"Agents disponibles : {catalogue}"),
            input_schema={"type": "object", "properties": {
                "agent": {"type": "string", "enum": list(subs), "description": "Nom exact de l'agent délégué"},
                "question": {"type": "string", "description": "Question autonome, avec le contexte nécessaire"}},
                "required": ["agent", "question"]},
            output_schema={"type": "object"}, executor="tools.orchestration:ask_agent",
            identity="utilisateur", requires_confirmation=False, read_only=True)
        registry = ToolRegistry(list(self.base.specs.values()) + [spec])
        count = {"n": 0}
        threads: dict[str, list[dict]] = {}       # fil de discussion par partenaire, le temps de la demande
        rounds: dict[str, int] = {}
        t0 = time.monotonic()

        def delegate(agent: str, question: str) -> dict:
            if count["n"] >= self.max_delegations:
                raise ToolError(f"Limite de {self.max_delegations} échanges atteinte pour cette demande.")
            if time.monotonic() - t0 > self.max_seconds:
                raise ToolError(f"Temps maximal de {int(self.max_seconds)} s atteint : aucun nouvel échange lancé.")
            count["n"] += 1
            rounds[agent] = rounds.get(agent, 0) + 1
            sub = subs[agent]
            scfg = replace(sub.cfg, tool_ids=plain_tools(sub.cfg.tool_ids),
                           max_iterations=min(sub.cfg.max_iterations or SUB_MAX_ITERATIONS, SUB_MAX_ITERATIONS))
            sid = sub.cfg.agent_id
            log = (lambda ev: self.on_sub_event(sid, ev)) if self.on_sub_event else None
            history = threads.get(agent, []) + [{"role": "user", "content": question}]
            res = AgentRuntime(self.model, self.base, self.ctx_factory(), on_tool_event=log).run(scfg, history)
            outils = [{"outil": e.tool_id, "statut": e.status} for e in res.events]
            if res.pending:
                return {"agent": sub.cfg.name, "agent_affiche": sub.label or sub.cfg.name, "statut": "validation_requise", "outils": outils, "echange": rounds[agent],
                        "message": (f"L'agent « {sub.cfg.name} » demande une validation humaine pour l'outil "
                                    f"{res.pending['tool']} : cette action n'est pas exécutée par délégation. "
                                    "Utilisez directement cet agent dans Chat & Test.")}
            threads[agent] = [m for m in res.messages if m["role"] != "system"]
            out = {"agent": sub.cfg.name, "agent_affiche": sub.label or sub.cfg.name, "statut": "succes",
                   "reponse": res.final_text or "",
                   "outils": outils, "latence_ms": res.latency_ms, "echange": rounds[agent]}
            maps = [e for e in res.events if e.tool_id == "render_map" and e.status == "succes" and isinstance(e.result, dict)]
            if maps:   # cartes du partenaire : résumé pour le modèle, données complètes pour l'affichage (_ui)
                out["cartes"] = [{"titre": m.result.get("titre"), "nombre_points": m.result.get("nombre_points")} for m in maps]
                out["_ui_maps"] = [{**m.result, "_ui_query": m.arguments.get("query", "")} for m in maps]
            charts = [e for e in res.events if e.tool_id == "render_chart" and e.status == "succes"
                      and isinstance(e.result, dict) and e.result.get("_ui_chart")]
            if charts:   # graphiques du partenaire : même principe que les cartes
                out["graphiques"] = [{"titre": c.result.get("titre"), "lignes": c.result.get("lignes")} for c in charts]
                out["_ui_charts"] = [c.result["_ui_chart"] for c in charts]
            return out

        ctx = self.ctx_factory()
        ctx.delegate = delegate
        guide = SUPERVISOR_GUIDE.format(max_delegations=self.max_delegations)
        run_cfg = replace(cfg, tool_ids=plain_tools(cfg.tool_ids) + [ASK_AGENT],
                          instructions=f"{(cfg.instructions or '').rstrip()}\n\n{guide}")
        return AgentRuntime(self.model, registry, ctx, on_tool_event=on_tool_event), run_cfg, warnings
