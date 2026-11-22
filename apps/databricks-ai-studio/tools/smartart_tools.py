"""Outils SmartArt : schémas qui illustrent une réponse (processus, cycle, hiérarchie, relations, matrice).

- render_smartart : outil du catalogue, ajouté à tous les agents ; creer_smartart : variante HakimAI (visuel V…).
- Aucune donnée lue ni code exécuté : le modèle fournit des éléments déjà établis dans sa réponse ; l'application
  valide, échappe et dessine (Graphviz DOT, rendu par st.graphviz_chart).
"""
from __future__ import annotations

import datetime as dt
import html

from backend.tool_registry import ToolContext, ToolError

KINDS = ("processus", "cycle", "hierarchie", "relation", "matrice")
KIND_LABELS = {"processus": "Processus", "cycle": "Cycle", "hierarchie": "Hiérarchie", "relation": "Relations",
               "matrice": "Matrice"}
MAX_ITEMS = {"processus": 10, "cycle": 8, "hierarchie": 20, "relation": 12, "matrice": 4}
MIN_ITEMS = {"processus": 2, "cycle": 3, "hierarchie": 2, "relation": 2, "matrice": 4}
PALETTE = [("#B0124F", "white"), ("#7A3E9D", "white"), ("#4A1942", "white"), ("#D9537F", "white"),
           ("#9C6BB8", "white"), ("#6E3A64", "white")]
MAX_TEXT, MAX_DETAIL, MAX_LINKS = 60, 140, 20


