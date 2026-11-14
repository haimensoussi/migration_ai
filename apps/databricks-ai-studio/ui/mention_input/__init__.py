"""Liste d'agents sur @ et complétion Tab ajoutées à la zone de saisie standard (st.chat_input).

L'envoi des messages reste celui de Streamlit : si l'ajout échoue (version de Streamlit, politique du navigateur),
le chat continue de fonctionner sans la liste.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FRONTEND = Path(__file__).parent / "frontend"


def enabled() -> bool:
    """AI_STUDIO_MENTION_INPUT=0 désactive la liste @ (saisie standard seule)."""
    return os.environ.get("AI_STUDIO_MENTION_INPUT", "1").strip().lower() not in ("0", "false", "off", "non")


def agents_payload(agents: list[dict]) -> list[dict]:
    """Seules les informations utiles à l'affichage sont transmises au navigateur."""
    return [{"name": a["name"], "category": a.get("category") or ""} for a in agents if a.get("name")]


def _js_string(src: str) -> str:
    return json.dumps(src, ensure_ascii=False).replace("</", "<\\/")


def autocomplete_html(agents: list[dict]) -> str:
    logic = (FRONTEND / "mention_logic.js").read_text(encoding="utf-8")
    install = (FRONTEND / "chat_autocomplete.js").read_text(encoding="utf-8")
    payload = json.dumps(agents_payload(agents), ensure_ascii=False).replace("</", "<\\/")
    return ("<script>(function(){var P=window.parent;try{"
            f"P.__dscAgents={payload};"
            "if(!P.__dscMentionInstalled){var D=P.document,s=D.createElement('script');s.id='dsc-mention-script';"
            f"s.textContent={_js_string(logic + chr(10) + install)};D.head.appendChild(s);}}"
            "}catch(e){if(window.console){console.warn('DISCOVERY : liste @ indisponible',e);}}})();</script>")


def inject(agents: list[dict]) -> None:
    import streamlit.components.v1 as components
    components.html(autocomplete_html(agents), height=0)
