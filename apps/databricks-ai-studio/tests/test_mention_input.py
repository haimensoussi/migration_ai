import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def mi(monkeypatch):
    fake = types.ModuleType("streamlit")
    fake.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    sys.modules.pop("ui.mention_input", None)
    import ui.mention_input as m
    return m, fake


def test_accept_once_per_id(mi):
    m, fake = mi
    v = {"id": "1-a", "text": "  @Sentinelle DQ Réseau bonjour "}
    assert m.accept(v, "k") == "@Sentinelle DQ Réseau bonjour"
    assert m.accept(v, "k") is None                     # page rejouée : pas de second envoi
    assert m.accept({"id": "2-b", "text": "suite"}, "k") == "suite"
    assert m.accept(None, "k") is None and m.accept({"id": "3", "text": "   "}, "k") is None


def test_payload_and_toggle(mi, monkeypatch):
    m, _ = mi
    assert m.agents_payload([{"agent_id": "x", "name": "SQL Assistant", "owner": "a@b", "category": "Analyse"},
                             {"agent_id": "y", "name": ""}]) == [{"name": "SQL Assistant", "category": "Analyse"}]
    monkeypatch.delenv("AI_STUDIO_MENTION_INPUT", raising=False)
    assert m.enabled()
    monkeypatch.setenv("AI_STUDIO_MENTION_INPUT", "0")
    assert not m.enabled()


def test_frontend_files_present():
    fe = ROOT / "ui" / "mention_input" / "frontend"
    html = (fe / "index.html").read_text()
    assert 'src="mention_logic.js"' in html and "streamlit:componentReady" in html and "setComponentValue" in html
    assert (fe / "mention_logic.js").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node indisponible")
def test_js_logic_with_node():
    r = subprocess.run(["node", str(ROOT / "tests" / "js" / "test_mention_logic.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
