import pytest

from backend import tool_builder as tb
from backend.tool_registry import ToolContext, ToolError, ToolPermissionError, ToolRegistry
from tools.custom_tools import placeholders, uc_call

T = "dataops_dev.description_du_reseau_bronze.gares_de_voyageurs"


class Sql:
    def __init__(self):
        self.calls = []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, params, row_limit))
        return {"columns": ["Nom_Gare"], "rows": [{"Nom_Gare": "Rennes"}], "truncated": False}


def spec(sql_txt, params=(("departement", "string", True),), max_rows=50):
    d = tb.normalize({"name": "Gares", "description": "x" * 40, "sql": sql_txt, "max_rows": max_rows,
                      "parameters": [{"name": n, "type": t, "required": r, "description": n} for n, t, r in params]})
    return tb.build_spec(d, "u@sncf.fr")


def test_placeholders_ignore_strings_comments_casts_and_variant_paths():
    q = "SELECT a::string, raw:champ, '10:30 :x', \"q :y\", `c:z` FROM t WHERE d = :dep AND (:seg IS NULL OR s = :seg) -- :c\n/* :w */"
    assert placeholders(q) == ["dep", "seg"]


def test_values_are_bound_never_inlined():
    sql = Sql()
    s = spec(f"SELECT Nom_Gare FROM {T} WHERE left(`Code commune`, 2) = :departement")
    evil = "35' OR '1'='1"
    out = ToolRegistry([s]).run(s, ToolContext(sql=sql, workspace=None, max_rows=200), {"departement": evil})
    stmt, params, limit = sql.calls[0]
    assert evil not in stmt and params == {"departement": evil} and limit == 50
    assert out["nombre_lignes"] == 1 and out["limite"] == 50


def test_limit_capped_by_context_and_optional_param_is_null():
    sql = Sql()
    s = spec(f"SELECT Nom_Gare FROM {T} WHERE (:seg IS NULL OR `Segment(s) DRG` = :seg)",
             params=(("seg", "string", False),), max_rows=1000)
    ToolRegistry([s]).run(s, ToolContext(sql=sql, workspace=None, max_rows=200), {})
    assert sql.calls[0][1] == {"seg": None} and sql.calls[0][2] == 200


def test_tampered_config_is_refused_at_run_time():
    s = spec(f"SELECT Nom_Gare FROM {T} WHERE `Code commune` = :departement")
    ctx = ToolContext(sql=Sql(), workspace=None)
    s.config["sql"] = f"DELETE FROM {T}"
    with pytest.raises(ToolPermissionError):
        ToolRegistry([s]).run(s, ctx, {"departement": "35"})
    s.config["sql"] = "SELECT * FROM other.schema.table WHERE a = :departement"
    with pytest.raises(ToolPermissionError, match="non déclarées"):
        ToolRegistry([s]).run(s, ctx, {"departement": "35"})
    s.config["sql"] = f"SELECT * FROM {T} WHERE a = :departement AND b = :autre"
    with pytest.raises(ToolError, match="incohérents"):
        ToolRegistry([s]).run(s, ctx, {"departement": "35"})


def test_uc_function_call_and_identifier_safety():
    assert uc_call({"function": "c.s.score", "params": ["d", "n"]}) == "SELECT `c`.`s`.`score`(:d, :n) AS resultat"
    assert uc_call({"function": "c.s.f", "params": [], "kind": "table"}) == "SELECT * FROM `c`.`s`.`f`()"
    for bad in ({"function": "c.s.f; DROP TABLE x"}, {"function": "c.s"}, {"function": "c.s.f", "params": ["x) --"]}):
        with pytest.raises(ToolPermissionError):
            uc_call(bad)
    d = tb.normalize({"name": "Score", "description": "y" * 40, "type": "uc_function", "function": "c.s.score",
                      "parameters": [{"name": "d", "type": "integer", "required": True, "description": "d"}]})
    s = tb.build_spec(d, "u@sncf.fr")
    sql = Sql()
    ToolRegistry([s]).run(s, ToolContext(sql=sql, workspace=None), {"d": "7"})
    assert sql.calls[0][0] == "SELECT `c`.`s`.`score`(:d) AS resultat" and sql.calls[0][1] == {"d": 7}
