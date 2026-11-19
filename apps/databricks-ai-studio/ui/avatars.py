"""Avatars d'agents DISCOVERY générés par le code (SVG, sans modèle ni image externe).

L'apparence est déterministe : elle dépend de l'identifiant de l'agent (variantes) et de sa catégorie
(couleur et accessoire métier). Même agent -> même avatar, partout dans l'interface.
"""
from __future__ import annotations

import base64
import hashlib
import tempfile
from pathlib import Path

from ui.catalog_cards import TONES, style_for

VISOR = "#2B1B33"
HEAD = "#FFFFFF"


def _bytes(seed: str) -> bytes:
    return hashlib.sha256(str(seed or "agent").encode("utf-8")).digest()


def _badge(kind: str, fg: str) -> str:
    """Accessoire métier sur le torse (centré en 50,86)."""
    w = f'fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"'
    if kind == "shield":
        return f'<path d="M50 78l7 3v5c0 4-3 7-7 8.5-4-1.5-7-4.5-7-8.5v-5z" {w}/><path d="M47 86l2 2 4-4" {w}/>'
    if kind == "database":
        return (f'<ellipse cx="50" cy="80" rx="7" ry="2.6" {w}/><path d="M43 80v10c0 1.5 3 2.6 7 2.6s7-1.1 7-2.6V80" {w}/>'
                f'<path d="M43 85c0 1.5 3 2.6 7 2.6s7-1.1 7-2.6" {w}/>')
    if kind == "chart":
        return f'<path d="M43 92h14M45 90v-5M50 90v-9M55 90v-7" {w}/>'
    if kind == "clock":
        return f'<circle cx="50" cy="86" r="7" {w}/><path d="M50 82v4l3 2" {w}/>'
    if kind == "play":
        return f'<circle cx="50" cy="86" r="7" {w}/><path d="M48 83l5 3-5 3z" {w}/>'
    if kind == "document":
        return f'<path d="M46 79h6l3 3v11h-9z" {w}/><path d="M48 86h5M48 89h4" {w}/>'
    return f'<path d="M46 82l-3 4 3 4M54 82l3 4-3 4" {w}/>'   # code


