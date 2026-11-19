import base64

from tools.catalog import BUILTIN_TOOLS
from ui import catalog_cards as cc


def _svg(uri: str) -> str:
    return base64.b64decode(uri.split(",", 1)[1]).decode()


def test_card_escapes_text_and_has_structure():
    h = cc.card_html("<b>Agent</b>", 'desc "x" <script>', "Qualité des données", [], "")
    assert "<script>" not in h and "<b>Agent</b>" not in h
    assert "&lt;b&gt;Agent&lt;/b&gt;" in h
    for cls in ("dsc-gcard", "dsc-gcard-ico", "dsc-gcard-title", "dsc-gcard-desc", "dsc-gcard-icons"):
        assert cls in h
    assert cc.TONES["vert"][0] in h          # pastille verte pour la qualité


def test_unknown_category_uses_default_style():
    assert cc.style_for("Inconnue") == cc.DEFAULT_STYLE
    assert cc.style_for(None) == cc.DEFAULT_STYLE


def test_icon_is_recolored():
    svg = _svg(cc.colored_icon_uri("shield", "#123456"))
    assert "#123456" in svg and cc.BASE_STROKE not in svg
    assert "<svg" in _svg(cc.colored_icon_uri("inexistant", "#000000"))   # repli sur code.svg


def test_agent_footer_dedup_limit_and_delegation():
    cats = {"a": "SQL", "b": "Unity Catalog", "c": "Visualisation", "d": "Jobs", "e": "Qualité des données"}
    f = cc.agent_footer(["a", "b", "c", "agent:x", "d", "e", "zz"], cats)
    icons = [i for i, _, _ in f]
    assert icons == ["database", "chart", "play", "clock"]   # b dédoublonné avec a, limite 4
    assert cc.agent_footer(None, cats) == []


def test_tool_footer_flags():
    f = cc.tool_footer("tools.sql_tools:execute_sql", True, False)
    assert [i for i, _, _ in f] == ["database", "success"]
    f = cc.tool_footer("tools.flow_tools:call_flow", False, True)
    assert [i for i, _, _ in f] == ["play", "alert", "shield"]


def test_team_footer_merges_members_and_style_override():
    cats = {"a": "SQL", "c": "Visualisation"}
    f = cc.team_footer([["a"], None, ["c", "a"]], cats)
    assert [i for i, _, _ in f] == ["database", "chart"]
    h = cc.card_html("Équipe X", "m", "SQL", f, "", cc.FILIERE_STYLE["UDR"])
    assert cc.TONES["vert"][0] in h and cc.TONES["bleu"][0] not in h
    assert cc.TONES["bleu"][0] in cc.card_html("x", "y", "SQL", [], "", ("shield", "inconnu"))   # ton invalide ignoré
    for fil in ("Transverse", "Supply Chain", "PTE", "UDR"):
        assert fil in cc.FILIERE_STYLE


def test_all_builtin_tools_render():
    for t in BUILTIN_TOOLS:
        h = cc.card_html(t.name, t.description, t.category, cc.tool_footer(t.executor, t.read_only,
                                                                           t.requires_confirmation))
        assert "dsc-gcard" in h
