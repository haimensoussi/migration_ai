"""Client Model Serving (format OpenAI chat completions, appel d'outils)."""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from databricks.sdk import WorkspaceClient

MAX_OUTPUT_TOKENS = 8192   # jetons produits au plus par appel du modèle


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

    # 2048 coupait les appels d'outils volumineux (export Excel rédigé, rapport) : arguments tronqués à {"titre"}.
    # Seuls les jetons réellement produits sont facturés ; la limite ne ralentit pas les réponses courtes.
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
            raise ModelError(f"Appel du modèle {endpoint} en échec : {e}") from e
        choices = resp.get("choices") or []
        if not choices:
            raise ModelError(f"Réponse vide du modèle {endpoint}.")
        return {"message": normalize_message(choices[0].get("message") or {}), "usage": resp.get("usage") or {},
                "finish_reason": choices[0].get("finish_reason")}

    def chat_stream(self, endpoint: str, messages: list[dict], tools: list[dict] | None = None,
                    temperature: float | None = None, max_tokens: int = MAX_OUTPUT_TOKENS,
                    on_text: Callable[[str], None] | None = None) -> dict:
        """Même résultat que chat, mais le texte arrive au fil de l'eau (SSE) et est transmis à on_text.

        Si le flux ne démarre pas (HTTP en erreur, réseau), repli sur l'appel classique : la réponse reste servie.
        """
        import requests
        body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens, "stream": True,
                                "stream_options": {"include_usage": True}}
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature
        emitted = []

        def relay(delta: str):
            emitted.append(delta)
            if on_text:
                on_text(delta)
        try:
            headers = self.w.config.authenticate()
            r = requests.post(f"{self.w.config.host.rstrip('/')}/serving-endpoints/{endpoint}/invocations",
                              json=body, headers=headers, stream=True, timeout=(15, 300))
            if r.status_code != 200:
                raise ModelError(f"HTTP {r.status_code}")
            with r:
                return assemble_stream((ln.decode("utf-8", "replace") for ln in r.iter_lines() if ln), relay)
        except Exception as e:  # noqa: BLE001
            if emitted:   # flux interrompu en cours de réponse : pas de second appel (texte déjà affiché)
                raise ModelError(f"Flux du modèle {endpoint} interrompu : {e}") from e
            return self.chat(endpoint, messages, tools=tools, temperature=temperature, max_tokens=max_tokens)


def assemble_stream(lines: Iterable[str], on_text: Callable[[str], None] | None = None) -> dict:
    """Reconstitue un message complet à partir des lignes SSE (format OpenAI chat.completion.chunk).

    Pur et testable : texte transmis delta par delta, appels d'outils reconstitués par index, jetons du dernier bloc.
    """
    text, calls, usage, finish = [], {}, {}, None
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if chunk.get("error"):
            raise ModelError(str(chunk["error"])[:500])
        for k, v in (chunk.get("usage") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                usage[k] = v
        for ch in chunk.get("choices") or []:
            delta = ch.get("delta") or {}
            content = delta.get("content")
            if isinstance(content, list):
                content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
            if content:
                text.append(content)
                if on_text:
                    on_text(content)
            for tc in delta.get("tool_calls") or []:
                c = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                fn = tc.get("function") or {}
                c["id"] = tc.get("id") or c["id"]
                c["name"] = fn.get("name") or c["name"]
                c["arguments"] += fn.get("arguments") or ""
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
    msg: dict[str, Any] = {"content": "".join(text)}
    if calls:
        msg["tool_calls"] = [{"id": c["id"], "function": {"name": c["name"], "arguments": c["arguments"]}}
                             for _, c in sorted(calls.items())]
    if not msg["content"] and not calls:
        raise ModelError("Réponse vide du modèle (flux).")
    return {"message": normalize_message(msg), "usage": usage, "finish_reason": finish}


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
