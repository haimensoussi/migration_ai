import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.tool_registry import ToolContext, ToolError, ToolPermissionError
from tools import http_tools as h


def resolver(ip):
    return lambda host, port, *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


def test_mask_url_hides_signatures():
    m = h.mask_url("https://x.logic.azure.com:443/workflows/1/triggers/manual/paths/invoke?api-version=2016&sp=%2Fx&sv=1.0&sig=SECRET")
    assert "SECRET" not in m and "sig=***" in m and "api-version=2016" in m


@pytest.mark.parametrize("url,ip,msg", [
    ("ftp://a.fr/x", "8.8.8.8", "http:// ou https://"),
    ("https://user:pw@a.fr/", "8.8.8.8", "identifiants"),
    ("https://a.fr:22/", "8.8.8.8", "Port refusé"),
    ("https://a.fr/", "10.1.2.3", "non publique"),
    ("https://a.fr/", "127.0.0.1", "non publique"),
    ("http://metadata/", "169.254.169.254", "non publique"),
    ("https://a.fr/", "100.64.0.1", "non publique"),
])
def test_ssrf_and_url_rules(url, ip, msg):
    with pytest.raises(ToolPermissionError, match=msg):
        h.check_target(url, resolver(ip))


def test_public_target_ok_and_allowlist(monkeypatch):
    assert h.check_target("https://prod.westeurope.logic.azure.com/x", resolver("20.1.2.3")) == \
        ("prod.westeurope.logic.azure.com", 443)
    monkeypatch.setenv(h.ALLOWED_ENV, "logic.azure.com, sncf.fr")
    assert h.check_target("https://prod.logic.azure.com/x", resolver("20.1.2.3"))[1] == 443
    with pytest.raises(ToolPermissionError, match="Domaine non autorisé"):
        h.check_target("https://evil.example/x", resolver("20.1.2.3"))


def test_dns_failure_is_reported_as_network_error():
    def boom(*a):
        raise socket.gaierror(-2, "Name or service not known")
    with pytest.raises(ToolError, match="DNS"):
        h.check_target("https://introuvable.example/x", boom)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path.startswith("/redirige"):
            return self._send(302, "", "text/plain", {"Location": "http://10.0.0.1/admin?token=abc"})
        if self.path.startswith("/absent"):
            return self._send(404, "introuvable", "text/plain")
        return self._send(200, json.dumps({"ok": True}))

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self._send(202, json.dumps({"recu": json.loads(self.rfile.read(n)), "ct": self.headers.get("Content-Type")}))


@pytest.fixture
def server(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(h, "check_target", lambda url, resolver=None: ("127.0.0.1", srv.server_port))
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_calls_return_status_without_following_redirects(server):
    ctx = ToolContext(sql=None, workspace=None)
    ok = h.http_call(ctx, server + "/ping?sig=SECRET")
    assert ok["statut_http"] == 200 and ok["json"] == {"ok": True} and "SECRET" not in ok["url"]
    red = h.http_call(ctx, server + "/redirige")
    assert red["statut_http"] == 302 and "non suivie" in red["redirection"] and "abc" not in red["redirection"]
    ko = h.http_call(ctx, server + "/absent")
    assert ko["statut_http"] == 404 and not ko["succes_http"] and ko["reponse"] == "introuvable"
    post = h.http_call(ctx, server + "/flux", "POST", {"texte": "Bonjour"})
    assert post["statut_http"] == 202 and post["json"] == {"recu": {"texte": "Bonjour"}, "ct": "application/json"}


def test_forbidden_headers_and_methods(server):
    ctx = ToolContext(sql=None, workspace=None)
    with pytest.raises(ToolPermissionError, match="En-tête refusé"):
        h.http_call(ctx, server, headers={"Authorization": "Bearer x"})
    with pytest.raises(ToolPermissionError, match="Méthode refusée"):
        h.http_call(ctx, server, method="TRACE")


def test_catalog_entry_requires_confirmation():
    from tools.catalog import BUILTIN_TOOLS
    t = next(t for t in BUILTIN_TOOLS if t.tool_id == "http_call")
    assert t.requires_confirmation and not t.read_only and t.input_schema["required"] == ["url"]


def test_logged_arguments_are_masked():
    import types
    from backend.agent_repository import AgentRepository
    from backend.agent_runtime import ToolEvent

    class Sql:
        def __init__(self):
            self.params = None

        def execute(self, statement, params=None):
            self.params = params
    sql = Sql()
    repo = AgentRepository(sql, types.SimpleNamespace(table=lambda n: n))
    repo.log_tool_call("c", "a", "u", ToolEvent("1", "http_call", {"url": "https://x.fr/p?sig=SECRET"}, "succes",
                                                result={"statut_http": 200}, duration_ms=3))
    assert "SECRET" not in sql.params["args"] and "sig=***" in sql.params["args"]
