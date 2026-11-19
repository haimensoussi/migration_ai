"""Cartes de catalogue DISCOVERY (agents et outils) : pastille d'icône colorée, titre et description
sur deux lignes, pictogrammes des capacités en bas à droite (format type galerie de modèles).

Module sans dépendance Streamlit : il produit du HTML échappé et testable.
"""
from __future__ import annotations

import base64
import html
from functools import lru_cache

from ui.discovery_icons import ICON_DIR

BASE_STROKE = "#A00062"          # couleur d'origine des SVG de assets/icons
MAX_FOOTER = 4

# Tons de pastille : (fond, couleur du pictogramme)
TONES = {
    "rose": ("#FBE0D8", "#B0124F"),
    "vert": ("#D9EFDF", "#2E7D4F"),
    "violet": ("#ECE3F5", "#7A3E9D"),
    "bleu": ("#DDEAF8", "#2F5E9E"),
    "orange": ("#FFEBD2", "#B85C00"),
    "prune": ("#F1DDEB", "#4A1942"),
}

# Catégorie -> (pictogramme, ton)
CATEGORY_STYLE = {
    "Qualité des données": ("shield", "vert"),
    "Visualisation": ("chart", "violet"),
    "Analyse": ("chart", "violet"),
    "Données": ("database", "bleu"),
    "SQL": ("database", "bleu"),
    "Unity Catalog": ("database", "bleu"),
    "Jobs": ("clock", "orange"),
    "Exploitation": ("clock", "orange"),
    "Automatisation": ("play", "orange"),
    "Flux": ("play", "orange"),
    "Orchestration": ("play", "prune"),
    "Gouvernance": ("document", "prune"),
    "FinOps": ("chart", "orange"),
    "Documentation": ("document", "rose"),
}
DEFAULT_STYLE = ("code", "rose")

# Pictogrammes de pied de carte : catégorie d'outil -> (pictogramme, couleur, libellé)
FOOTER_BY_CATEGORY = {
    "Visualisation": ("chart", "#7A3E9D", "Visualisation"),
    "Analyse": ("chart", "#7A3E9D", "Analyse"),
    "SQL": ("database", "#2F5E9E", "Données SQL"),
    "Données": ("database", "#2F5E9E", "Données"),
    "Unity Catalog": ("database", "#2F5E9E", "Unity Catalog"),
    "Qualité des données": ("shield", "#2E7D4F", "Qualité des données"),
    "Jobs": ("clock", "#B85C00", "Jobs"),
    "Exploitation": ("clock", "#B85C00", "Exploitation"),
    "Automatisation": ("play", "#B85C00", "Automatisation"),
    "Flux": ("play", "#B85C00", "Flux"),
    "Gouvernance": ("document", "#4A1942", "Gouvernance"),
    "FinOps": ("chart", "#B85C00", "FinOps"),
}
FOOTER_AGENT = ("play", "#4A1942", "Délègue à d'autres agents")


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def style_for(category: str | None) -> tuple[str, str]:
    return CATEGORY_STYLE.get((category or "").strip(), DEFAULT_STYLE)


@lru_cache(maxsize=None)
def colored_icon_uri(name: str, color: str) -> str:
    """SVG de assets/icons recoloré (trait) et encodé en data URI."""
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        path = ICON_DIR / "code.svg"
    svg = path.read_text(encoding="utf-8").replace(BASE_STROKE, color)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()


def agent_footer(tool_ids: list | None, tool_categories: dict[str, str]) -> list[tuple[str, str, str]]:
    """Pictogrammes des capacités d'un agent, déduits de ses outils (sans doublon, MAX_FOOTER au plus)."""
    out, seen = [], set()
    for tid in tool_ids or []:
        tid = str(tid)
        item = FOOTER_AGENT if tid.startswith("agent:") else FOOTER_BY_CATEGORY.get(tool_categories.get(tid, ""))
        if item and item[0] not in seen:
            seen.add(item[0])
            out.append(item)
    return out[:MAX_FOOTER]


