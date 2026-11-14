import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ui import mention_input as m

ROOT = Path(__file__).resolve().parents[1]


def test_payload_and_toggle(monkeypatch):
    assert m.agents_payload([{"agent_id": "x", "name": "SQL Assistant", "owner": "a@b", "category": "Analyse"},
                             {"agent_id": "y", "name": ""}]) == [{"name": "SQL Assistant", "category": "Analyse"}]
    monkeypatch.delenv("AI_STUDIO_MENTION_INPUT", raising=False)
    assert m.enabled()
    monkeypatch.setenv("AI_STUDIO_MENTION_INPUT", "0")
    assert not m.enabled()


def test_autocomplete_html_is_safe_and_complete():
    html = m.autocomplete_html([{"name": "Agent </script><b>x</b>", "category": "Qualité"},
                                {"name": "Sentinelle DQ Réseau"}])
    assert html.startswith("<script>") and html.endswith("</script>")
    assert html.count("</script>") == 1                      # aucun nom ni code ne ferme la balise
    assert "__dscAgents" in html and "Sentinelle DQ Réseau" in html
    assert "stChatInputTextArea" in html and "MentionLogic" in html


def test_no_custom_send_path_left():
    src = (ROOT / "ui" / "chat_panel.py").read_text()
    assert "st.chat_input(placeholder" in src and "mention_input(" not in src and "STICKY_CSS" not in src


@pytest.mark.skipif(shutil.which("node") is None, reason="Node indisponible")
def test_js_logic_and_syntax_with_node(tmp_path):
    r = subprocess.run(["node", str(ROOT / "tests" / "js" / "test_mention_logic.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for f in ["mention_logic.js", "chat_autocomplete.js"]:
        c = subprocess.run(["node", "--check", str(ROOT / "ui" / "mention_input" / "frontend" / f)],
                           capture_output=True, text=True)
        assert c.returncode == 0, c.stderr
    # Le script généré s'exécute sans erreur de syntaxe
    js = re.sub(r"^<script>|</script>$", "", m.autocomplete_html([{"name": "A"}]))
    p = tmp_path / "boot.js"
    p.write_text(js)
    assert subprocess.run(["node", "--check", str(p)], capture_output=True, text=True).returncode == 0
