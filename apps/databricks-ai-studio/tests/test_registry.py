import pytest

from backend.tool_registry import ToolContext, ToolError, ToolRegistry, resolve_executor, validate_args
from tools.catalog import BUILTIN_TOOLS
from tools.common import split_name


def test_catalog_contracts():
    ids = [t.tool_id for t in BUILTIN_TOOLS]
    assert len(ids) == len(set(ids)) == 12
    for t in BUILTIN_TOOLS:
        assert t.input_schema["type"] == "object"
        assert callable(resolve_executor(t.executor))
        assert t.to_openai()["function"]["name"] == t.tool_id
        back = type(t).from_row({**t.to_row(), "requires_confirmation": str(t.requires_confirmation).lower()})
        assert back == t


def test_only_tools_package_executable():
    with pytest.raises(ToolError):
        resolve_executor("os:system")


def test_validate_args():
    schema = {"type": "object", "properties": {"q": {"type": "string"}, "n": {"type": "integer", "maximum": 5}},
              "required": ["q"]}
    assert validate_args(schema, {"q": "x", "n": "9"}) == {"q": "x", "n": 5}
    with pytest.raises(ToolError):
        validate_args(schema, {})
    with pytest.raises(ToolError):
        validate_args(schema, {"q": "x", "z": 1})
    with pytest.raises(ToolError):
        validate_args(schema, {"q": 3})


def test_split_name():
    assert split_name("a.b.c", 3) == ["a", "b", "c"]
    with pytest.raises(ToolError):
        split_name("a.b;drop", 2)


def test_registry_hides_unpublished():
    reg = ToolRegistry(BUILTIN_TOOLS)
    assert "run_job" not in reg.for_agent(["run_job", "execute_sql"])
    assert "execute_sql" in reg.for_agent(["run_job", "execute_sql"])


def test_execute_sql_allowlist():
    from tools.sql_tools import execute_sql

    class FakeSql:
        def query(self, statement, params=None, row_limit=None):
            return {"columns": ["v"], "rows": [{"v": "1"}], "truncated": False}

    ctx = ToolContext(sql=FakeSql(), workspace=None, allowed_tables=["a.b.c"], max_rows=10)
    assert execute_sql(ctx, "SELECT * FROM a.b.c", 50)["limite"] == 10
    with pytest.raises(ToolError):
        execute_sql(ctx, "SELECT * FROM x.y.z")
    with pytest.raises(ToolError):
        execute_sql(ctx, "SELECT * FROM c")
    with pytest.raises(ToolError):
        execute_sql(ctx, "DROP TABLE a.b.c")
