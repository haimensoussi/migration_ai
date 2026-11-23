"""Outils EIA eia_kpi et eia_forecast : KPI et prévisions d'une équipe métier, définis par sa configuration.

- Les requêtes viennent de config/teams/<team_id>.json (validées au chargement) ; le modèle ne fournit pas de SQL.
- Exécution sous l'identité de l'utilisateur, avec les contrôles communs (lecture seule, tables autorisées).
- Chaque valeur renvoyée porte sa preuve (outil, sources, requête) pour que les agents la citent sans l'inventer.
"""
from __future__ import annotations

import datetime as dt

from backend import config as app_config
from backend.eia import contracts as c
from backend.eia import forecast as fc_mod
from backend.eia import kpi as k
from backend.eia import team_config as tc
from backend.tool_registry import ToolContext, ToolError, ToolSpec
from tools.sql_tools import checked_statement

MAX_KPI_ROWS = 5000


def _today() -> dt.date:
    return dt.date.today()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _team(team_id: str) -> tc.TeamConfig:
    try:
        return tc.load(team_id, data_scope=app_config.data_scope())
    except tc.TeamConfigError as e:
        raise ToolError(f"Configuration d'équipe invalide ou absente : {e}") from e


def fetch_kpi(ctx: ToolContext, cfg: tc.TeamConfig, kpi_id: str, tool: str,
              drop_incomplete: bool = True) -> tuple[dict, list[dict], c.Evidence, dict]:
    """Exécute la requête d'un KPI ; renvoie (définition, points, preuve, notes sur les données)."""
    try:
        kdef = cfg.kpi(kpi_id)
    except tc.TeamConfigError as e:
        raise ToolError(f"{e}. KPI disponibles : {', '.join(x['id'] for x in cfg.kpis)}") from e
    statement = checked_statement(ctx, cfg.kpi_sql(kpi_id))
    r = ctx.sql.query(statement, row_limit=MAX_KPI_ROWS)
    if r.get("truncated"):
        raise ToolError(f"Résultat du KPI {kpi_id} tronqué au-delà de {MAX_KPI_ROWS} lignes : valeurs non fiables")
    points, empty = k.to_points(r.get("rows") or [], kdef["grain"])
    excluded: list[str] = []
    if kdef["grain"] == "mois" and drop_incomplete:
        points, excluded = k.drop_incomplete(points, _today())
    sources = sorted(set(tc.ALIAS.findall(kdef["sql"])))
    ev = c.Evidence(tool=tool, source=", ".join(cfg.sources[a] for a in sources), query=statement, produced_at=_now())
    notes = {"lignes_lues": len(r.get("rows") or []), "valeurs_vides": empty, "mois_exclus_incomplets": excluded}
    if kdef["grain"] == "mois":
        gaps = {d: k.missing_months(list(s)) for d, s in k.by_dimension(points).items()}
        notes["mois_manquants"] = {d or "global": g for d, g in gaps.items() if g}
    return kdef, points, ev, notes


def _definition(kdef: dict) -> dict:
    return {"formule": kdef.get("formula", ""), "exclusions": kdef.get("exclusions", ""), "limites": kdef.get("limits", "")}


def eia_kpi(ctx: ToolContext, team_id: str, kpi_id: str, dimension: str = "", window_months: int = 1,
            last_n: int = 13) -> dict:
    cfg = _team(team_id)
    kdef, points, ev, notes = fetch_kpi(ctx, cfg, kpi_id, "eia_kpi")
    if dimension:
        dims = sorted({p["dimension"] for p in points})
        points = [p for p in points if p["dimension"].lower() == dimension.strip().lower()]
        if not points:
            raise ToolError(f"Valeur de dimension inconnue pour {kpi_id} : {dimension}. Valeurs : {', '.join(dims[:40])}")
    if not points:
        raise ToolError(f"Aucune valeur pour le KPI {kpi_id}")
    results, findings, series = [], [], []
    for dim, s in k.by_dimension(points).items():
        if kdef["grain"] == "mois":
            res = k.compare(s, window_months, kdef.get("unit", ""))
        else:
            last = sorted(s)[-1]
            res = {"periode": last, "valeur": s[last], "points": len(s)}
        f = c.Finding(kind="kpi", title=kdef["label"] + (f" - {dim}" if dim else ""), value=res["valeur"],
                      unit=kdef.get("unit", ""), period=res["periode"], evidence=ev)
        findings.append(f)
        results.append({"dimension": dim, "constat_id": f.id, **res})
        keep = sorted(s)[-last_n:]
        series += [{"dimension": dim, "periode": p, "valeur": s[p]} for p in keep]
    issues = c.validate_result(c.AgentResult(agent="analyst", status="reussi", findings=findings))
    if issues:
        raise ToolError("Résultat non conforme au contrat : " + "; ".join(issues))
    return {"equipe": cfg.team_id, "kpi": kpi_id, "libelle": kdef["label"], "unite": kdef.get("unit", ""),
            "grain": kdef["grain"], "sens": kdef.get("direction", ""), "definition": _definition(kdef),
            "resultats": results, "serie": series, "constats": [c.to_dict(f) for f in findings],
            "preuve": c.to_dict(ev), "notes_donnees": notes}


