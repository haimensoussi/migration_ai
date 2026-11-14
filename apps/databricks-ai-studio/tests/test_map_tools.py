import json

import pytest

from backend.agent_runtime import AgentConfig, AgentRuntime
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS
from tools.map_tools import MAX_POINTS, render_map
from ui import map_view

T = "dataops_dev.description_du_reseau_bronze.gares_de_voyageurs"


class Sql:
    def __init__(self, rows, columns=None, truncated=False):
        self.rows, self.columns, self.truncated, self.seen = rows, columns, truncated, []

    def query(self, statement, params=None, row_limit=None):
        self.seen.append((statement, row_limit))
        cols = self.columns or (list(self.rows[0].keys()) if self.rows else [])
        return {"columns": cols, "rows": self.rows[:row_limit], "truncated": self.truncated}


ROWS = [{"Nom_Gare": "Abancourt", "Segment(s) DRG": "C", "latitude": 49.6852237, "longitude": 1.7743058},
        {"Nom_Gare": "Abbeville", "Segment(s) DRG": "B", "latitude": "50.10221", "longitude": "1.82449"},
        {"Nom_Gare": "Sans position", "Segment(s) DRG": "A", "latitude": None, "longitude": None},
        {"Nom_Gare": "Hors bornes", "Segment(s) DRG": "A", "latitude": 95, "longitude": 2}]


def ctx(sql, tables=(T,)):
    return ToolContext(sql=sql, workspace=None, allowed_tables=list(tables), max_rows=200)


def test_points_summary_and_invalid_rows():
    sql = Sql(ROWS)
    r = render_map(ctx(sql), f"SELECT * FROM {T}", title="Gares", color_by="Segment(s) DRG")
    assert r["nombre_points"] == 2 and r["ignores"] == 2 and r["hors_metropole"] == 0
    assert r["colonnes_coordonnees"] == ["latitude", "longitude"]
    assert r["legende"] == {"type": "categories", "valeurs": ["C", "B"], "autres": 0}
    assert r["emprise"]["lat_max"] == pytest.approx(50.10221)
    assert sql.seen[0][1] == MAX_POINTS                     # limite carte (5000), pas celle d'execute_sql (200)


def test_custom_coordinate_columns_and_errors():
    rows = [{"nom": "x", "y_wgs": 48.8, "x_wgs": 2.3}]
    r = render_map(ctx(Sql(rows)), f"SELECT * FROM {T}", lat_column="y_wgs", lon_column="x_wgs")
    assert r["nombre_points"] == 1
    with pytest.raises(ToolError, match="latitude"):
        render_map(ctx(Sql([{"nom": "x"}])), f"SELECT * FROM {T}")
    with pytest.raises(ToolError, match="absente"):
        render_map(ctx(Sql(ROWS)), f"SELECT * FROM {T}", color_by="inconnue")


def test_read_only_and_allowed_tables_enforced():
    with pytest.raises(ToolError):
        render_map(ctx(Sql(ROWS)), f"DELETE FROM {T}")
    with pytest.raises(ToolError, match="hors des connaissances"):
        render_map(ctx(Sql(ROWS)), "SELECT * FROM a.b.autre")


def test_limit_capped_and_numeric_legend():
    sql = Sql([{"latitude": 48 + i / 100, "longitude": 2, "v": i} for i in range(3)])
    r = render_map(ctx(sql), f"SELECT * FROM {T}", color_by="v", limit=99999)
    assert sql.seen[0][1] == MAX_POINTS and r["legende"] == {"type": "numerique", "min": 0.0, "max": 2.0}


def test_model_never_receives_ui_points():
    sql = Sql(ROWS)
    spec = next(s for s in BUILTIN_TOOLS if s.tool_id == "render_map")

    class Model:
        def __init__(self):
            self.replies = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "render_map", "arguments": json.dumps({"query": f"SELECT * FROM {T}"})}}]},
                            {"role": "assistant", "content": "Voici la carte."}]
            self.seen = []

        def chat(self, endpoint, messages, tools=None, temperature=None, max_tokens=None):
            self.seen.append(messages)
            return {"message": self.replies.pop(0), "usage": {"total_tokens": 1}}
    m = Model()
    cfg = AgentConfig("carto", 1, "Carto Réseau", "m", "x", tool_ids=["render_map"], knowledge_tables=[T])
    res = AgentRuntime(m, ToolRegistry([spec]), ctx(sql)).run(cfg, [{"role": "user", "content": "carte"}])
    tool_msg = next(x for x in m.seen[-1] if x["role"] == "tool")
    assert "_ui_points" not in tool_msg["content"] and '"nombre_points": 2' in tool_msg["content"]
    assert len(res.events[0].result["_ui_points"]) == 2      # conservés pour l'affichage


def test_map_view_helpers():
    pts = [{"_lat": 49.0, "_lon": 1.0, "Segment(s) DRG": "C"}, {"_lat": 50.0, "_lon": 2.0, "Segment(s) DRG": "Z"}]
    res = {"couleur": "Segment(s) DRG", "legende": {"type": "categories", "valeurs": ["C"]},
           "emprise": {"lat_min": 49.0, "lat_max": 50.0, "lon_min": 1.0, "lon_max": 2.0}}
    col = map_view.colorize(pts, res)
    assert col[0]["_color"][:3] == map_view.PALETTE[0] and col[1]["_color"][:3] == map_view.OTHER
    vs = map_view.view_state(res)
    assert vs["latitude"] == 49.5 and vs["longitude"] == 1.5 and vs["zoom"] == 7.5
    data, tip = map_view.tooltip_rows(col, ["Segment(s) DRG"])
    assert data[0]["f0"] == "C" and "{f0}" in tip and "Segment(s) DRG" in tip
    gj = json.loads(map_view.to_geojson(pts))
    assert gj["features"][0]["geometry"]["coordinates"] == [1.0, 49.0]
    assert gj["features"][0]["properties"] == {"Segment(s) DRG": "C"}
