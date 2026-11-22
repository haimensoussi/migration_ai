"""Texte affiché au fil de l'eau pendant que le modèle répond (comme un chat grand public).

Branché sur AgentRuntime.on_text : delta = morceau de texte, None = nouvel appel du modèle (le texte déjà affiché,
annonce avant un outil, est conservé et la suite s'y ajoute). Le tour terminé, la page est redessinée depuis
l'historique : le texte définitif, avec graphiques et schémas, remplace l'affichage provisoire.
"""
from __future__ import annotations

import time

CURSOR = " ▌"
MIN_INTERVAL = 0.05   # secondes entre deux rafraîchissements (limite le trafic vers le navigateur)


class LiveText:
    def __init__(self, box, clock=time.monotonic):
        self.box, self.clock = box, clock
        self.buf, self._last = "", 0.0

    def __call__(self, delta: str | None) -> None:
        if delta is None:            # nouvel appel du modèle
            if self.buf:
                self.buf += "\n\n"   # texte d'annonce conservé, la suite s'y ajoute
            return
        self.buf += delta
        now = self.clock()
        if now - self._last >= MIN_INTERVAL:
            self._last = now
            self.box.markdown(self.buf + CURSOR)

    @classmethod
    def bubble(cls, avatar=None) -> "LiveText | None":
        """Bulle de réponse affichée tout de suite, remplie au fil de l'eau.

        None si l'affichage progressif n'est pas possible : la réponse arrive alors en bloc, comme avant.
        """
        import streamlit as st
        try:
            box = st.chat_message("assistant", avatar=avatar).empty()
        except Exception:  # noqa: BLE001
            return None
        return cls(box) if hasattr(box, "markdown") else None

    def close(self) -> None:
        if self.buf:
            self.box.markdown(self.buf.rstrip())
