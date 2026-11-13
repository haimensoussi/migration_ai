import io
import json
import urllib.error

import pytest

from backend.agent_runtime import AgentConfig, AgentRuntime
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools import power_automate as pa
from tools.catalog import BUILTIN_TOOLS

URL = "https://env.d9.environment.api.powerplatform.com:443/powerautomate/x/invoke?sig=test"


class FakeResp:
    def __init__(self, body, status=200):
        self._b, self.status = body.encode(), status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setenv(pa.FLOW_ENV, URL)

    def fake_urlopen(req, timeout):
        calls.append({"url": req.full_url, "body": json.loads(req.data), "timeout": timeout})
        return FakeResp(json.dumps({"status": "ok"}))
    monkeypatch.setattr(pa.urllib.request, "urlopen", fake_urlopen)
    return calls


def ctx():
    return ToolContext(sql=None, workspace=None, conversation_id="conv-1", user_email="a@sncf.fr")


def test_read_payload_matches_contract(sent):
    out = pa.office_read(ctx(), "outlook", "search", query="facture", question="trouve la facture")
    body = sent[0]["body"]
    assert set(body) == {"sessionId", "question", "technology", "operation", "parameters", "status",
                         "requires_confirmation"}
    assert body["sessionId"] == "conv-1" and body["parameters"] == {"query": "facture"}
    assert body["requires_confirmation"] is False and out["reponse_flux"] == {"status": "ok"}


def test_send_payload(sent):
    pa.office_send(ctx(), "outlook", "send", to="x@sncf.fr", subject="Objet", body="Bonjour")
    b = sent[0]["body"]
    assert b["parameters"] == {"to": "x@sncf.fr", "subject": "Objet", "body": "Bonjour"}
    assert b["requires_confirmation"] is True and b["status"] == "approved"


def test_recipient_domain_allowlist(sent, monkeypatch):
    monkeypatch.setenv(pa.DOMAINS_ENV, "sncf.fr")
    with pytest.raises(ToolError):
        pa.office_send(ctx(), "outlook", "send", to="x@gmail.com", subject="s", body="b")
    assert not sent


def test_missing_or_foreign_url(monkeypatch):
    monkeypatch.delenv(pa.FLOW_ENV, raising=False)
    with pytest.raises(ToolError):
        pa.office_read(ctx(), "outlook", "search")
    monkeypatch.setenv(pa.FLOW_ENV, "https://evil.example.com/hook")
    with pytest.raises(ToolError):
        pa.office_read(ctx(), "outlook", "search")


def test_http_error_reported(monkeypatch):
    monkeypatch.setenv(pa.FLOW_ENV, URL)

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad", {}, io.BytesIO(b"schema invalide"))
    monkeypatch.setattr(pa.urllib.request, "urlopen", boom)
    with pytest.raises(ToolError, match="HTTP 400"):
        pa.office_read(ctx(), "outlook", "search")


def test_send_requires_human_approval_in_runtime(sent):
    class Model:
        def __init__(self):
            self.replies = [
                {"role": "assistant", "content": "", "tool_calls": [{"id": "s1", "type": "function", "function": {
                    "name": "office_send", "arguments": json.dumps(
                        {"technology": "outlook", "operation": "send", "to": "x@sncf.fr", "subject": "s",
                         "body": "b"})}}]},
                {"role": "assistant", "content": "Message envoyé."}]

        def chat(self, *a, **k):
            return {"message": self.replies.pop(0), "usage": {}}
    reg = ToolRegistry(BUILTIN_TOOLS)
    cfg = AgentConfig(agent_id="so", version=1, name="Smart Office", model_endpoint="m",
                      instructions="Assistant bureautique de test.", tool_ids=["office_read", "office_send"])
    rt = AgentRuntime(Model(), reg, ctx())
    res = rt.run(cfg, [{"role": "user", "content": "envoie"}])
    assert res.pending and res.pending["tool"] == "office_send" and not sent  # rien n'est parti
    res2 = rt.resume(cfg, res.messages, {"s1": True})
    assert len(sent) == 1 and res2.events[0].status == "succes" and res2.final_text == "Message envoyé."
