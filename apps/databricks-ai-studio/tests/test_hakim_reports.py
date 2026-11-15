import decimal
import types

import pytest

from backend import hakim
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.hakim_report_tools import build_report, vega_spec
from tools.hakim_tools import Platform

REG = ToolRegistry(hakim.TOOLS)
ROWS = [{"drg": "DRG A", "total": decimal.Decimal("1500.5")}, {"drg": "<script>x</script>", "total": 20}]


class Sql:
    def __init__(self, rows):
        self.rows, self.seen = rows, []

    def query(self, statement, params=None, row_limit=None):
        self.seen.append((statement, row_limit))
        return {"rows": [dict(r) for r in self.rows], "columns": list(self.rows[0]) if self.rows else [],
                "truncated": False}


def ctx(rows=ROWS):
    plat = Platform(types.SimpleNamespace(), types.SimpleNamespace(), "a@sncf.fr", False, {})
    return ToolContext(sql=Sql(rows), workspace=None, user_email="a@sncf.fr", max_rows=200, platform=plat)


def run(c, tid, **a):
    return REG.run(REG.specs[tid], c, a)


def test_visual_is_read_only_and_validates_columns():
    assert REG.specs["creer_visuel"].read_only and not REG.specs["creer_visuel"].requires_confirmation
    c = ctx()
    r = run(c, "creer_visuel", titre="T", requete="SELECT drg, total FROM t", type="barres", x="drg", y="total")
    assert r["visuel_id"] == "V1" and r["statistiques_y"]["somme"] == 1520.5
    assert c.platform.visuals["V1"]["lignes"][0]["total"] == 1500.5            # Decimal -> float
    with pytest.raises(ToolError, match="absente"):
        run(c, "creer_visuel", titre="T", requete="SELECT drg, total FROM t", type="barres", x="drg", y="inconnue")
    with pytest.raises(ToolError, match="nombres"):
        run(c, "creer_visuel", titre="T", requete="SELECT drg, total FROM t", type="barres", x="total", y="drg")
    with pytest.raises(ToolError):
        run(c, "creer_visuel", titre="T", requete="DELETE FROM t", type="tableau")
    with pytest.raises(ToolError):
        run(c, "creer_visuel", titre="T", requete="SELECT 1; DROP TABLE t", type="tableau")


def test_spec_types():
    v = {"type": "camembert", "titre": "T", "x": "drg", "y": "total", "colonnes": ["drg", "total"], "lignes": []}
    assert vega_spec(v)["encoding"]["theta"]["field"] == "total"
    v["type"] = "barres_horizontales"
    assert vega_spec(v)["encoding"]["y"]["field"] == "drg"


def test_report_escapes_text_and_traces_queries():
    c = ctx()
    run(c, "creer_visuel", titre="Par DRG", requete="SELECT drg, total FROM t", type="barres", x="drg", y="total")
    r = run(c, "generer_rapport", titre="Rapport <b>", introduction="<img src=x onerror=alert(1)>",
            sections=[{"titre": "S1", "texte": "Constat", "visuel_id": "V1"}])
    rep = c.platform.reports[r["rapport_id"]]
    assert "<img src=x" not in rep["html"] and "&lt;img" in rep["html"]
    assert "<script>x</script>" not in rep["html"].split("<script>vegaEmbed")[0]
    assert "SELECT drg, total FROM t" in rep["html"] and "SELECT drg, total FROM t" in rep["markdown"]
    with pytest.raises(ToolError, match="introuvable"):
        run(c, "generer_rapport", titre="X", sections=[{"titre": "S", "visuel_id": "V9"}])


def test_json_in_script_cannot_close_tag():
    v = {"id": "V1", "type": "barres", "titre": "T", "x": "drg", "y": "total", "colonnes": ["drg", "total"],
         "lignes": [{"drg": "</script><script>alert(1)</script>", "total": 1}], "requete": "q", "cree_le": "now"}
    html_ = build_report("R", [{"titre": "S", "visuel_id": "V1"}], {"V1": v}, "u")["html"]
    assert "</script><script>alert(1)" not in html_


def test_text_values_from_sql_api_become_numbers_but_codes_stay_text():
    rows = [{"cp": "01000", "total": "112037.0"}, {"cp": "93290", "total": "20"}]
    c = ctx(rows)
    c.sql.query = lambda s, params=None, row_limit=None: {"rows": [dict(r) for r in rows], "columns": ["cp", "total"],
                                                          "truncated": False, "types": {"cp": "STRING", "total": "DOUBLE"}}
    run(c, "creer_visuel", titre="T", requete="SELECT cp, total FROM t", type="barres", x="cp", y="total")
    v = c.platform.visuals["V1"]["lignes"]
    assert v[0] == {"cp": "01000", "total": 112037.0} and v[1]["total"] == 20.0