def eia_forecast(ctx: ToolContext, team_id: str, kpi_id: str, horizon: int = 0) -> dict:
    cfg = _team(team_id)
    fcfg = cfg.forecast or {}
    allowed = fcfg.get("kpis") or []
    if kpi_id not in allowed:
        raise ToolError(f"Prévision non prévue pour {kpi_id} dans la configuration de l'équipe. "
                        f"KPI prévisibles : {', '.join(allowed) or 'aucun'}")
    kdef, points, ev, notes = fetch_kpi(ctx, cfg, kpi_id, "eia_forecast",
                                        drop_incomplete=fcfg.get("exclude_last_incomplete_month", True))
    if kdef["grain"] != "mois" or any(p["dimension"] for p in points):
        raise ToolError(f"Prévision possible uniquement sur un KPI mensuel global ; {kpi_id} ne l'est pas")
    h = int(horizon or fcfg.get("horizon", 3))
    try:
        run = fc_mod.forecast([p["period"] for p in points], [p["value"] for p in points], horizon=h,
                              season_length=int(fcfg.get("season_length", 12)),
                              test_points=int(fcfg.get("test_points", 6)),
                              max_error_pct=float(fcfg.get("max_error_pct", 15)), metric=kpi_id, evidence=ev)
    except fc_mod.ForecastError as e:
        raise ToolError(f"Prévision impossible pour {kpi_id} : {e}") from e
    f = run.forecast
    issues = c.validate_result(c.AgentResult(agent="prediction", status="reussi", forecasts=[f]))
    if issues:
        raise ToolError("Prévision non conforme au contrat : " + "; ".join(issues))
    hist = {p["period"]: p["value"] for p in points}
    vs_ly = []
    for p in f.points:
        base = hist.get(k.month_add(p.period, -12))
        vs_ly.append({"periode": p.period, "prevu": p.value, "n_1": base, "variation_pct": k.pct(p.value, base)})
    total = sum(p.value for p in f.points)
    base_total = sum(x["n_1"] for x in vs_ly) if all(x["n_1"] is not None for x in vs_ly) else None
    return {"equipe": cfg.team_id, "kpi": kpi_id, "libelle": kdef["label"], "unite": kdef.get("unit", ""),
            "prevision": c.to_dict(f), "tests_methodes": run.backtests, "comparaison_n_1": vs_ly,
            "total_horizon": {"prevu": round(total, 2), "n_1": base_total, "variation_pct": k.pct(total, base_total)},
            "preuve": c.to_dict(ev), "notes_donnees": notes}


_TEAM = {"type": "string", "description": "Identifiant de l'équipe métier (ex. sales)"}
_KPI = {"type": "string", "description": "Identifiant du KPI défini dans la configuration de l'équipe"}

# Outils EIA : contrats prêts, branchés au catalogue et à HAKIM à l'étape 4.
EIA_KPI_TOOLS: list[ToolSpec] = [
    ToolSpec(
        tool_id="eia_kpi", name="KPI d'équipe", category="EIA",
        description=("Calcule un KPI défini dans la configuration d'une équipe métier (requête validée, lecture seule) : "
                     "dernière valeur, variation mensuelle, variation N-1 sur une fenêtre de mois, série récente, par "
                     "dimension le cas échéant. Le mois en cours est exclu. Chaque valeur porte un identifiant de "
                     "constat et sa preuve ; citer ces valeurs sans les recalculer."),
        input_schema={"type": "object", "properties": {
            "team_id": _TEAM, "kpi_id": _KPI,
            "dimension": {"type": "string", "description": "Valeur de dimension à isoler (ex. une région), facultatif"},
            "window_months": {"type": "integer", "minimum": 1, "maximum": 12,
                              "description": "Fenêtre de comparaison N-1 en mois (défaut 1)"},
            "last_n": {"type": "integer", "minimum": 1, "maximum": 36,
                       "description": "Nombre de périodes récentes renvoyées par dimension (défaut 13)"}},
            "required": ["team_id", "kpi_id"]},
        output_schema={"type": "object", "properties": {"resultats": {"type": "array"}, "serie": {"type": "array"},
                       "constats": {"type": "array"}, "preuve": {"type": "object"}}},
        executor="tools.eia_kpi_tools:eia_kpi"),
    ToolSpec(
        tool_id="eia_forecast", name="Prévision d'un KPI d'équipe", category="EIA",
        description=("Prévoit un KPI mensuel autorisé à la prévision par la configuration de l'équipe. Compare des "
                     "méthodes simples sur les derniers mois connus, retient la plus précise et indique si la prévision "
                     "est fiable (erreur de test sous le seuil de l'équipe). Renvoie les points prévus, une plage "
                     "basse-haute, la comparaison avec N-1 et les hypothèses. Ne pas présenter une prévision non "
                     "fiable comme une certitude."),
        input_schema={"type": "object", "properties": {
            "team_id": _TEAM, "kpi_id": _KPI,
            "horizon": {"type": "integer", "minimum": 1, "maximum": 12,
                        "description": "Nombre de mois à prévoir (défaut : configuration de l'équipe)"}},
            "required": ["team_id", "kpi_id"]},
        output_schema={"type": "object", "properties": {"prevision": {"type": "object"},
                       "tests_methodes": {"type": "object"}, "comparaison_n_1": {"type": "array"}}},
        executor="tools.eia_kpi_tools:eia_forecast"),
]
