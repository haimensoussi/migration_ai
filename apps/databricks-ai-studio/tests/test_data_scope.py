import pytest

from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS

ROWS = [{"tableName": n, "isTemporary": "false"} for n in
        ("agents", "conversations", "data_frequentation_gares", "data_regularite_mensuelle_ter", "tools")]


class Sql:
    def __init__(self):
        self.seen = []

    def query(self, statement, params=None, row_limit=None):
        self.seen.append(statement)
        return {"rows": ROWS, "columns": ["tableName", "isTemporary"], "truncated": False}


def run(args, env=None, monkeypatch=None):
    reg = ToolRegistry(BUILTIN_TOOLS)
    sql = Sql()
    return reg.run(reg.specs["list_tables"], ToolContext(sql=sql, workspace=None), args), sql


def test_default_scope_lists_only_data_tables(monkeypatch):
    for k in ("AI_STUDIO_DATA_CATALOG", "AI_STUDIO_DATA_SCHEMA", "AI_STUDIO_DATA_PREFIX"):
        monkeypatch.delenv(k, raising=False)
    r, sql = run({})
    assert "`dataops_dev`.`ai_studio`" in sql.seen[0]
    assert [t["table"] for t in r["tables"]] == ["dataops_dev.ai_studio.data_frequentation_gares",
                                                 "dataops_dev.ai_studio.data_regularite_mensuelle_ter"]
    assert "défaut" in r["zone_de_donnees"]


def test_other_schema_is_not_filtered_and_partial_args_rejected():
    r, _ = run({"catalog": "dataops_dev", "schema": "description_du_reseau_bronze"})
    assert r["nombre"] == 5 and "zone_de_donnees" not in r
    with pytest.raises(ToolError, match="ET le schéma"):
        run({"catalog": "dataops_dev"})


def test_scope_configurable_and_validated(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_DATA_SCHEMA", "autre")
    monkeypatch.setenv("AI_STUDIO_DATA_PREFIX", "")
    r, sql = run({})
    assert "`autre`" in sql.seen[0] and r["nombre"] == 5
    monkeypatch.setenv("AI_STUDIO_DATA_SCHEMA", "x; DROP")
    with pytest.raises(Exception):
        run({})
