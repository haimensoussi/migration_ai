"""Construction du bandeau d'accueil (HTML de confiance, valeurs échappées)."""
from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".svg": "image/svg+xml"}


@lru_cache(maxsize=None)
def _uri(path: str) -> str:
    p = Path(path)
    return f"data:{MIME[p.suffix.lower()]};base64," + base64.b64encode(p.read_bytes()).decode()


def _find(stem: str) -> Path | None:
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        p = ASSETS / "img" / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def banner_html(title: str, subtitle: str) -> str:
    full = _find("hero_full")
    if full:
        return (f'<div class="dsc-banner-full"><img src="{_uri(str(full))}" '
                f'alt="{html.escape(title)} — {html.escape(subtitle)}"></div>')
    art = _find("hero_photo") or ASSETS / "img" / "hero_art.svg"
    train = ASSETS / "icons" / "train_line.svg"
    return (
        '<div class="ais-hero dsc-banner">'
        f'<div class="dsc-banner-art" style="background-image:url(\'{_uri(str(art))}\')"></div>'
        '<div class="dsc-banner-slash"></div>'
        '<div class="dsc-banner-left">'
        f'<img class="dsc-banner-train" src="{_uri(str(train))}" alt="" aria-hidden="true">'
        f'<div><h2>{html.escape(title)}</h2><div>{html.escape(subtitle)}</div></div>'
        '</div></div>')
