import xml.etree.ElementTree as ET
from pathlib import Path

from ui import avatars as av
from ui.catalog_cards import TONES, card_html


def test_svg_is_valid_and_deterministic():
    for i in range(40):
        s = av.avatar_svg(f"agent{i}", "SQL", i % 5 == 0)
        ET.fromstring(s)
    assert av.avatar_svg("x", "SQL") == av.avatar_svg("x", "SQL")


def test_variety_over_many_agents():
    shapes = {av.avatar_svg(f"a{i}") for i in range(30)}
    assert len(shapes) == 30                         # 30 agents de même catégorie : 30 visages distincts


def test_every_face_variant_is_reachable():
    import re
    seen = {av._bytes(f"s{i}")[3] % 8 for i in range(400)}
    assert seen == set(range(8))                      # 8 types d'yeux
    assert {av._bytes(f"s{i}")[4] % 6 for i in range(400)} == set(range(6))   # 6 bouches
    s = av.avatar_svg("x", "SQL", lead=True)
    assert not re.search(r'cy="(9|11)"', s)            # pas d'antenne sous la couronne


def test_category_color_and_lead_crown():
    s = av.avatar_svg("x", "Qualité des données")
    assert TONES["vert"][0] in s and TONES["vert"][1] in s
    assert "#F2B705" not in s
    assert "#F2B705" in av.avatar_svg("x", "Orchestration", lead=True)


def test_is_lead_and_agent_helpers(tmp_path, monkeypatch):
    assert av.is_lead({"tool_ids": ["execute_sql", "agent:abc"]})
    assert not av.is_lead({"tool_ids": ["execute_sql"]}) and not av.is_lead({})
    a = {"agent_id": "id1", "name": "Clara", "category": "SQL", "tool_ids": []}
    assert av.agent_avatar_uri(a).startswith("data:image/svg+xml;base64,")
    monkeypatch.setattr(av, "AVATAR_DIR", tmp_path / "av")
    p = av.agent_avatar_file(a)
    assert Path(p).is_file() and p.endswith(".svg") and av.agent_avatar_file(a) == p
    ET.fromstring(Path(p).read_text())


def test_card_uses_avatar_instead_of_tile():
    uri = av.avatar_uri("x", "SQL")
    h = card_html("Clara", "desc", "SQL", [], "", avatar=uri)
    tile = 'class="dsc-gcard-ico"'          # « dsc-gcard-icons » (pied de carte) ne doit pas compter
    assert "dsc-gcard-avatar" in h and tile not in h
    assert tile in card_html("Clara", "desc", "SQL")