def avatar_svg(seed: str, category: str | None = None, lead: bool = False) -> str:
    """SVG 100x100 : fond pastille, robot (tête, visière, yeux, antenne, bouche), accessoire métier."""
    b = _bytes(seed)
    kind, tone = style_for(category)
    bg, fg = TONES[tone]
    rx = (14, 20, 26)[b[0] % 3]                      # forme de tête
    head_w = (52, 56, 60)[b[1] % 3]
    hx = 50 - head_w / 2
    parts = [f'<circle cx="50" cy="50" r="50" fill="{bg}"/>']
    # corps / épaules
    parts.append(f'<path d="M22 100c0-17 12-28 28-28s28 11 28 28z" fill="{fg}"/>')
    parts.append(_badge(kind, fg))
    # cou
    parts.append(f'<rect x="44" y="66" width="12" height="8" rx="3" fill="#D9D4DE"/>')
    line = f'stroke="{fg}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"'
    # antenne (5 variantes ; la couronne du chef la remplace)
    ant = -1 if lead else b[2] % 5
    if ant == 0:       # tige et boule
        parts.append(f'<path d="M50 22v-9" {line}/><circle cx="50" cy="11" r="4" fill="{fg}"/>')
    elif ant == 1:     # double antenne
        parts.append(f'<path d="M40 23l-5-9M60 23l5-9" {line}/>'
                     f'<circle cx="35" cy="13" r="3.4" fill="{fg}"/><circle cx="65" cy="13" r="3.4" fill="{fg}"/>')
    elif ant == 2:     # ressort
        parts.append(f'<path d="M50 22l-4-3 8-3-8-3 4-3" {line}/><circle cx="50" cy="9" r="3" fill="{fg}"/>')
    elif ant == 3:     # voyant lumineux
        parts.append(f'<path d="M50 22v-6" {line}/><rect x="44" y="8" width="12" height="8" rx="4" fill="{fg}"/>'
                     f'<rect x="47" y="10.5" width="6" height="3" rx="1.5" fill="{bg}"/>')
    # oreilles (3 variantes : plots, boulons, casque audio)
    ears = b[5] % 3
    if ears == 2 and lead:
        ears = 0
    if ears == 1:
        parts.append(f'<circle cx="{hx - 1}" cy="46" r="6" fill="{fg}"/><circle cx="{hx + head_w + 1}" cy="46" r="6" fill="{fg}"/>')
    elif ears == 2:
        parts.append(f'<path d="M{hx - 2} 44a{head_w / 2 + 2} {head_w / 2 + 2} 0 0 1 {head_w + 4} 0" '
                     f'stroke="{fg}" stroke-width="4" fill="none"/>'
                     f'<rect x="{hx - 7}" y="36" width="10" height="20" rx="5" fill="{fg}"/>'
                     f'<rect x="{hx + head_w - 3}" y="36" width="10" height="20" rx="5" fill="{fg}"/>')
    else:
        parts.append(f'<rect x="{hx - 5}" y="38" width="7" height="16" rx="3.5" fill="{fg}"/>'
                     f'<rect x="{hx + head_w - 2}" y="38" width="7" height="16" rx="3.5" fill="{fg}"/>')
    # tête
    parts.append(f'<rect x="{hx}" y="22" width="{head_w}" height="46" rx="{rx}" fill="{HEAD}" '
                 f'stroke="#E6E3EA" stroke-width="1.5"/>')
    # front (4 variantes)
    brow = b[8] % 4
    if brow == 1:
        parts.append(f'<circle cx="50" cy="28" r="2.2" fill="{fg}"/>')
    elif brow == 2:
        parts.append(f'<rect x="42" y="26.5" width="16" height="3" rx="1.5" fill="{fg}" fill-opacity=".55"/>')
    elif brow == 3:
        parts.append(f'<circle cx="{hx + 7}" cy="28" r="1.6" fill="#CFC9D6"/>'
                     f'<circle cx="{hx + head_w - 7}" cy="28" r="1.6" fill="#CFC9D6"/>')
    # couronne de chef d'équipe
    if lead:
        parts.append('<path d="M38 21l4-9 8 6 8-6 4 9z" fill="#F2B705" stroke="#C98F00" stroke-width="1.2" '
                     'stroke-linejoin="round"/>')
    # visière (3 formes : pilule, écran, deux verres)
    vw = head_w - 12
    visor = b[6] % 3
    if visor == 2:
        parts.append(f'<rect x="{50 - vw / 2}" y="34" width="{vw / 2 - 2}" height="18" rx="8" fill="{VISOR}"/>'
                     f'<rect x="52" y="34" width="{vw / 2 - 2}" height="18" rx="8" fill="{VISOR}"/>')
    else:
        parts.append(f'<rect x="{50 - vw / 2}" y="33" width="{vw}" height="20" rx="{10 if visor == 0 else 4}" '
                     f'fill="{VISOR}"/>')
    # yeux (8 variantes)
    eyes = b[3] % 8
    if eyes == 0:      # ronds lumineux
        parts.append(f'<circle cx="41" cy="43" r="4" fill="{bg}"/><circle cx="59" cy="43" r="4" fill="{bg}"/>')
    elif eyes == 1:    # souriants
        parts.append(f'<path d="M37 45q4-5 8 0M55 45q4-5 8 0" fill="none" stroke="{bg}" stroke-width="3" '
                     f'stroke-linecap="round"/>')
    elif eyes == 2:    # lunettes
        parts.append(f'<rect x="35" y="38" width="12" height="9" rx="3" fill="{fg}"/>'
                     f'<rect x="53" y="38" width="12" height="9" rx="3" fill="{fg}"/>'
                     f'<path d="M47 42h6" stroke="{fg}" stroke-width="2"/>'
                     f'<path d="M37 40l3 0M55 40l3 0" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>')
    elif eyes == 3:    # bandeau lumineux
        parts.append(f'<rect x="37" y="41" width="26" height="5" rx="2.5" fill="{bg}"/>')
    elif eyes == 4:    # clin d'œil
        parts.append(f'<circle cx="41" cy="43" r="4" fill="{bg}"/>'
                     f'<path d="M55 44q4-4 8 0" fill="none" stroke="{bg}" stroke-width="3" stroke-linecap="round"/>')
    elif eyes == 5:    # grands yeux avec reflet
        parts.append(f'<circle cx="41" cy="43" r="5.5" fill="{bg}"/><circle cx="59" cy="43" r="5.5" fill="{bg}"/>'
                     f'<circle cx="42" cy="44" r="2.6" fill="{VISOR}"/><circle cx="60" cy="44" r="2.6" fill="{VISOR}"/>'
                     f'<circle cx="40" cy="41" r="1.3" fill="#FFFFFF"/><circle cx="58" cy="41" r="1.3" fill="#FFFFFF"/>')
    elif eyes == 6:    # pixels
        parts.append(f'<rect x="37" y="39" width="7" height="7" rx="1" fill="{bg}"/>'
                     f'<rect x="56" y="39" width="7" height="7" rx="1" fill="{bg}"/>')
    else:              # concentré (paupières mi-closes)
        parts.append(f'<path d="M36 42h10M54 42h10" stroke="{bg}" stroke-width="3" stroke-linecap="round"/>'
                     f'<circle cx="41" cy="45" r="2.4" fill="{bg}"/><circle cx="59" cy="45" r="2.4" fill="{bg}"/>')
    # reflet de visière
    parts.append(f'<path d="M{50 - vw / 2 + 5} 37q3-2 7-2" stroke="#FFFFFF" stroke-opacity=".45" '
                 f'stroke-width="2" fill="none" stroke-linecap="round"/>')
    # joues (une fois sur trois)
    if b[7] % 3 == 0:
        parts.append(f'<circle cx="{hx + 8}" cy="58" r="3.5" fill="{fg}" fill-opacity=".22"/>'
                     f'<circle cx="{hx + head_w - 8}" cy="58" r="3.5" fill="{fg}" fill-opacity=".22"/>')
    # bouche (6 variantes)
    mouth = b[4] % 6
    if mouth == 0:     # sourire
        parts.append(f'<path d="M44 59q6 5 12 0" fill="none" stroke="{fg}" stroke-width="2.6" stroke-linecap="round"/>')
    elif mouth == 1:   # barre
        parts.append(f'<rect x="43" y="57" width="14" height="4" rx="2" fill="{fg}"/>')
    elif mouth == 2:   # points
        parts.append(''.join(f'<circle cx="{44 + 4 * i}" cy="59" r="1.5" fill="{fg}"/>' for i in range(4)))
    elif mouth == 3:   # grand sourire ouvert
        parts.append(f'<path d="M43 57h14q-1 7-7 7t-7-7z" fill="{fg}"/>')
    elif mouth == 4:   # grille de haut-parleur
        parts.append(f'<rect x="42" y="56" width="16" height="6" rx="2" fill="none" stroke="{fg}" stroke-width="1.6"/>'
                     f'<path d="M46 56v6M50 56v6M54 56v6" stroke="{fg}" stroke-width="1.4"/>')
    else:              # petite moue
        parts.append(f'<path d="M46 59q4 -2 8 0" fill="none" stroke="{fg}" stroke-width="2.6" stroke-linecap="round"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
            '<defs><clipPath id="c"><circle cx="50" cy="50" r="50"/></clipPath></defs>'
            f'<g clip-path="url(#c)">{"".join(parts)}</g></svg>')


def avatar_uri(seed: str, category: str | None = None, lead: bool = False) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(avatar_svg(seed, category, lead).encode()).decode()


def is_lead(agent: dict) -> bool:
    """Chef d'équipe / coordinateur : délègue à d'autres agents (outils « agent:<id> »)."""
    return any(str(t).startswith("agent:") for t in agent.get("tool_ids") or [])


def _seed(agent: dict) -> str:
    return str(agent.get("agent_id") or agent.get("name") or "agent")


def agent_avatar_uri(agent: dict) -> str:
    return avatar_uri(_seed(agent), agent.get("category"), is_lead(agent))


AVATAR_DIR = Path(tempfile.gettempdir()) / "discovery_avatars"


def avatar_file(seed: str, category: str | None = None, lead: bool = False) -> str:
    """Chemin d'un fichier SVG (pour st.chat_message(avatar=...)), écrit une seule fois par apparence."""
    svg = avatar_svg(seed, category, lead)
    path = AVATAR_DIR / f"{hashlib.sha1(svg.encode()).hexdigest()}.svg"
    if not path.exists():
        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
    return str(path)


def agent_avatar_file(agent: dict) -> str:
    return avatar_file(_seed(agent), agent.get("category"), is_lead(agent))
