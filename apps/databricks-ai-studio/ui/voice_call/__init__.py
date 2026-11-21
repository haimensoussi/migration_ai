"""Composant Streamlit bidirectionnel « appel vocal » (HTML/JS sans npm, protocole des composants Streamlit).

Le navigateur ouvre la connexion WebRTC avec OpenAI grâce à une clé éphémère fournie par le serveur ; les appels
d'outils demandés par le modèle remontent au serveur (valeur du composant) et les résultats redescendent (arguments).
"""
from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).parent / "frontend"
_component = None


def _get():
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("discovery_voice_call", path=str(FRONTEND))
    return _component


def voice_call(*, secret: dict | None, results: list[dict], error: dict | None, max_seconds: int,
               max_tool_calls: int, calls_url: str, key: str = "hakim_voice"):
    """Renvoie le dernier événement du navigateur : {kind: start|tools|end, seq, ...} ou None."""
    return _get()(secret=secret, results=results, error=error, max_seconds=max_seconds,
                  max_tool_calls=max_tool_calls, calls_url=calls_url, key=key, default=None)
