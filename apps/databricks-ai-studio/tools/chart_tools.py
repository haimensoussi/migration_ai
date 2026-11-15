"""Outil render_chart (catalogue, tous les agents) et moteur de graphiques partagé avec HakimAI.

- Requête SELECT contrôlée (checked_statement : lecture seule, tables autorisées de l'agent), droits de l'utilisateur.
- Le modèle choisit le type et les colonnes ; l'application dessine (Vega-Lite) : aucun code généré n'est exécuté.
- Le modèle ne reçoit qu'un résumé ; les données complètes sont dans « _ui_chart », réservée à l'affichage.
"""
from __future__ import annotations

import datetime as dt
import decimal
import math

from backend.tool_registry import ToolContext, ToolError
from tools.sql_tools import checked_statement

MAX_ROWS = 1000
FULL_PREVIEW = 50          # au-delà, le modèle ne reçoit qu'un aperçu partiel (signalé)
CHART_KINDS = ("barres", "barres_horizontales", "courbe", "aire", "camembert", "nuage", "tableau")
NUMERIC = {"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"}   # l'API SQL renvoie tout en texte
TEMPORAL = {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ"}
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#000000"]  # Okabe-Ito


def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _clean(v):
    """Valeurs JSON (Decimal -> float, dates -> ISO) pour Vega-Lite, l'export et le journal."""
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _stats(rows: list[dict], col: str) -> dict | None:
    vals = [x for x in (_num(r.get(col)) for r in rows) if x is not None]
    if not vals:
        return None
    return {"min": min(vals), "max": max(vals), "somme": round(sum(vals), 4), "moyenne": round(sum(vals) / len(vals), 4),
            "valeurs": len(vals), "vides": len(rows) - len(vals)}


def build_chart(ctx: ToolContext, title: str, query: str, kind: str, x: str = "", y: str = "", color: str = "",
                limit: int = 200) -> dict:
    """Exécute la requête et prépare un visuel (dict) ; lève ToolError si la demande est incohérente."""
    if kind not in CHART_KINDS:
        raise ToolError(f"Type inconnu : {kind}. Types possibles : {', '.join(CHART_KINDS)} (carte : render_map).")
    stmt = checked_statement(ctx, query)
    n = max(1, min(int(limit or 200), MAX_ROWS))
    r = ctx.sql.query(stmt, row_limit=n)
    raw = r.get("rows") or []
    types = r.get("types") or {}
    temporal = bool(raw and x and (isinstance(raw[0].get(x), (dt.date, dt.datetime))
                                   or str(types.get(x) or "").upper() in TEMPORAL))
    numeric = {c for c, t in types.items() if str(t or "").upper() in NUMERIC} | ({y} if y else set())
    rows = [{k: (_num(val) if k in numeric and val is not None else _clean(val)) for k, val in row.items()}
            for row in raw]
    cols = list(r.get("columns") or (list(rows[0].keys()) if rows else []))
    cols = [c["name"] if isinstance(c, dict) else c for c in cols]
    if not rows:
        raise ToolError("La requête ne renvoie aucune ligne : rien à représenter.")
    if kind != "tableau":
        for role, c in (("x", x), ("y", y)):
            if not c or c not in cols:
                raise ToolError(f"Colonne {role} « {c} » absente du résultat (colonnes : {', '.join(cols)}).")
        if color and color not in cols:
            raise ToolError(f"Colonne de couleur « {color} » absente du résultat.")
        if _stats(rows, y) is None:
            raise ToolError(f"La colonne y « {y} » ne contient pas de nombres.")
    return {"type": kind, "titre": title, "requete": query, "x": x, "y": y, "couleur": color, "colonnes": cols,
            "lignes": rows, "tronque": bool(r.get("truncated")), "limite": n, "x_temporel": temporal,
            "cree_le": dt.datetime.now().isoformat(timespec="seconds")}


def summary(v: dict) -> dict:
    """Ce que voit le modèle : de quoi commenter le visuel sans recevoir toutes les données."""
    full = len(v["lignes"]) <= FULL_PREVIEW
    out = {"titre": v["titre"], "type": v["type"], "lignes": len(v["lignes"]), "tronque": v["tronque"],
           "colonnes": v["colonnes"], "apercu": v["lignes"] if full else v["lignes"][:20], "apercu_complet": full,
           "affichage": "Le visuel s'affiche sous la réponse."}
    if not full:
        out["note"] = ("Aperçu partiel (20 premières lignes) : ne commenter que des chiffres présents dans l'aperçu "
                       "ou dans statistiques_y.")
    if v.get("y"):
        out["statistiques_y"] = _stats(v["lignes"], v["y"])
    if v.get("couleur"):   # comptages calculés par l'application : le modèle ne recompte pas
        groups: dict = {}
        for r in v["lignes"]:
            g = groups.setdefault(str(r.get(v["couleur"])), {"lignes": 0, "somme_y": 0.0})
            g["lignes"] += 1
            g["somme_y"] += _num(r.get(v["y"])) or 0.0
        out["repartition_par_" + v["couleur"]] = [{"valeur": k, **g} for k, g in
                                                  sorted(groups.items(), key=lambda kv: -kv[1]["lignes"])]
        out["note_repartition"] = "Utiliser cette répartition telle quelle pour tout comptage par groupe."
    if v["tronque"]:
        out["attention"] = f"Résultat limité à {v['limite']} lignes : agréger davantage pour un visuel complet."
    return out


def vega_spec(v: dict) -> dict:
    """Spécification Vega-Lite (affichage Streamlit et rapports HTML)."""
    kind, x, y, color = v["type"], v["x"], v["y"], v.get("couleur")
    yq = {"field": y, "type": "quantitative", "title": y}
    xn = {"field": x, "type": "nominal", "title": x, "sort": "-y" if v.get("tri", True) else None}
    if kind == "barres":
        mark, enc = "bar", {"x": xn, "y": yq}
    elif kind == "barres_horizontales":
        mark, enc = "bar", {"y": {**xn, "sort": "-x" if v.get("tri", True) else None}, "x": yq}
    elif kind in ("courbe", "aire"):
        mark = "line" if kind == "courbe" else "area"
        enc = {"x": {"field": x, "type": "temporal" if v.get("x_temporel") else "ordinal", "title": x}, "y": yq}
    elif kind == "camembert":
        mark, enc = {"type": "arc", "innerRadius": 50}, {"theta": yq, "color": {"field": x, "type": "nominal", "title": x}}
    else:  # nuage
        mark, enc = "point", {"x": {"field": x, "type": "quantitative", "title": x}, "y": yq}
    if color and kind != "camembert":
        enc["color"] = {"field": color, "type": "nominal", "title": color}
    enc["tooltip"] = [{"field": c} for c in v["colonnes"][:6]]
    return {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "title": v["titre"],
            "data": {"values": v["lignes"]}, "mark": mark, "encoding": enc, "width": "container", "height": 340,
            "config": {"range": {"category": PALETTE}, "mark": {"color": PALETTE[0]}}}


def render_chart(ctx: ToolContext, query: str, type: str, title: str = "", x: str = "", y: str = "",
                 color_by: str = "", limit: int = 200) -> dict:
    v = build_chart(ctx, title or "Graphique", query, type, x, y, color_by, limit)
    return {**summary(v), "_ui_chart": v}
