import json

from backend.agent_runtime import AgentConfig, AgentRuntime, unanswered_calls
from backend.tool_registry import ToolContext, ToolRegistry, ToolSpec

ECHO = ToolSpec(tool_id="echo", name="Echo", category="Test", description="renvoie le texte",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={"type": "object"}, executor="tools.testing:echo")
DANGER = ToolSpec(tool_id="danger", name="Danger", category="Test", description="action sensible",
                  input_schema={"type": "object", "properties": {}}, output_schema={"type": "object"},
                  executor="tools.testing:echo_empty", requires_confirmation=True, read_only=False)


class ScriptedModel:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, endpoint, messages, tools=None, temperature=None, max_tokens=2048):
        self.calls.append({"messages": list(messages), "tools": tools})
        return {"message": self.replies.pop(0), "usage": {"total_tokens": 10}}


def call(i, name, args):
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def cfg(**kw):
    base = dict(agent_id="a", version=1, name="t", model_endpoint="m", instructions="Tu es un test.",
                tool_ids=["echo", "danger"], max_iterations=4)
    base.update(kw)
    return AgentConfig(**base)


def make(replies, events=None):
    rt = AgentRuntime(ScriptedModel(replies), ToolRegistry([ECHO, DANGER]), ToolContext(None, None),
                      on_tool_event=(events.append if events is not None else None))
    return rt


def test_tool_loop():
    events = []
    rt = make([{"role": "assistant", "content": "", "tool_calls": [call("c1", "echo", {"text": "bonjour"})]},
               {"role": "assistant", "content": "Résultat : bonjour"}], events)
    res = rt.run(cfg(), [{"role": "user", "content": "dis bonjour"}])
    assert res.final_text == "Résultat : bonjour"
    assert [e.status for e in res.events] == ["succes"] and events[0].result == {"echo": "bonjour"}
    tool_msg = next(m for m in res.messages if m["role"] == "tool")
    assert json.loads(tool_msg["content"])["result"] == {"echo": "bonjour"}
    assert res.usage["total_tokens"] == 20
    sent_tools = rt.model.calls[0]["tools"]
    assert {t["function"]["name"] for t in sent_tools} == {"echo", "danger"}


def test_invalid_args_and_unknown_tool_are_reported_to_model():
    rt = make([{"role": "assistant", "content": "", "tool_calls": [call("c1", "echo", {}),
                                                                     call("c2", "rm_rf", {})]},
               {"role": "assistant", "content": "désolé"}])
    res = rt.run(cfg(), [{"role": "user", "content": "x"}])
    assert [e.status for e in res.events] == ["erreur", "erreur"]
    assert "manquants" in res.events[0].error and "non autorisé" in res.events[1].error


def test_max_iterations():
    loop = [{"role": "assistant", "content": "", "tool_calls": [call(f"c{i}", "echo", {"text": "x"})]} for i in range(5)]
    res = make(loop).run(cfg(max_iterations=2), [{"role": "user", "content": "boucle"}])
    assert "maximal" in res.final_text and len(res.events) == 2


def test_human_confirmation_pause_and_resume():
    rt = make([{"role": "assistant", "content": "", "tool_calls": [call("d1", "danger", {})]},
               {"role": "assistant", "content": "action refusée, je m'arrête"}])
    res = rt.run(cfg(), [{"role": "user", "content": "fais l'action"}])
    assert res.pending and res.pending["tool"] == "danger" and not res.events
    assert unanswered_calls(res.messages)[0]["id"] == "d1"
    res2 = rt.resume(cfg(), res.messages, {"d1": False})
    assert res2.events[0].status == "refuse" and res2.final_text.startswith("action refusée")


def test_tools_not_in_agent_are_hidden():
    rt = make([{"role": "assistant", "content": "ok"}])
    rt.run(cfg(tool_ids=[]), [{"role": "user", "content": "x"}])
    assert rt.model.calls[0]["tools"] is None
