import json
import types

import pytest

from backend import tool_builder as tb
from backend.agent_repository import AgentRepository
from backend.config import load_settings
from backend.tool_registry import ToolContext, ToolError, ToolPermissionError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS
from tools.custom_tools import http_parts

EXISTING = {t.tool_id: t for t in BUILTIN_TOOLS}


def draft(**kw):
    base = {"type": "http_connection", "name": "Envoi Smart Office",
            "description": "Envoie un message au flux Power Automate Smart Office et renvoie son accusé de réception.",
            "connection": "power_automate_smart_office", "method": "POST", "path": "/flows/{{flux}}/run",
            "body": {"destinataire": "{{destinataire}}", "texte": "Bonjour {{destinataire}}", "priorite": "{{priorite}}"},
            "parameters": [{"name": "flux", "type": "string", "description": "Flux", "example": "smart office"},
                           {"name": "destinataire", "type": "string", "description": "E-mail", "example": "a@sncf.fr"},
                           {"name": "priorite", "type": "integer", "description": "Priorité", "required": False,
                            "example": "2"}]}
    return tb.normalize({**base, **kw})


class Sql:
    def __init__(self, code=200, text='{"ok": true}', missing_conn=False):
        self.code, self.text, self.missing, self.calls = code, text, missing_conn, []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, params))
        if statement.startswith("DESCRIBE CONNECTION") and self.missing:
            raise RuntimeError("CONNECTION_NOT_FOUND")
        if statement.startswith("EXPLAIN"):
            return {"columns": ["plan"], "rows": [{"plan": "== Physical Plan =="}], "truncated": False}
        if statement.startswith("DESCRIBE"):
            return {"columns": ["info_name"], "rows": [{"info_name": "x"}], "truncated": False}
        return {"columns": ["status_code", "text"], "rows": [{"status_code": str(self.code), "text": self.text}],
                "truncated": False}


def test_build_marks_writes_as_confirmed_and_not_read_only():
    d = draft()
    assert tb.check(d, EXISTING, "u", Sql()).ok
    s = tb.build_spec(d, "u")
    assert s.executor == "tools.custom_tools:http_call" and s.requires_confirmation and not s.read_only
    g = tb.build_spec(draft(method="GET", body=None), "u")
    assert not g.requires_confirmation and g.read_only
    back = tb.draft_from_spec(s)
    assert back["connection"] == "power_automate_smart_office" and tb.fingerprint(back) == tb.fingerprint(d)


def test_values_rendered_in_parsed_json_and_path_encoded():
    stmt, params = http_parts(tb.build_spec(draft(), "u").config,
                              {"flux": "a/b c", "destinataire": '"},"x":"y', "priorite": 2})
    assert "conn => 'power_automate_smart_office'" in stmt and "method => 'POST'" in stmt
    assert params["path"] == "/flows/a%2Fb%20c/run"
    body = json.loads(params["json"])
    assert body == {"destinataire": '"},"x":"y', "texte": 'Bonjour "},"x":"y', "priorite": 2}   # pas d'injection JSON
    assert '"},"x":"y' not in stmt


def test_config_safety_rules():
    def errs(**kw):
        return " | ".join(tb.check(draft(**kw), EXISTING, "u").errors)
    assert "système" in errs(connection="system_ai_agent_slack_mcp")
    assert "Nom de connexion invalide" in errs(connection="x'; DROP")
    assert "Chemin invalide" in errs(path="https://evil.example/x")
    assert "Chemin invalide" in errs(path="/a/../admin")
    assert "En-tête interdit" in errs(headers={"Authorization": "Bearer abc"})
    assert "En-tête interdit" in errs(headers={"X-Test": "a\r\nHost: x"})
    assert "GET n'a pas de corps" in errs(method="GET")
    assert "non déclarés : inconnu" in errs(path="/x/{{inconnu}}/{{flux}}")
    assert "JSON invalide" in errs(body="{pas du json")
    assert "introuvable" in " ".join(tb.check(draft(), EXISTING, "u", Sql(missing_conn=True)).errors)


def test_http_errors_are_technical_errors_and_response_truncated():
    s = tb.build_spec(draft(method="GET", body=None, path="/items/{{flux}}",
                            parameters=[{"name": "flux", "type": "string", "description": "f"}]), "u")
    ctx = ToolContext(sql=Sql(code=403, text="Forbidden"), workspace=None)
    with pytest.raises(ToolError, match="HTTP 403"):
        ToolRegistry([s]).run(s, ctx, {"flux": "x"})
    big = ToolRegistry([s]).run(s, ToolContext(sql=Sql(text="x" * 9000), workspace=None), {"flux": "x"})
    assert big["statut_http"] == 200 and big["tronque"] and len(big["reponse"]) == 4000
    s.config["headers"] = {"Cookie": "a"}                       # configuration altérée
    with pytest.raises(ToolPermissionError):
        ToolRegistry([s]).run(s, ctx, {"flux": "x"})


class RepoSql:
    def __init__(self, read_only=True, owner="u@sncf.fr", exists=True):
        self.ro, self.owner, self.exists, self.writes = read_only, owner, exists, []

    def query(self, statement, params=None, row_limit=None):
        if "SELECT executor" in statement:
            return {"rows": [{"executor": "tools.custom_tools:http_call", "owner": self.owner,
                              "read_only": str(self.ro).lower()}] if self.exists else []}
        if "max(version)" in statement:
            return {"rows": [{"v": 1}]}
        return {"rows": []}

    def execute(self, statement, params=None):
        self.writes.append(statement)


def repo(sql, admins=()):
    s = types.SimpleNamespace(tool_admins=admins, table=lambda n: f"c.s.{n}")
    return AgentRepository(sql, s)


def test_only_tool_admins_publish_writing_tools():
    spec = tb.build_spec(draft(), "u@sncf.fr", status="publie")
    with pytest.raises(PermissionError, match="administrateur"):
        repo(RepoSql(exists=False)).save_custom_tool(spec, "u@sncf.fr", {"ok": True})
    assert repo(RepoSql(exists=False), ("u@sncf.fr",)).save_custom_tool(spec, "u@sncf.fr", {"ok": True}) == 1
    brouillon = tb.build_spec(draft(), "u@sncf.fr", status="brouillon")
    assert repo(RepoSql(exists=False)).save_custom_tool(brouillon, "u@sncf.fr", {"ok": True}) == 1
    with pytest.raises(PermissionError):
        repo(RepoSql(read_only=False)).set_tool_status("envoi", "publie", "u@sncf.fr")
    repo(RepoSql(read_only=False), ("u@sncf.fr",)).set_tool_status("envoi", "publie", "u@sncf.fr")
    repo(RepoSql(read_only=True)).set_tool_status("lecture", "publie", "u@sncf.fr")


def test_tool_admins_from_env(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_TOOL_ADMINS", " A@sncf.fr , b@sncf.fr,")
    assert load_settings().tool_admins == ("a@sncf.fr", "b@sncf.fr")
