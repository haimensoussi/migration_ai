"""Client Model Serving (format chat completions avec appel d'outils), sous l'identite de l'utilisateur."""
from __future__ import annotations

from typing import Any

MAX_OUTPUT_TOKENS = 8192


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, w):
        self.w = w

    def chat(self, endpoint: str, messages: list[dict], tools: list[dict] | None = None,
             temperature: float | None = None, max_tokens: int = MAX_OUTPUT_TOKENS) -> dict:
        body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature
        try:
            resp = self.w.api_client.do("POST", f"/serving-endpoints/{endpoint}/invocations", body=body)
        except Exception as e:  # noqa: BLE001
            raise ModelError(f"Appel du modele {endpoint} en echec : {e}") from e
        choices = resp.get("choices") or []
        if not choices:
            raise ModelError(f"Reponse vide du modele {endpoint}.")
        return {"message": normalize_message(choices[0].get("message") or {}), "usage": resp.get("usage") or {},
                "finish_reason": choices[0].get("finish_reason")}


def normalize_message(msg: dict) -> dict:
    content = msg.get("content")
    if isinstance(content, list):  # blocs de contenu
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    out = {"role": "assistant", "content": content or ""}
    if msg.get("tool_calls"):
        out["tool_calls"] = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or "{}"}}
            for c in msg["tool_calls"]]
    return out
