"""Réponses au fil de l'eau : reconstitution du flux SSE, boucle d'agent, affichage provisoire, repli."""
import json
import types

import pytest

from backend.agent_runtime import AgentConfig, AgentRuntime
from backend.model_client import ModelClient, ModelError, assemble_stream
from backend.tool_registry import ToolContext, ToolRegistry
from tools.catalog import BUILTIN_TOOLS
from ui.live_text import CURSOR, LiveText


def sse(*chunks):
    return [f"data: {json.dumps(c, ensure_ascii=False)}" for c in chunks] + ["data: [DONE]"]


def ch(delta=None, finish=None, usage=None):
    c = {"choices": [{"delta": delta or {}, "index": 0, "finish_reason": finish}]}
    if usage:
        c["usage"] = usage
    return c


# Format observé sur databricks-claude-sonnet-4-6 (2026-11-22) : usage partiel à chaque bloc, complet au dernier
TEXT = sse(ch({"content": "Bonjour à "}, usage={"prompt_tokens": 19, "completion_tokens": None}),
           ch({"content": "toi !"}), ch({"content": ""}, "stop", {"prompt_tokens": 19, "completion_tokens": 32,
                                                                  "total_tokens": 51}))
TOOL = sse(ch({"content": "Je regarde."}),
           ch({"content": None, "tool_calls": [{"index": 0, "id": "toolu_1", "type": "function",
                                                "function": {"name": "get_weather", "arguments": ""}}]}),
           ch({"tool_calls": [{"index": 0, "function": {"arguments": "{\"ville"}}]}),
           ch({"tool_calls": [{"index": 0, "function": {"arguments": "\": \"Lyon\"}"}}]}),
           ch({"content": ""}, "tool_calls", {"prompt_tokens": 581, "completion_tokens": 82, "total_tokens": 663}))


def test_text_stream_deltas_and_usage():
    got = []
    r = assemble_stream(TEXT, got.append)
    assert got == ["Bonjour à ", "toi !"] and r["message"] == {"role": "assistant", "content": "Bonjour à toi !"}
    assert r["usage"] == {"prompt_tokens": 19, "completion_tokens": 32, "total_tokens": 51}
    assert r["finish_reason"] == "stop"


def test_tool_call_reassembled_from_fragments():
    r = assemble_stream(TOOL)
    assert r["finish_reason"] == "tool_calls" and r["message"]["content"] == "Je regarde."
    assert r["message"]["tool_calls"] == [{"id": "toolu_1", "type": "function",
                                           "function": {"name": "get_weather", "arguments": '{"ville": "Lyon"}'}}]


def test_stream_errors():
    with pytest.raises(ModelError, match="vide"):
        assemble_stream(["data: [DONE]"])
    with pytest.raises(ModelError, match="quota"):
        assemble_stream(sse({"error": {"message": "quota"}}))
    assert assemble_stream([": ping", "data: {pas du json"] + TEXT)["message"]["content"] == "Bonjour à toi !"


class StreamModel:
    """1er appel : annonce + appel d'outil ; 2e appel : réponse finale. Les deux en flux."""
    def __init__(self):
        self.n = 0

    def chat(self, *a, **k):
        raise AssertionError("chat ne doit pas être appelé quand on_text est branché")

    def chat_stream(self, endpoint, messages, tools=None, temperature=None, on_text=None):
        self.n += 1
        if self.n == 1:
            lines = sse(ch({"content": "Je calcule."}),
                        ch({"tool_calls": [{"index": 0, "id": "c1", "function": {
                            "name": "render_smartart", "arguments": json.dumps({
                                "type": "processus", "titre": "Démarche",
                                "elements": [{"texte": "A"}, {"texte": "B"}]})}}]}), ch({}, "tool_calls"))
        else:
            lines = sse(ch({"content": "Voici "}), ch({"content": "le schéma."}, "stop", {"total_tokens": 7}))
        return assemble_stream(lines, on_text)


def test_runtime_streams_every_model_call():
    rt = AgentRuntime(StreamModel(), ToolRegistry(BUILTIN_TOOLS), ToolContext(sql=None, workspace=None))
    seen = []
    rt.on_text = seen.append
    cfg = AgentConfig(agent_id="a", version=1, name="A", model_endpoint="m", instructions="",
                      tool_ids=["render_smartart"], knowledge_tables=[])
    res = rt.run(cfg, [{"role": "user", "content": "schéma"}])
    assert seen == [None, "Je calcule.", None, "Voici ", "le schéma."]
    assert res.final_text == "Voici le schéma." and res.events[0].status == "succes" and res.usage["total_tokens"] == 7


def test_runtime_without_on_text_keeps_block_call():
    class Block:
        def chat(self, *a, **k):
            return {"message": {"role": "assistant", "content": "ok"}, "usage": {}}

        def chat_stream(self, *a, **k):
            raise AssertionError("pas de flux sans on_text")
    rt = AgentRuntime(Block(), ToolRegistry(BUILTIN_TOOLS), ToolContext(sql=None, workspace=None))
    cfg = AgentConfig(agent_id="a", version=1, name="A", model_endpoint="m", instructions="", tool_ids=[],
                      knowledge_tables=[])
    assert rt.run(cfg, [{"role": "user", "content": "x"}]).final_text == "ok"


class Box:
    def __init__(self):
        self.shown = []

    def markdown(self, t):
        self.shown.append(t)


def test_live_text_throttles_and_keeps_announcement():
    t = iter([1.0, 1.01, 1.2, 1.3])
    box = Box()
    live = LiveText(box, clock=lambda: next(t))
    live(None)
    live("Je ")          # 1.0 : affiché
    live("regarde.")     # 1.01 : trop tôt, cumulé
    live(None)           # nouvel appel du modèle : annonce conservée
    live("Résultat")     # 1.2 : affiché
    live.close()
    assert box.shown == ["Je " + CURSOR, "Je regarde.\n\nRésultat" + CURSOR, "Je regarde.\n\nRésultat"]


def test_chat_stream_falls_back_to_block_call_when_stream_fails(monkeypatch):
    import requests
    w = types.SimpleNamespace(config=types.SimpleNamespace(host="https://h", authenticate=lambda: {}))
    mc = ModelClient(w)
    monkeypatch.setattr(requests, "post", lambda *a, **k: types.SimpleNamespace(status_code=400))
    monkeypatch.setattr(mc, "chat", lambda *a, **k: {"message": {"role": "assistant", "content": "bloc"}, "usage": {}})
    assert mc.chat_stream("m", [{"role": "user", "content": "x"}])["message"]["content"] == "bloc"
