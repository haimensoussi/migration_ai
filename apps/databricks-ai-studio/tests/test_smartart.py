"""Schémas SmartArt : validation, DOT, outil universel, HakimAI, rapport."""
import types

import pytest

from backend import hakim
from backend.agent_repository import DEFAULT_TOOLS, UNIVERSAL_TOOLS, with_universal_tools
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools import smartart_tools as S
from tools.catalog import BUILTIN_TOOLS
from tools.hakim_report_tools import build_report
from tools.hakim_tools import Platform

REG = ToolRegistry(BUILTIN_TOOLS)
SPEC = REG.specs["render_smartart"]
STEPS = [{"texte": "Comprendre"}, {"texte": "Existant"}, {"texte": "Cible", "detail": "TO-BE"}, {"texte": "Déployer"}]


def test_spec_is_read_only_universal_and_not_a_default():
    assert SPEC.read_only and not SPEC.requires_confirmation and SPEC.status == "publie"
    assert UNIVERSAL_TOOLS == ("render_smartart",) and "render_smartart" not in DEFAULT_TOOLS
    assert with_universal_tools(["execute_sql"]) == ["execute_sql", "render_smartart"]
    assert with_universal_tools(["render_smartart", "x"]) == ["render_smartart", "x"]   # pas de doublon


def test_process_chain():
    sa = S.build_smartart("processus", "Démarche", STEPS)
    assert sa["dot"].count("->") == 3 and "rankdir=LR" in sa["dot"] and "n0 -> n1;" in sa["dot"]
    assert "TO-BE" in sa["dot"] and sa["dot"].startswith("digraph G {") and sa["dot"].endswith("}")


def test_cycle_closes_loop():
    sa = S.build_smartart("cycle", "Amélioration", STEPS)
    assert "layout=circo" in sa["dot"] and "n3 -> n0;" in sa["dot"] and sa["dot"].count("->") == 4


def test_hierarchy_parents_and_errors():
    els = [{"texte": "Équipe DQ"}, {"texte": "Nadia", "parent": "Équipe DQ"}, {"texte": "Karim", "parent": "équipe dq"}]
    sa = S.build_smartart("hierarchie", "Organisation", els)
    assert "n0 -> n1;" in sa["dot"] and "n0 -> n2;" in sa["dot"] and sa["dot"].count("->") == 2
    with pytest.raises(ToolError, match="absent"):
        S.build_smartart("hierarchie", "O", [{"texte": "A"}, {"texte": "B", "parent": "Z"}])
    with pytest.raises(ToolError, match="boucle|sans parent"):
        S.build_smartart("hierarchie", "O", [{"texte": "A", "parent": "B"}, {"texte": "B", "parent": "A"}])


def test_relation_links_must_reference_elements():
    els = [{"texte": "Commandes"}, {"texte": "Fournisseurs"}]
    sa = S.build_smartart("relation", "Modèle", els, [{"de": "Commandes", "vers": "Fournisseurs", "libelle": "code"}])
    assert 'n0 -> n1 [label="code"];' in sa["dot"] and len(sa["liens"]) == 1
    with pytest.raises(ToolError, match="extrémités"):
        S.build_smartart("relation", "M", els, [{"de": "Commandes", "vers": "Articles"}])
    with pytest.raises(ToolError, match="liens"):
        S.build_smartart("relation", "M", els)


def test_matrix_needs_four_and_escapes_html():
    els = [{"texte": "A <b>"}, {"texte": "B & C"}, {"texte": "C"}, {"texte": "D"}]
    sa = S.build_smartart("matrice", "Priorisation", els, axe_x="Effort", axe_y="Valeur")
    assert "A &lt;b&gt;" in sa["dot"] and "B &amp; C" in sa["dot"] and "<b>" not in sa["dot"].replace("<B>", "")
    assert "Effort" in sa["dot"] and "Valeur" in sa["dot"]
    with pytest.raises(ToolError, match="exactement 4"):
        S.build_smartart("matrice", "P", els[:3])


def test_validation_and_dot_escaping():
    with pytest.raises(ToolError, match="Type inconnu"):
        S.build_smartart("pyramide", "T", STEPS)
    with pytest.raises(ToolError, match="double"):
        S.build_smartart("processus", "T", [{"texte": "A"}, {"texte": "a"}])
    with pytest.raises(ToolError, match="de 2 à 10"):
        S.build_smartart("processus", "T", [{"texte": "A"}])
    sa = S.build_smartart("processus", "T", [{"texte": 'Dire "oui"'}, {"texte": "x" * 200}])
    assert 'Dire \\"oui\\"' in sa["dot"] and "x" * 61 not in sa["dot"].replace("\\n", "")


def test_render_tool_through_registry():
    out = REG.run(SPEC, ToolContext(sql=None, workspace=None), {"type": "processus", "titre": "Démarche", "elements": STEPS})
    assert out["elements"] == 4 and out["_ui_smartart"]["dot"].count("->") == 3


def test_hakim_creer_smartart_is_visual_and_report_lists_it():
    spec = next(t for t in hakim.TOOLS if t.tool_id == "creer_smartart")
    assert spec.read_only and spec.input_schema["properties"] == SPEC.input_schema["properties"]
    assert "creer_smartart" in hakim.config("m").tool_ids
    plat = Platform(types.SimpleNamespace(), None, "a@sncf.fr")
    with pytest.raises(ToolError, match="HakimAI"):                              # hors HakimAI : refusé
        ToolRegistry(hakim.TOOLS).run(spec, ToolContext(sql=None, workspace=None),
                                      {"type": "cycle", "titre": "Cycle", "elements": STEPS})
    ctx = ToolContext(sql=None, workspace=None, platform=plat)
    r = ToolRegistry(hakim.TOOLS).run(spec, ctx, {"type": "cycle", "titre": "Cycle", "elements": STEPS})
    assert r["visuel_id"] == "V1" and plat.visuals["V1"]["type"] == "smartart" and plat.visuals["V1"]["forme"] == "cycle"
    rep = build_report("R", [{"titre": "Démarche", "visuel_id": "V1"}], plat.visuals, "a@sncf.fr")
    assert "<li>Cible — TO-BE</li>" in rep["html"] and "1. Comprendre" in rep["markdown"]
    assert "```sql" not in rep["markdown"] and rep["visuels"] == ["V1"]
