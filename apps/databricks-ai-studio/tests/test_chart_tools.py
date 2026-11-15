import json

import pytest

from backend.agent_runtime import AgentConfig, AgentRuntime
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS

REG = ToolRegistry(BUILTIN_TOOLS)
ROWS = [{"drg": "DRG A", "total": "1500.5"}, {"drg": "DRG B", "total": "20"}]


class Sql:
    def query(self, statement, params=None, row_limit=None):
        return {"rows": [dict(r) for r in ROWS], "columns": ["drg", "total"], "truncated": False,
                "types": {"drg": "STRING", "total": "DOUBLE"}}


def ctx():
    return ToolContext(sql=Sql(), workspace=None, user_email="a@sncf.fr", max_rows=200)


def test_published_read_only_spec():
    spec = REG.specs["render_chart"]
    assert spec.status == "publie" and spec.read_only and not spec.requires_confirmation
    assert spec.category == "Visualisation" and spec.executor == "tools.chart_tools:render_chart"


def test_chart_result_and_errors():
    r = REG.run(REG.specs["render_chart"], ctx(), {"query": "SELECT drg, total FROM t", "type": "barres",
                                                   "x": "drg", "y": "total"})
    assert r["statistiques_y"]["somme"] == 1520.5 and r["_ui_chart"]["lignes"][0]["total"] == 1500.5
    with pytest.raises(ToolError):
        REG.run(REG.specs["render_chart"], ctx(), {"query": "DROP TABLE t", "type": "barres", "x": "drg", "y": "total"})
    with pytest.raises(ToolError, match="absente"):
        REG.run(REG.specs["render_chart"], ctx(), {"query": "SELECT 1", "type": "barres", "x": "zz", "y": "total"})
    with pytest.raises(ToolError):
        REG.run(REG.specs["render_chart"], ctx(), {"query": "SELECT 1", "type": "carte"})


class Model:
    def __init__(self):
        self.calls = 0
        self.seen = []

    def chat(self, endpoint, messages, tools=None, temperature=0.1):
        self.calls += 1
        self.seen.append(messages)
        if self.calls == 1:
            return {"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                    "function": {"name": "render_chart", "arguments": json.dumps(
                        {"query": "SELECT drg, total FROM t", "type": "barres", "x": "drg", "y": "total"})}}]}}
        return {"message": {"role": "assistant", "content": "ok"}}


def test_model_never_receives_full_chart_data():
    m = Model()
    rt = AgentRuntime(m, REG, ctx())
    res = rt.run(AgentConfig("a", 1, "A", "m", "Instructions de test suffisantes.", ["render_chart"]),
                 [{"role": "user", "content": "trace"}])
    tool_msg = next(x for x in m.seen[-1] if x.get("role") == "tool")
    assert "_ui_chart" not in tool_msg["content"] and res.events[0].result["_ui_chart"]["type"] == "barres"


def test_small_results_are_sent_in_full_to_the_model():
    from tools.chart_tools import summary
    v = {"titre": "T", "type": "barres", "y": "n", "colonnes": ["k", "n"], "tronque": False, "limite": 200,
         "lignes": [{"k": i, "n": i} for i in range(15)]}
    assert summary(v)["apercu_complet"] and len(summary(v)["apercu"]) == 15
    v["lignes"] = [{"k": i, "n": i} for i in range(80)]
    s = summary(v)
    assert not s["apercu_complet"] and len(s["apercu"]) == 20 and "partiel" in s["note"]


def test_group_breakdown_is_computed_by_the_app():
    from tools.chart_tools import summary
    v = {"titre": "T", "type": "barres", "y": "n", "couleur": "g", "colonnes": ["k", "g", "n"], "tronque": False,
         "limite": 200, "lignes": [{"k": 1, "g": "A", "n": 2}, {"k": 2, "g": "B", "n": 3}, {"k": 3, "g": "A", "n": 5}]}
    assert summary(v)["repartition_par_g"] == [{"valeur": "A", "lignes": 2, "somme_y": 7.0},
                                               {"valeur": "B", "lignes": 1, "somme_y": 3.0}]
