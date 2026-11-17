"""export_excel : classeur .xlsx valide, valeurs typées, texte jamais interprété comme formule, lecture seule."""
import base64
import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from backend import hakim
from backend.tool_registry import ToolContext, ToolError, ToolPermissionError, ToolRegistry
from tools import excel_tools as xt
from tools.catalog import BUILTIN_TOOLS

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


class Sql:
    def __init__(self, n=2, truncated=False):
        self.n, self.truncated, self.calls = n, truncated, []

    def query(self, s, params=None, row_limit=None):
        self.calls.append((s, row_limit))
        rows = [{"nom": "Côte d'Azur <&>", "n": "12", "taux": "0.5", "jour": "2026-01-31", "ok": "true",
                 "f": "=SUM(A1)"}] * self.n
        return {"columns": ["nom", "n", "taux", "jour", "ok", "f"], "rows": rows, "truncated": self.truncated,
                "types": {"nom": "STRING", "n": "BIGINT", "taux": "DOUBLE", "jour": "DATE", "ok": "BOOLEAN",
                          "f": "STRING"}}


def ctx(sql=None, allowed=None):
    return ToolContext(sql=sql or Sql(), workspace=None, user_email="a@sncf.fr", allowed_tables=allowed or [])


def unzip(res):
    return zipfile.ZipFile(io.BytesIO(base64.b64decode(res["_ui_excel"]["contenu_b64"])))


def test_workbook_is_valid_xml_with_info_sheet():
    r = xt.export_excel(ctx(), "Gares", [{"nom": "A/B", "requete": "SELECT * FROM a.b.c"},
                                         {"nom": "A/B", "requete": "SELECT * FROM a.b.c"}])
    z = unzip(r)
    for n in z.namelist():
        ET.fromstring(z.read(n))
    names = [e.attrib["name"] for e in ET.fromstring(z.read("xl/workbook.xml")).find(f"{NS}sheets")]
    assert names == ["A B", "A B (2)", "Informations"]
    assert [f["lignes"] for f in r["feuilles"]] == [2, 2] and r["fichier"].endswith(".xlsx")
    info = z.read("xl/worksheets/sheet3.xml").decode()
    assert "SELECT * FROM a.b.c" in info and "a@sncf.fr" in info
    assert "_ui_excel" in r and "contenu_b64" not in {k for k in r if not k.startswith("_ui")}


def test_values_are_typed_and_formulas_stay_text():
    s = unzip(xt.export_excel(ctx(), "T", [{"nom": "F", "requete": "SELECT 1"}])).read("xl/worksheets/sheet1.xml").decode()
    assert '<c r="B2"><v>12</v></c>' in s and '<c r="C2"><v>0.5</v></c>' in s
    assert '<c r="D2" s="2"><v>46053</v></c>' in s                       # 31/01/2026
    assert '<c r="E2" t="b"><v>1</v></c>' in s
    assert "Côte d'Azur &lt;&amp;&gt;" in s
    assert '<c r="F2" t="inlineStr"' in s and "<f>" not in s              # jamais de formule


@pytest.mark.parametrize("v,t,exp", [("NaN", "DOUBLE", ("s", "NaN")), ("x", "BIGINT", ("s", "x")),
                                     (None, "STRING", (None, None)), ("3.5", "DECIMAL(10,2)", ("n", 3.5))])
def test_convert_edge_cases(v, t, exp):
    assert xt.convert(v, t) == exp


def test_limits_truncation_and_read_only():
    sql = Sql(n=3)
    r = xt.export_excel(ctx(sql), "T", [{"nom": "F", "requete": "SELECT 1"}], limite=3)
    assert r["feuilles"][0]["tronque"] and sql.calls[0][1] == 3
    xt.export_excel(ctx(sql), "T", [{"nom": "F", "requete": "SELECT 1"}], limite=999999)
    assert sql.calls[-1][1] == xt.MAX_ROWS
    with pytest.raises(ToolPermissionError):
        xt.export_excel(ctx(), "T", [{"nom": "F", "requete": "DELETE FROM a.b.c"}])
    with pytest.raises(ToolPermissionError):
        xt.export_excel(ctx(allowed=["a.b.c"]), "T", [{"nom": "F", "requete": "SELECT * FROM x.y.z"}])
    with pytest.raises(ToolError, match="feuilles au plus"):
        xt.export_excel(ctx(), "T", [{"nom": "F", "requete": "SELECT 1"}] * 11)


def test_registered_in_catalog_and_hakim():
    spec = next(t for t in BUILTIN_TOOLS if t.tool_id == "export_excel")
    assert spec.read_only and not spec.requires_confirmation
    h = ToolRegistry(hakim.TOOLS).specs["exporter_excel"]
    assert h.read_only and not h.requires_confirmation
    r = ToolRegistry([spec]).run(spec, ctx(), {"titre": "T", "feuilles": [{"nom": "F", "requete": "SELECT 1"}]})
    assert r["feuilles"][0]["lignes"] == 2
