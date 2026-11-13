"""Moteur agentique : modèle -> choix d'outil -> exécution -> observation -> poursuite.

- N'expose au modèle que les outils publiés et associés à l'agent.
- Valide les arguments, journalise chaque appel (callback), borne le nombre d'itérations.
- Les outils marqués `requires_confirmation` suspendent la boucle jusqu'à une décision humaine.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec

MAX_TOOL_RESULT_CHARS = 12000


@dataclass
class AgentConfig:
    agent_id: str
    version: int
    name: str
    model_endpoint: str
    instructions: str
    tool_ids: list[str] = field(default_factory=list)
    knowledge_tables: list[str] = field(default_factory=list)
    temperature: float | None = 0.1
    max_iterations: int = 6


@dataclass
class ToolEvent:
    call_id: str
    tool_id: str
    arguments: dict
    status: str  # succes | erreur | refuse
    result: Any = None
    error: str | None = None
    duration_ms: int = 0


@dataclass
class TurnResult:
    messages: list[dict]                 # conversation complète (avec message système)
    new_messages: list[dict]             # messages ajoutés pendant ce tour
    events: list[ToolEvent]
    final_text: str | None = None
    pending: dict | None = None          # appel d'outil en attente de validation humaine
    latency_ms: int = 0
    usage: dict = field(default_factory=dict)


def system_prompt(cfg: AgentConfig, tools: dict[str, ToolSpec]) -> str:
    parts = [cfg.instructions.strip(), "", "## Cadre d'exécution (Databricks AI Studio)"]
    parts.append("- Tu agis avec les droits Unity Catalog de l'utilisateur connecté ; un refus d'accès est normal et doit être signalé tel quel.")
    if tools:
        parts.append("- Outils disponibles : " + ", ".join(sorted(tools)) + ". N'invente pas de résultat d'outil.")
    else:
        parts.append("- Aucun outil n'est disponible : réponds sans exécuter d'action.")
    if cfg.knowledge_tables:
        parts.append("- Tables autorisées (noms complets à utiliser) : " + ", ".join(cfg.knowledge_tables))
    parts.append("- SQL en lecture seule uniquement. Réponds en français, de façon concise, en citant les tables utilisées.")
    return "\n".join(parts)


class AgentRuntime:
    def __init__(self, model, registry: ToolRegistry, ctx: ToolContext,
                 on_tool_event: Callable[[ToolEvent], None] | None = None):
        self.model, self.registry, self.ctx, self.on_tool_event = model, registry, ctx, on_tool_event

    # -- API publique -------------------------------------------------------
    def run(self, cfg: AgentConfig, history: list[dict], approvals: dict[str, bool] | None = None) -> TurnResult:
        tools = self.registry.for_agent(cfg.tool_ids)
        messages = [{"role": "system", "content": system_prompt(cfg, tools)}] + list(history)
        return self._loop(cfg, messages, approvals or {})

    def resume(self, cfg: AgentConfig, messages: list[dict], approvals: dict[str, bool]) -> TurnResult:
        return self._loop(cfg, list(messages), approvals)

    # -- Boucle ---------------------------------------------------------------
    def _loop(self, cfg: AgentConfig, messages: list[dict], approvals: dict[str, bool]) -> TurnResult:
        start, t0, events, usage = len(messages), time.monotonic(), [], {}
        tools = self.registry.for_agent(cfg.tool_ids)
        payload = [s.to_openai() for s in tools.values()] or None
        self.ctx.allowed_tables = list(cfg.knowledge_tables)

        def result(**kw):
            return TurnResult(messages=messages, new_messages=messages[start:], events=events,
                              latency_ms=int((time.monotonic() - t0) * 1000), usage=usage, **kw)

        model_calls = 0
        while True:
            calls = unanswered_calls(messages)
            if not calls:
                if model_calls >= cfg.max_iterations:
                    text = f"Arrêt : nombre maximal d'itérations ({cfg.max_iterations}) atteint."
                    messages.append({"role": "assistant", "content": text})
                    return result(final_text=text)
                resp = self.model.chat(cfg.model_endpoint, messages, tools=payload, temperature=cfg.temperature)
                model_calls += 1
                for k, v in (resp.get("usage") or {}).items():
                    if isinstance(v, (int, float)):
                        usage[k] = usage.get(k, 0) + v
                msg = resp["message"]
                messages.append(msg)
                calls = msg.get("tool_calls") or []
                if not calls:
                    return result(final_text=msg.get("content") or "")
            for call in calls:
                spec = tools.get(call["function"]["name"])
                if spec and spec.requires_confirmation:
                    decision = approvals.get(call["id"])
                    if decision is None:
                        return result(pending={"call": call, "tool": spec.tool_id,
                                               "arguments": _parse_args(call)})
                    if decision is False:
                        ev = ToolEvent(call["id"], spec.tool_id, _parse_args(call), "refuse",
                                       error="Exécution refusée par l'utilisateur.")
                        self._record(ev, messages, events)
                        continue
                ev = self._execute(call, tools)
                self._record(ev, messages, events)

    def _execute(self, call: dict, tools: dict[str, ToolSpec]) -> ToolEvent:
        name, t0 = call["function"]["name"], time.monotonic()
        args: dict = {}
        try:
            args = _parse_args(call, strict=True)
            spec = tools.get(name)
            if spec is None:
                raise ToolError(f"Outil « {name} » non autorisé pour cet agent.")
            out = self.registry.run(spec, self.ctx, args)
            return ToolEvent(call["id"], name, args, "succes", result=out,
                             duration_ms=int((time.monotonic() - t0) * 1000))
        except ToolError as e:
            msg = str(e)
        except Exception as e:  # noqa: BLE001 - erreur technique remontée au modèle
            msg = f"Erreur technique ({type(e).__name__}) : {e}"
        return ToolEvent(call["id"], name, args, "erreur", error=msg[:2000],
                         duration_ms=int((time.monotonic() - t0) * 1000))

    def _record(self, ev: ToolEvent, messages: list[dict], events: list[ToolEvent]) -> None:
        payload = {"status": ev.status, "result": ev.result} if ev.status == "succes" else {"status": ev.status, "error": ev.error}
        content = json.dumps(payload, ensure_ascii=False, default=str)
        if len(content) > MAX_TOOL_RESULT_CHARS:
            content = content[:MAX_TOOL_RESULT_CHARS] + "... [résultat tronqué]"
        messages.append({"role": "tool", "tool_call_id": ev.call_id, "content": content})
        events.append(ev)
        if self.on_tool_event:
            try:
                self.on_tool_event(ev)
            except Exception:  # noqa: BLE001 - la journalisation ne bloque pas la conversation
                pass


def _parse_args(call: dict, strict: bool = False) -> dict:
    raw = call["function"].get("arguments") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as e:
        if strict:
            raise ToolError(f"Arguments JSON invalides : {e}") from e
        return {"_brut": raw}
    return val if isinstance(val, dict) else {"_valeur": val}


def unanswered_calls(messages: list[dict]) -> list[dict]:
    """Appels d'outils du dernier message assistant sans réponse `tool`."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m["role"] == "assistant":
            answered = {x.get("tool_call_id") for x in messages[i + 1:] if x["role"] == "tool"}
            return [c for c in (m.get("tool_calls") or []) if c["id"] not in answered]
        if m["role"] == "user":
            return []
    return []


def new_id() -> str:
    return uuid.uuid4().hex
