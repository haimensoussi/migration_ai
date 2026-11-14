"""Outil render_map : requête SQL en lecture seule -> points géolocalisés pour une carte interactive.

Le modèle ne reçoit qu'un résumé ; les points complets sont dans la clé « _ui_points », réservée à l'affichage.
"""
from __future__ import annotations

import math

from backend.tool_registry import ToolContext, ToolError
from tools.sql_tools import checked_statement

MAX_POINTS = 5000
LAT_NAMES = ("latitude", "lat")
LON_NAMES = ("longitude", "lon", "lng", "long")
METROPOLE = {"lat_min": 41.0, "lat_max": 51.6, "lon_min": -5.8, "lon_max": 10.0}


def _find(columns: list[str], wanted: tuple[str, ...], explicit: str | None) -> str | None:
    if explicit:
        hit = next((c for c in columns if c.lower() == explicit.lower()), None)
        if not hit:
            raise ToolError(f"Colonne « {explicit} » absente du résultat. Colonnes : {', '.join(columns)}")
        return hit
    return next((c for w in wanted for c in columns if c.lower() == w), None)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def render_map(ctx: ToolContext, query: str, title: str = "", layer: str = "points", color_by: str | None = None,
               tooltip: list | None = None, lat_column: str | None = None, lon_column: str | None = None,
               limit: int = MAX_POINTS) -> dict:
    statement = checked_statement(ctx, query)
    n = max(1, min(int(limit), MAX_POINTS))
    r = ctx.sql.query(statement, row_limit=n)
    rows = r.get("rows") or []
    columns = list(r.get("columns") or (list(rows[0].keys()) if rows else []))
    if rows and not columns:
        columns = list(rows[0].keys())
    lat_c, lon_c = _find(columns, LAT_NAMES, lat_column), _find(columns, LON_NAMES, lon_column)
    if not lat_c or not lon_c:
        raise ToolError("Le résultat doit contenir une colonne latitude et une colonne longitude "
                        f"(colonnes reçues : {', '.join(columns) or 'aucune'}).")
    if color_by and color_by not in columns:
        raise ToolError(f"Colonne de couleur « {color_by} » absente du résultat.")
    tips = [c for c in (tooltip or []) if c in columns] or [c for c in columns if c not in (lat_c, lon_c)][:4]

    points, ignored = [], 0
    for row in rows:
        lat, lon = _num(row.get(lat_c)), _num(row.get(lon_c))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            ignored += 1
            continue
        p = {k: row.get(k) for k in dict.fromkeys(tips + ([color_by] if color_by else []))}
        p["_lat"], p["_lon"] = lat, lon
        points.append(p)
    if not points:
        return {"titre": title, "nombre_points": 0, "ignores": ignored, "tronque": bool(r.get("truncated")),
                "message": "Aucun point affichable : résultat vide ou coordonnées invalides.", "_ui_points": []}

    lats, lons = [p["_lat"] for p in points], [p["_lon"] for p in points]
    hors = sum(1 for p in points if not (METROPOLE["lat_min"] <= p["_lat"] <= METROPOLE["lat_max"]
                                        and METROPOLE["lon_min"] <= p["_lon"] <= METROPOLE["lon_max"]))
    apercu = [{k: v for k, v in p.items() if not k.startswith("_")} | {lat_c: p["_lat"], lon_c: p["_lon"]}
              for p in points[:10]]
    out = {"titre": title or "Carte", "couche": layer, "nombre_points": len(points), "ignores": ignored,
           "hors_metropole": hors, "tronque": bool(r.get("truncated")), "limite": n,
           "colonnes_coordonnees": [lat_c, lon_c], "couleur": color_by, "infobulle": tips,
           "emprise": {"lat_min": min(lats), "lat_max": max(lats), "lon_min": min(lons), "lon_max": max(lons)},
           "apercu": apercu, "_ui_points": points}
    if color_by:
        vals = [p.get(color_by) for p in points]
        nums = [_num(v) for v in vals]
        if all(x is not None for x in nums):
            out["legende"] = {"type": "numerique", "min": min(nums), "max": max(nums)}
        else:
            cats = list(dict.fromkeys(str(v) for v in vals))
            out["legende"] = {"type": "categories", "valeurs": cats[:12], "autres": max(0, len(cats) - 12)}
    return out
