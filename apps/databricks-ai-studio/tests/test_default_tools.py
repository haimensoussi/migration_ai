import json
from types import SimpleNamespace

from backend.agent_repository import DEFAULT_TOOLS, AgentRepository, with_default_tools
from tools.catalog import BUILTIN_TOOLS


class Sql:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((statement, params or {}))

    def query(self, statement, params=None, row_limit=None):
        return {"rows": [], "columns": [], "truncated": False}


def repo():
    return AgentRepository(Sql(), SimpleNamespace(table=lambda n: f"c.s.{n}", max_iterations=6))


CFG = {"model_endpoint": "m", "instructions": "Instructions de test.", "knowledge_tables": []}


def test_defaults_are_published_read_only_builtins():
    specs = {t.tool_id: t for t in BUILTIN_TOOLS}
    assert DEFAULT_TOOLS == ("render_chart", "render_kpi", "generate_report")
    assert all(specs[t].status == "publie" and specs[t].read_only and not specs[t].requires_confirmation
               for t in DEFAULT_TOOLS)


def test_with_default_tools_keeps_order_without_duplicates():
    assert with_default_tools(None) == list(DEFAULT_TOOLS)
    assert with_default_tools(["execute_sql", "render_kpi", "agent:x"]) == [
        "execute_sql", "render_kpi", "agent:x", "render_chart", "generate_report"]


def test_create_agent_adds_defaults_to_version_1():
    r = repo()
    r.create_agent({"name": "A"}, {**CFG, "tool_ids": ["execute_sql"]}, "u")
    tools = json.loads(next(p["tools"] for s, p in r.sql.calls if "agent_versions" in s))
    assert tools == ["execute_sql", "render_chart", "render_kpi", "generate_report"]


def test_create_agent_without_tools_and_caller_cfg_untouched():
    r = repo()
    cfg = {**CFG}
    r.create_agent({"name": "A"}, cfg, "u")
    tools = json.loads(next(p["tools"] for s, p in r.sql.calls if "agent_versions" in s))
    assert tools == list(DEFAULT_TOOLS) and "tool_ids" not in cfg