def tool_footer(executor: str, read_only: bool, requires_confirmation: bool) -> list[tuple[str, str, str]]:
    """Pictogrammes d'un outil : type d'exécution, lecture seule, validation humaine."""
    ex = (executor or "").lower()
    if "http" in ex or "flow" in ex or "power_automate" in ex:
        kind = ("play", "#B85C00", "Appel externe")
    elif "uc_function" in ex:
        kind = ("code", "#2F5E9E", "Fonction Unity Catalog")
    elif "uc_tools" in ex:
        kind = ("database", "#2F5E9E", "Unity Catalog")
    elif "sql" in ex:
        kind = ("database", "#2F5E9E", "Requête SQL")
    elif "chart" in ex or "report" in ex or "map" in ex or "excel" in ex:
        kind = ("chart", "#7A3E9D", "Restitution")
    elif "job" in ex:
        kind = ("clock", "#B85C00", "Jobs")
    else:
        kind = ("code", "#6B6475", "Outil intégré")
    out = [kind]
    out.append(("success", "#2E7D4F", "Lecture seule") if read_only else ("alert", "#B85C00", "Écriture"))
    if requires_confirmation:
        out.append(("shield", "#4A1942", "Validation humaine"))
    return out[:MAX_FOOTER]


def card_html(title: str, description: str, category: str | None = None,
              footer: list[tuple[str, str, str]] | None = None, tag: str = "") -> str:
    """Carte complète. `tag` : HTML déjà sûr (badge de statut) affiché en bas à gauche."""
    icon, tone = style_for(category)
    bg, fg = TONES[tone]
    foot = "".join(f'<img src="{colored_icon_uri(n, c)}" alt="{esc(l)}" title="{esc(l)}">' for n, c, l in footer or [])
    return (
        f'<div class="dsc-gcard" title="{esc(title)}">'
        f'<div class="dsc-gcard-head"><div class="dsc-gcard-ico" style="background:{bg}">'
        f'<img src="{colored_icon_uri(icon, fg)}" alt="" aria-hidden="true"></div>'
        f'<div class="dsc-gcard-title">{esc(title)}</div></div>'
        f'<div class="dsc-gcard-desc" title="{esc(description)}">{esc(description)}</div>'
        f'<div class="dsc-gcard-foot"><div>{tag}</div><div class="dsc-gcard-icons">{foot}</div></div>'
        f'</div>'
    )


CARD_CSS = """
<style>
.dsc-gcard { background:#FFFFFF; border:1px solid #ECEAF0; border-radius:12px; padding:22px 22px 16px 22px;
  box-shadow:0 1px 4px rgba(43,27,51,.10); height:196px; display:flex; flex-direction:column;
  transition:box-shadow .15s ease, transform .15s ease; margin-bottom:4px; }
.dsc-gcard:hover { box-shadow:0 6px 18px rgba(43,27,51,.16); transform:translateY(-1px); }
.dsc-gcard-head { display:flex; gap:14px; align-items:center; min-height:52px; }
.dsc-gcard-ico { width:50px; height:50px; border-radius:8px; flex:none; display:flex; align-items:center;
  justify-content:center; }
.dsc-gcard-ico img { width:26px; height:26px; }
.dsc-gcard-title { color:#242424; font-weight:600; font-size:1.02rem; line-height:1.4; display:-webkit-box;
  -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.dsc-gcard-desc { color:#424242; font-size:.95rem; line-height:1.5; margin-top:14px; display:-webkit-box;
  -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.dsc-gcard-foot { margin-top:auto; display:flex; align-items:center; justify-content:space-between; min-height:24px; }
.dsc-gcard-icons { display:flex; gap:10px; }
.dsc-gcard-icons img { width:20px; height:20px; }
</style>
"""
