"""HakimAI Voix : configuration de session, clé éphémère, liste blanche et exécution des outils."""
import io
import json
import urllib.error
from pathlib import Path

import pytest

from backend import hakim, voice
from backend.tool_registry import ToolContext, ToolRegistry, ToolSpec

ROOT = Path(__file__).resolve().parents[1]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_voice_specs_whitelist_read_only():
    specs = voice.voice_specs(hakim.TOOLS)
    assert sorted(s.tool_id for s in specs) == sorted(voice.VOICE_TOOLS)
    assert all(s.read_only and not s.requires_confirmation for s in specs)


def test_voice_specs_drop_write_tool_even_if_whitelisted():
    w = ToolSpec("lister_agents", "x", "c", "d", {"type": "object", "properties": {}}, {}, "tools.x:y",
                 read_only=False, requires_confirmation=True)
    assert voice.voice_specs([w]) == []


def test_session_config_shape():
    body = voice.session_config(voice.voice_specs(hakim.TOOLS), "gpt-realtime", "marin")
    s = body["session"]
    assert s["type"] == "realtime" and s["model"] == "gpt-realtime"
    assert s["audio"]["output"]["voice"] == "marin"
    assert {t["name"] for t in s["tools"]} == set(voice.VOICE_TOOLS)
    assert all(t["type"] == "function" and "parameters" in t for t in s["tools"])
    assert body["expires_after"]["seconds"] <= 600
    assert "LECTURE SEULE" in s["instructions"]


def test_mint_sends_key_server_side_and_returns_only_ephemeral():
    seen = {}

    def opener(req, timeout):
        seen["auth"] = req.get_header("Authorization")
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return _Resp(json.dumps({"value": "ek_123", "expires_at": 99}).encode())

    out = voice.mint_client_secret("sk-perm", {"session": {"type": "realtime"}}, opener=opener)
    assert out == {"value": "ek_123", "expires_at": 99}
    assert "sk-perm" not in json.dumps(out)
    assert seen["auth"] == "Bearer sk-perm" and seen["url"] == voice.CLIENT_SECRETS_URL


def test_mint_network_error_explains_policy():
    def opener(req, timeout):
        raise urllib.error.URLError("Temporary failure in name resolution")

    with pytest.raises(voice.VoiceError, match="politique réseau"):
        voice.mint_client_secret("sk", {}, opener=opener)


def test_mint_http_error_does_not_leak_key():
    def opener(req, timeout):
        raise urllib.error.HTTPError(voice.CLIENT_SECRETS_URL, 401, "x", {},
                                     io.BytesIO(b'{"error": {"message": "Incorrect API key"}}'))

    with pytest.raises(voice.VoiceError) as e:
        voice.mint_client_secret("sk-secret", {}, opener=opener)
    assert "401" in str(e.value) and "sk-secret" not in str(e.value)


def test_mint_requires_key():
    with pytest.raises(voice.VoiceError):
        voice.mint_client_secret("", {})


def _registry(fn_path="tests.test_voice:_fake_tool"):
    spec = ToolSpec("lister_agents", "Agents", "c", "d",
                    {"type": "object", "properties": {"recherche": {"type": "string"}}, "required": []}, {}, fn_path)
    return ToolRegistry([spec])


def _fake_tool(ctx, recherche=""):
    return {"agents": [{"nom": "A", "q": recherche}], "_ui_points": [1, 2, 3]}


def test_run_tool_refuses_non_whitelisted(monkeypatch):
    reg = ToolRegistry([ToolSpec("creer_agent", "x", "c", "d", {"type": "object", "properties": {}}, {},
                                 "tools.x:y", read_only=False, requires_confirmation=True)])
    ev, out = voice.run_tool(reg, ToolContext(sql=None, workspace=None), "creer_agent", "{}", "c1")
    assert ev.status == "erreur" and "non autorisé" in json.loads(out)["erreur"]


def test_run_tool_executes_and_strips_ui(monkeypatch):
    from backend import tool_registry
    monkeypatch.setattr(tool_registry, "resolve_executor", lambda p: _fake_tool)
    ev, out = voice.run_tool(_registry(), ToolContext(sql=None, workspace=None), "lister_agents",
                             '{"recherche": "qualité"}', "c2")
    assert ev.status == "succes" and ev.call_id == "c2" and ev.arguments == {"recherche": "qualité"}
    data = json.loads(out)
    assert data["agents"][0]["q"] == "qualité" and "_ui_points" not in data


def test_run_tool_bad_json_and_unknown_arg(monkeypatch):
    from backend import tool_registry
    monkeypatch.setattr(tool_registry, "resolve_executor", lambda p: _fake_tool)
    ev, out = voice.run_tool(_registry(), ToolContext(sql=None, workspace=None), "lister_agents", "{pas json", "c3")
    assert ev.status == "erreur" and "JSON" in out
    ev, out = voice.run_tool(_registry(), ToolContext(sql=None, workspace=None), "lister_agents", '{"x": 1}', "c4")
    assert ev.status == "erreur" and "inconnus" in out


def test_run_tool_technical_error_is_labelled(monkeypatch):
    from backend import tool_registry

    def boom(ctx, **k):
        raise ValueError("panne")
    monkeypatch.setattr(tool_registry, "resolve_executor", lambda p: boom)
    ev, out = voice.run_tool(_registry(), ToolContext(sql=None, workspace=None), "lister_agents", "{}", "c5")
    assert ev.status == "erreur" and "Erreur technique" in ev.error


def test_output_truncated():
    out = voice._truncate({"x": "a" * 10000})
    assert len(out) <= voice.MAX_OUTPUT_CHARS + 20 and out.endswith("(tronqué)")


def test_status_and_settings(monkeypatch):
    monkeypatch.delenv("AI_STUDIO_VOICE_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert voice.status()[0] is False
    monkeypatch.setenv("AI_STUDIO_VOICE_ENABLED", "true")
    ok, msg = voice.status()
    assert not ok and "openai-key" in msg
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    monkeypatch.setenv("AI_STUDIO_VOICE_MAX_SECONDS", "99999")
    assert voice.status() == (True, "") and voice.settings()["max_seconds"] == 1800


def test_no_key_in_repo_files():
    for p in [ROOT / "app.yaml", ROOT / "backend" / "voice.py", ROOT / "views" / "hakim_voix.py",
              ROOT / "ui" / "voice_call" / "frontend" / "index.html"]:
        txt = p.read_text(encoding="utf-8")
        assert "sk-proj-" not in txt and "sk-live" not in txt


def test_frontend_protocol_and_guards():
    js = (ROOT / "ui" / "voice_call" / "frontend" / "index.html").read_text(encoding="utf-8")
    for needle in ("streamlit:componentReady", "streamlit:setComponentValue", "streamlit:render",
                   "response.function_call_arguments.done", "function_call_output", "oai-events",
                   "S.args.secret.nonce === S.startSeq", "S.args.error.for === S.startSeq"):
        assert needle in js
    assert "OPENAI_API_KEY" not in js
