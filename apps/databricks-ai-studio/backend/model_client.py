"""Client Model Serving (format OpenAI chat completions, appel d'outils)."""
from __future__ import annotations

from typing import Any

from databricks.sdk import WorkspaceClient


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, w: WorkspaceClient):
        self.w = w

    def list_chat_endpoints(self) -> list[dict]:
        """Endpoints prêts de tâche llm/v1/chat visibles par l'identité courante."""
        resp = self.w.api_client.do("GET", "/api/2.0/serving-endpoints")
        out = []
        for e in resp.get("endpoints", []):
            if e.get("task") == "llm/v1/chat" and (e.get("state") or {}).get("ready") == "READY":
                out.append({"name": e["name"], "task": e.get("task")})
        return sorted(out, key=lambda x: x["name"])

    def chat(self, endpoint: str, messages: list[dict], tools: list[dict] | None = None,
             temperature: float | None = None, max_tokens: int = 2048) -> dict:
        body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature
        try:
            resp = self.w.api_client.do("POST", f"/serving-endpoints/{endpoint}/invocations", body=body)
        except Exception as e:  # noqa: BLE001
            raise ModelError(f"Appel du modèle {endpoint} en échec : {e}") from e
        choices = resp.get("choices") or []
        if not choices:
            raise ModelError(f"Réponse vide du modèle {endpoint}.")
        return {"message": normalize_message(choices[0].get("message") or {}), "usage": resp.get("usage") or {}}


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
