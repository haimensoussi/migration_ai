import json

import pytest

from backend.agent_runtime import AgentConfig, AgentRuntime
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS
from tools.report_tools import compute_kpi, fmt_value

REG = ToolRegistry(BUILTIN_TOOLS)
NB = "\u202f"


class Sql:
    def __init__(self, rows, types=None):
        self.rows, self.types, self.calls = rows, types or {}, []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, row_limit))
        rows = [dict(r) for r in self.rows][: row_limit or None]
        return {"rows": rows, "columns": list(self.rows[0].keys()) if self.rows else [], "truncated": False,
                "types": self.types}


def ctx(rows, types=None):
    return ToolContext(sql=Sql(rows, types), workspace=None, user_email="a@sncf.fr", max_rows=200)


def test_specs_published_read_only():
    for tid, ex in (("render_kpi", "tools.report_tools:render_kpi"), ("generate_report", "tools.report_tools:generate_report")):
        s = REG.specs[tid]
        assert s.status == "publie" and s.read_only and not s.requires_confirmation and s.executor == ex


def test_compute_kpi_known_cases():
    k = compute_kpi("Régularité", "91.2", "92.0", "pourcentage", "hausse_favorable")
    assert k["valeur_affichee"] == "91,2 %" and k["ecart"] == pytest.approx(-0.8)
    assert k["ecart_affiche"] == "\u22120,8 pt" and k["tendance"] == "baisse défavorable" and k["ecart_relatif_pct"] is None
    k = compute_kpi("Voyageurs", 1500, 1200, "nombre", "neutre", "voyageurs")
    assert k["ecart"] == 300 and k["ecart_relatif_pct"] == 25.0 and k["tendance"] == "hausse"
    assert k["valeur_affichee"] == f"1{NB}500 voyageurs" and k["ecart_affiche"] == "+300 voyageurs (+25,0 %)"
    assert compute_kpi("Retards", 80, 100, "nombre", "baisse_favorable")["tendance"] == "baisse favorable"
    assert compute_kpi("X", 5, 5, "nombre", "hausse_favorable")["tendance"] == "stable"
    k = compute_kpi("X", 5, None, "nombre", "neutre")
    assert k["ecart"] is None and k["tendance"] is None
    k = compute_kpi("X", None, 3, "nombre", "neutre")
    assert k["valeur_affichee"] == "n/d" and k["tendance"] == "valeur manquante" and k["ecart"] is None
    assert compute_kpi("X", 10, 0, "nombre", "neutre")["ecart_relatif_pct"] is None   # pas de division par zéro
    assert fmt_value(3210450, "nombre") == f"3{NB}210{NB}450" and fmt_value(2.5, "decimal") == "2,50"


def test_render_kpi_rows_and_errors():
    rows = [{"annee": "2025", "taux": "91.2", "taux_ref": "92.0"}, {"annee": "2024", "taux": "92.0", "taux_ref": None}]
    r = REG.run(REG.specs["render_kpi"], ctx(rows), {"query": "SELECT annee, taux, taux_ref FROM t", "valeur": "taux",
                                                     "libelle": "annee", "reference": "taux_ref", "format": "pourcentage",
                                                     "sens": "hausse_favorable", "libelle_reference": "année N-1"})
    assert [k["libelle"] for k in r["indicateurs"]] == ["2025", "2024"] and r["indicateurs"][1]["ecart"] is None
    assert r["_ui_kpi"]["delta_color"] == "normal" and r["note_format"]
    with pytest.raises(ToolError, match="absente"):
        REG.run(REG.specs["render_kpi"], ctx(rows), {"query": "SELECT 1", "valeur": "zz"})
    with pytest.raises(ToolError, match="un indicateur"):
        REG.run(REG.specs["render_kpi"], ctx([{"v": i} for i in range(13)]), {"query": "SELECT v FROM t", "valeur": "v"})
    with pytest.raises(ToolError, match="nombres"):
        REG.run(REG.specs["render_kpi"], ctx([{"v": "abc"}]), {"query": "SELECT v FROM t", "valeur": "v"})
    with pytest.raises(ToolError):
        REG.run(REG.specs["render_kpi"], ctx(rows), {"query": "DROP TABLE t", "valeur": "taux"})


def test_generate_report_sections_annex_and_escaping():
    rows = [{"drg": "DRG A", "total": "1500.5"}, {"drg": "DRG B", "total": "20"}]
    r = REG.run(REG.specs["generate_report"], ctx(rows, {"drg": "STRING", "total": "DOUBLE"}), {
        "titre": "Fréquentation <script>alert(1)</script>", "introduction": "Intro",
        "sections": [{"titre": "Par DRG", "texte": "Texte", "requete": "SELECT drg, total FROM t", "type": "barres",
                      "x": "drg", "y": "total"},
                     {"titre": "Commentaire", "texte": "Sans données"}], "conclusion": "Fin"})
    html, md = r["_ui_report"]["html"], r["_ui_report"]["markdown"]
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "Généré par DISCOVERY" in html and "SELECT drg, total FROM t" in html and "```sql" in md
    assert r["sections"][0]["statistiques_y"]["somme"] == 1520.5 and r["sections"][1]["visuel"] is None


def test_generate_report_errors():
    rows = [{"drg": "A", "total": "1"}]
    with pytest.raises(ToolError):
        REG.run(REG.specs["generate_report"], ctx(rows), {"titre": "T", "sections": []})
    with pytest.raises(ToolError, match="Section 1"):
        REG.run(REG.specs["generate_report"], ctx(rows), {"titre": "T", "sections": [
            {"titre": "S", "requete": "SELECT drg, total FROM t", "type": "barres", "x": "zz", "y": "total"}]})
    from tools.report_tools import generate_report
    with pytest.raises(ToolError, match="cartes"):
        generate_report(ctx(rows), "T", [{"titre": "S", "requete": "SELECT 1", "type": "carte"}])
    with pytest.raises(ToolError, match="8 sections"):
        generate_report(ctx(rows), "T", [{"titre": f"S{i}"} for i in range(9)])


class Model:
    def __init__(self):
        self.n, self.seen = 0, []

    def chat(self, endpoint, messages, tools=None, temperature=0.1):
        self.n += 1
        self.seen.append(messages)
        if self.n == 1:
            return {"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                    "function": {"name": "render_kpi", "arguments": json.dumps(
                        {"query": "SELECT v FROM t", "valeur": "v", "titre": "Total"})}}]}}
        return {"message": {"role": "assistant", "content": "ok"}}


def test_model_sees_values_not_ui_payload():
    m = Model()
    AgentRuntime(m, REG, ctx([{"v": "42"}])).run(
        AgentConfig("a", 1, "A", "m", "Instructions de test suffisantes.", ["render_kpi"]), [{"role": "user", "content": "q"}])
    tool_msg = next(x for x in m.seen[-1] if x.get("role") == "tool")
    assert "_ui_kpi" not in tool_msg["content"] and "42" in tool_msg["content"]