def _txt(v, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _wrap(s: str, width: int = 22) -> str:
    words, lines, cur = s.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return "\n".join(lines + [cur] if cur else lines)


def _items(kind: str, elements) -> list[dict]:
    if not isinstance(elements, list):
        raise ToolError("elements doit être une liste d'objets {texte, detail}.")
    out, seen = [], set()
    for e in elements:
        e = e if isinstance(e, dict) else {"texte": e}
        t = _txt(e.get("texte"), MAX_TEXT)
        if not t:
            raise ToolError("Chaque élément a un texte non vide.")
        if t.lower() in seen:
            raise ToolError(f"Élément en double : « {t} ».")
        seen.add(t.lower())
        out.append({"texte": t, "detail": _txt(e.get("detail"), MAX_DETAIL), "parent": _txt(e.get("parent"), MAX_TEXT)})
    lo, hi = MIN_ITEMS[kind], MAX_ITEMS[kind]
    if not lo <= len(out) <= hi:
        exact = f"exactement {lo}" if lo == hi else f"de {lo} à {hi}"
        raise ToolError(f"Un schéma {KIND_LABELS[kind].lower()} comporte {exact} éléments ({len(out)} fournis).")
    return out


def _node(i: int, it: dict, color: int, shape: str = "box") -> str:
    fill, font = PALETTE[color % len(PALETTE)]
    label = _wrap(it["texte"]) + ("\n\n" + _wrap(it["detail"], 30) if it["detail"] else "")
    return (f"n{i} [label={_q(label)}, shape={shape}, style=\"filled,rounded\", fillcolor={_q(fill)}, "
            f"fontcolor={_q(font)}, color={_q(fill)}];")


def _matrix_dot(items: list[dict], axe_x: str, axe_y: str) -> str:
    e = html.escape

    def cell(it, i):
        fill, font = PALETTE[i % len(PALETTE)]
        det = f'<BR/><FONT POINT-SIZE="10">{e(it["detail"])}</FONT>' if it["detail"] else ""
        return (f'<TD BGCOLOR="{fill}" WIDTH="190" HEIGHT="90"><FONT COLOR="{font}"><B>{e(it["texte"])}</B>'
                f'{det}</FONT></TD>')
    ylab = f'<TD ROWSPAN="2"><FONT COLOR="#4A1942">{e(axe_y)}</FONT></TD>' if axe_y else ""
    xlab = f'<TR>{"<TD></TD>" if axe_y else ""}<TD COLSPAN="2"><FONT COLOR="#4A1942">{e(axe_x)}</FONT></TD></TR>' \
        if axe_x else ""
    table = (f'<TABLE BORDER="0" CELLSPACING="6" CELLPADDING="8"><TR>{ylab}{cell(items[0], 0)}{cell(items[1], 1)}</TR>'
             f'<TR>{cell(items[2], 2)}{cell(items[3], 3)}</TR>{xlab}</TABLE>')
    return f'digraph G {{\nnode [shape=plaintext, fontname="Segoe UI", fontsize=12];\nm [label=<{table}>];\n}}'


def build_smartart(type: str, titre: str, elements, liens=None, axe_x: str = "", axe_y: str = "") -> dict:
    """Valide les éléments et produit le DOT. Pur (sans Streamlit ni SQL) : testable."""
    if type not in KINDS:
        raise ToolError(f"Type inconnu : {type}. Types possibles : {', '.join(KINDS)}.")
    titre = _txt(titre, 100)
    if not titre:
        raise ToolError("Donnez un titre au schéma.")
    items = _items(type, elements)
    idx = {it["texte"].lower(): i for i, it in enumerate(items)}
    links = []
    if type == "matrice":
        dot = _matrix_dot(items, _txt(axe_x, 60), _txt(axe_y, 60))
    else:
        head = ["digraph G {", 'graph [fontname="Segoe UI", nodesep=0.35, ranksep=0.45];',
                'node [fontname="Segoe UI", fontsize=12, margin="0.18,0.10", penwidth=1.2];',
                'edge [color="#888888", penwidth=1.4, fontname="Segoe UI", fontsize=10, fontcolor="#4A1942"];']
        if type == "processus":
            head.append("rankdir=LR;")
            body = [_node(i, it, i) for i, it in enumerate(items)]
            body += [f"n{i} -> n{i + 1};" for i in range(len(items) - 1)]
        elif type == "cycle":
            head.append("layout=circo;")
            body = [_node(i, it, i, "ellipse") for i, it in enumerate(items)]
            body += [f"n{i} -> n{(i + 1) % len(items)};" for i in range(len(items))]
        elif type == "hierarchie":
            head.append("rankdir=TB;")
            depth = {}
            for it in items:
                if it["parent"] and it["parent"].lower() not in idx:
                    raise ToolError(f"Parent « {it['parent']} » de « {it['texte']} » absent des éléments.")
                if it["parent"].lower() == it["texte"].lower():
                    raise ToolError(f"« {it['texte']} » ne peut pas être son propre parent.")
            for i, it in enumerate(items):   # profondeur (détecte les boucles)
                d, cur, seen = 0, it, set()
                while cur["parent"]:
                    if cur["texte"].lower() in seen:
                        raise ToolError("La hiérarchie contient une boucle.")
                    seen.add(cur["texte"].lower())
                    cur, d = items[idx[cur["parent"].lower()]], d + 1
                depth[i] = d
            if not any(d == 0 for d in depth.values()):
                raise ToolError("La hiérarchie doit avoir au moins un élément sans parent.")
            body = [_node(i, it, depth[i]) for i, it in enumerate(items)]
            body += [f"n{idx[it['parent'].lower()]} -> n{i};" for i, it in enumerate(items) if it["parent"]]
        else:   # relation
            head.append("rankdir=LR;")
            if not isinstance(liens, list) or not liens:
                raise ToolError("Un schéma de relations demande des liens {de, vers, libelle}.")
            if len(liens) > MAX_LINKS:
                raise ToolError(f"{MAX_LINKS} liens au plus.")
            body = [_node(i, it, i) for i, it in enumerate(items)]
            for ln in liens:
                ln = ln if isinstance(ln, dict) else {}
                a, b, lab = _txt(ln.get("de"), MAX_TEXT), _txt(ln.get("vers"), MAX_TEXT), _txt(ln.get("libelle"), 40)
                if a.lower() not in idx or b.lower() not in idx:
                    raise ToolError(f"Lien « {a} → {b} » : les deux extrémités doivent être des éléments.")
                links.append({"de": a, "vers": b, "libelle": lab})
                body.append(f"n{idx[a.lower()]} -> n{idx[b.lower()]}" + (f" [label={_q(lab)}]" if lab else "") + ";")
        dot = "\n".join(head + body + ["}"])
    return {"type": type, "titre": titre, "elements": items, "liens": links, "axe_x": _txt(axe_x, 60),
            "axe_y": _txt(axe_y, 60), "dot": dot}


def summary(sa: dict) -> dict:
    return {"titre": sa["titre"], "type": sa["type"], "elements": len(sa["elements"]), "liens": len(sa["liens"]),
            "affichage": "Le schéma s'affiche sous la réponse."}


def render_smartart(ctx: ToolContext, type: str, titre: str, elements: list, liens: list | None = None,
                    axe_x: str = "", axe_y: str = "") -> dict:
    sa = build_smartart(type, titre, elements, liens, axe_x, axe_y)
    return {**summary(sa), "_ui_smartart": sa}


def creer_smartart(ctx: ToolContext, titre: str, type: str, elements: list, liens: list | None = None,
                   axe_x: str = "", axe_y: str = "") -> dict:
    """HakimAI : même schéma, conservé comme visuel de la conversation (réutilisable dans generer_rapport)."""
    from tools.hakim_tools import _p
    p = _p(ctx)
    sa = build_smartart(type, titre, elements, liens, axe_x, axe_y)
    vid = f"V{len(p.visuals) + 1}"
    p.visuals[vid] = {"id": vid, **sa, "type": "smartart", "forme": sa["type"], "requete": "", "colonnes": [],
                      "lignes": [], "cree_le": dt.datetime.now().isoformat(timespec="seconds")}
    return {"visuel_id": vid, **summary(sa)}
