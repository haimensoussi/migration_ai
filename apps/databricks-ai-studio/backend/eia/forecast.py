"""EIA Core - prévision de séries mensuelles : méthodes simples et explicables, testées sur l'historique.

Chaque méthode candidate est évaluée sur les derniers mois connus (origine fixe) ; la meilleure est retenue.
La prévision n'est déclarée fiable que si son erreur de test respecte le seuil de la configuration d'équipe.
Aucune dépendance externe. Aucune logique propre à une équipe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from backend.eia.contracts import Evidence, Forecast, ForecastPoint
from backend.eia.kpi import month_add

TREND_WINDOW = 3


class ForecastError(ValueError):
    pass


def _naive_seasonal(hist: list[float], h: int, s: int) -> list[float]:
    n = len(hist)
    return [hist[n - s + k] for k in range(h)]


def _seasonal_trend(hist: list[float], h: int, s: int) -> list[float]:
    """Même mois de l'année précédente x évolution annuelle des 3 derniers mois connus."""
    n, w = len(hist), TREND_WINDOW
    base = sum(hist[n - w - s:n - s])
    g = sum(hist[n - w:]) / base if base else 1.0
    return [hist[n - s + k] * g for k in range(h)]


def _moving_average(hist: list[float], h: int, s: int) -> list[float]:
    w = TREND_WINDOW
    return [sum(hist[-w:]) / w] * h


# nom -> (fonction, historique minimal en fonction de la saisonnalité s, libellé)
METHODS: dict[str, tuple[Callable[[list[float], int, int], list[float]], Callable[[int], int], str]] = {
    "naif_saisonnier": (_naive_seasonal, lambda s: s, "même mois de l'année précédente"),
    "saisonnier_tendance": (_seasonal_trend, lambda s: s + TREND_WINDOW,
                            "même mois de l'année précédente x évolution annuelle des 3 derniers mois"),
    "moyenne_mobile_3": (_moving_average, lambda s: TREND_WINDOW, "moyenne des 3 derniers mois (sans saisonnalité)"),
}
BASELINE = "naif_saisonnier"


def _errors(actual: list[float], pred: list[float]) -> tuple[float | None, float | None]:
    rel = [abs(a - p) / abs(a) for a, p in zip(actual, pred) if a]
    if not rel:
        return None, None
    return round(100 * sum(rel) / len(rel), 2), round(100 * max(rel), 2)


@dataclass
class ForecastRun:
    forecast: Forecast
    backtests: dict = field(default_factory=dict)     # méthode -> erreurs de test


def forecast(periods: list[str], values: list[float], horizon: int, season_length: int = 12, test_points: int = 6,
             max_error_pct: float = 15.0, metric: str = "", evidence: Evidence | None = None) -> ForecastRun:
    if len(periods) != len(values):
        raise ForecastError("Périodes et valeurs de longueurs différentes")
    s, n = int(season_length), len(values)
    if not 1 <= horizon <= s:
        raise ForecastError(f"Horizon invalide : entre 1 et {s} mois")
    if n < TREND_WINDOW:
        raise ForecastError(f"Historique insuffisant : {n} mois (minimum {TREND_WINDOW})")
    for a, b in zip(periods, periods[1:]):
        if month_add(a, 1) != b:
            raise ForecastError(f"Série discontinue entre {a} et {b} : mois manquants")
    origin = n - test_points
    backtests: dict[str, dict] = {}
    for name, (fn, need, _) in METHODS.items():
        if 1 <= test_points <= s and origin >= need(s):
            mean_err, max_err = _errors(values[origin:], fn(values[:origin], test_points, s))
            if mean_err is not None:
                backtests[name] = {"erreur_moyenne_pct": mean_err, "erreur_max_pct": max_err, "mois_testes": test_points,
                                   "periode_test": f"{periods[origin]}..{periods[-1]}"}
    if backtests:
        best = min(backtests, key=lambda m: backtests[m]["erreur_moyenne_pct"])
    else:
        best = next(m for m in METHODS if n >= METHODS[m][1](s))
    fn, _, label = METHODS[best]
    pred = fn(values, horizon, s)
    err = backtests.get(best, {}).get("erreur_moyenne_pct")
    q = backtests[best]["erreur_max_pct"] / 100 if best in backtests else None
    nonneg = all(v >= 0 for v in values)
    points = []
    for k, v in enumerate(pred):
        lo = hi = None
        if q is not None:
            lo, hi = v - abs(v) * q, v + abs(v) * q
            lo = max(lo, 0.0) if nonneg else lo
            lo, hi = round(lo, 2), round(hi, 2)
        points.append(ForecastPoint(period=month_add(periods[-1], k + 1), value=round(v, 2), lower=lo, upper=hi))
    reliable = err is not None and err <= max_error_pct
    if err is None:
        note = f"Non fiable : historique trop court pour tester la méthode ({n} mois)"
    elif not reliable:
        note = f"Non fiable : erreur moyenne au test {err} % supérieure au seuil de {max_error_pct} %"
    else:
        note = f"Fiable : erreur moyenne au test {err} % (seuil {max_error_pct} %)"
    fc = Forecast(
        metric=metric, method=best, horizon=horizon, points=points, history_points=n, backtest_error_pct=err,
        baseline_error_pct=backtests.get(BASELINE, {}).get("erreur_moyenne_pct"), reliable=reliable,
        reliability_note=note, evidence=evidence,
        assumptions=[f"Méthode retenue : {label}",
                     f"Test sur les {test_points} derniers mois connus" if backtests else "Aucun test possible",
                     "Plage basse-haute = erreur maximale observée au test (pas un intervalle de confiance statistique)",
                     f"{n} mois d'historique, de {periods[0]} à {periods[-1]}"])
    return ForecastRun(forecast=fc, backtests=backtests)
