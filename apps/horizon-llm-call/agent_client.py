"""Client de l'agent llm_call (Model Serving, format Responses) : construction de la requête,
appel et lecture des erreurs métier (codes HORIZON conservés : MISSING_INPUT, INVALID_MODEL...)."""
from __future__ import annotations

import re

# Modèles acceptés par l'agent (model_endpoints de son model_config.yml) ; le premier est le défaut de l'agent
MODELS = ["claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5"]
COST_KEYS = ("total_cost_micro_eur", "total_cost_usd")
_ERR_RE = re.compile(r"Error '([A-Z][A-Z0-9_]+): (.*)'\s*$", re.S)


class AgentCallError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def build_request(history: list[dict], system: str | None, model: str | None,
                  temperature: float | None, max_tokens: int | None) -> dict:
    """history : [{'role': 'user'|'assistant', 'content': str}] ; paramètres None non transmis (défaut de l'agent)."""
    messages = ([{"role": "system", "content": system}] if system and system.strip() else []) + [
        {"role": m["role"], "content": m["content"]} for m in history]
    custom = {k: v for k, v in {"model": model, "temperature": temperature, "max_tokens": max_tokens}.items()
              if v is not None}
    return {"input": messages, "custom_inputs": custom}


def parse_error(exc: Exception) -> AgentCallError:
    """Extrait le code métier de l'erreur renvoyée par Model Serving, sinon code technique."""
    text = str(exc)
    m = _ERR_RE.search(text)
    if m:
        return AgentCallError(m.group(1), m.group(2))
    return AgentCallError(f"TECHNIQUE_{type(exc).__name__}".upper(), text[:500])


def call_agent(w, endpoint: str, request: dict) -> dict:
    try:
        resp = w.api_client.do("POST", f"/serving-endpoints/{endpoint}/invocations", body=request)
    except Exception as e:  # noqa: BLE001 - converti en erreur lisible
        raise parse_error(e) from e
    out = resp.get("custom_outputs") or {}
    text = "".join(p.get("text", "") for it in resp.get("output", []) for p in (it.get("content") or []))
    return {"content": text or out.get("content", ""), "outputs": out}
