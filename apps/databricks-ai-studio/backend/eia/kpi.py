"""EIA Core - séries de KPI : normalisation des résultats SQL, mois incomplets, comparaisons.

Générique : aucune logique propre à une équipe. Les valeurs arrivent en texte (API SQL) et sont converties ici.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

_MONTH = re.compile(r"^(\d{4})-(\d{2})")
RATE_UNITS = ("%", "ratio")          # taux : non additifs, la fenêtre utilise une moyenne simple


def to_float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def norm_period(v: Any, grain: str) -> str:
    """Mois -> AAAA-MM ; instantané -> AAAA-MM-JJ ; autre valeur conservée telle quelle."""
    if v is None:
        return ""
    s = str(v).strip()
    m = _MONTH.match(s)
    if not m:
        return s
    return f"{m.group(1)}-{m.group(2)}" if grain == "mois" else s[:10]


def month_add(period: str, n: int) -> str:
    k = int(period[:4]) * 12 + int(period[5:7]) - 1 + n
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def pct(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base == 0:
        return None
    return round(100 * (cur - base) / abs(base), 2)


def to_points(rows: list[dict], grain: str) -> tuple[list[dict], int]:
    """Lignes SQL (period, value, dimension facultative) -> points triés ; renvoie aussi le nombre de valeurs vides."""
    pts, empty = [], 0
    for r in rows:
        v = to_float(r.get("value"))
        if v is None:
            empty += 1
            continue
        d = r.get("dimension")
        pts.append({"period": norm_period(r.get("period"), grain), "dimension": "" if d is None else str(d), "value": v})
    return sorted(pts, key=lambda p: (p["dimension"], p["period"])), empty


def drop_incomplete(points: list[dict], today: dt.date) -> tuple[list[dict], list[str]]:
    """Exclut le mois en cours et les mois futurs (données partielles) ; renvoie les mois exclus."""
    cur = f"{today.year:04d}-{today.month:02d}"
    kept = [p for p in points if p["period"] < cur]
    return kept, sorted({p["period"] for p in points if p["period"] >= cur})


def by_dimension(points: list[dict]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for p in points:
        out.setdefault(p["dimension"], {})[p["period"]] = p["value"]
    return out


def missing_months(periods: list[str]) -> list[str]:
    """Mois absents entre le premier et le dernier mois de la série."""
    if not periods:
        return []
    ps, out, cur = sorted(periods), [], sorted(periods)[0]
    have = set(ps)
    while cur < ps[-1]:
        cur = month_add(cur, 1)
        if cur not in have:
            out.append(cur)
    return out


def compare(series: dict[str, float], window: int = 1, unit: str = "") -> dict:
    """Dernier mois, variation mensuelle et variation annuelle d'une fenêtre de `window` mois (N vs N-1).

    Fenêtre : somme pour un KPI additif, moyenne simple pour un taux (approximation signalée).
    """
    if not series:
        return {}
    periods = sorted(series)
    last = periods[-1]
    rate = unit in RATE_UNITS
    out: dict[str, Any] = {"periode": last, "valeur": series[last], "points": len(periods)}
    prev = month_add(last, -1)
    if prev in series:
        out["mois_precedent"] = series[prev]
        out["variation_mensuelle_pct"] = pct(series[last], series[prev])
    win = [month_add(last, -i) for i in range(window)]
    ly = [month_add(p, -12) for p in win]
    if all(p in series for p in win + ly):
        agg = (lambda xs: sum(xs) / len(xs)) if rate else sum
        cur, base = agg([series[p] for p in win]), agg([series[p] for p in ly])
        out.update({"fenetre_mois": window, "fenetre": last if window == 1 else f"{win[-1]}..{last}", "valeur_fenetre": round(cur, 4),
                    "valeur_fenetre_n_1": round(base, 4), "agregation_fenetre": "moyenne" if rate else "somme"})
        if rate:
            out["variation_annuelle_points"] = round(cur - base, 2)
            out["note"] = "Taux : moyenne simple des mois de la fenêtre (non pondérée)"
        else:
            out["variation_annuelle_pct"] = pct(cur, base)
    else:
        out["note"] = f"Comparaison N-1 impossible : mois manquants pour la fenêtre de {window} mois"
    return out
