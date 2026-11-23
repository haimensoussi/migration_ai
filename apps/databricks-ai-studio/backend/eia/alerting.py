"""EIA Core - moteur d'alerting, indépendant de la plateforme d'exécution.

Calcule les alertes par du code (jamais par le modèle) à partir des règles de la configuration d'équipe.
Trois interfaces injectables : source de KPI, enregistrement (EiaRepository) et canal d'envoi.
Aucune dépendance à Spark, dbutils ou aux Jobs : `run_alerting` se lance depuis n'importe quel planificateur
(fonction Azure appelée par Power Automate, Job, ligne de commande, App).

Conventions :
- seuil franchi : valeur <= seuil pour seuil_bas et les variations (baisse défavorable), valeur >= seuil pour seuil_haut ;
- erreur technique (source, prévision impossible, envoi) = alerte de type « technique », jamais mélangée au métier ;
- règle désactivée : ignorée ; règle « a_valider » : évaluée et signalée comme telle dans chaque alerte.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.eia import contracts as c
from backend.eia import forecast as fc_mod
from backend.eia import kpi as k
from backend.eia.team_config import TeamConfig

LOW_TYPES = ("seuil_bas", "variation_annuelle", "variation_prevision")
SEV_RANK = {"info": 0, "attention": 1, "critique": 2}
ACTOR = "eia_alerting"


# ---------------- interfaces ----------------

@dataclass
class KpiData:
    kdef: dict
    points: list[dict]                     # {period, dimension, value}, mois en cours exclu
    evidence: c.Evidence
    notes: dict = field(default_factory=dict)


class KpiSource(Protocol):
    def fetch(self, cfg: TeamConfig, kpi_id: str, today: dt.date) -> KpiData: ...


class Notifier(Protocol):
    name: str

    def send(self, subject: str, body: str, alerts: list[dict], run_id: str) -> dict: ...


# ---------------- évaluation ----------------

def breach(value: float, rule_type: str, thresholds: dict) -> tuple[str, float] | None:
    """Gravité la plus forte franchie (critique avant attention) ; None si aucun seuil franchi."""
    low = rule_type in LOW_TYPES
    for sev in ("critique", "attention", "info"):
        t = thresholds.get(sev)
        if t is not None and (value <= t if low else value >= t):
            return sev, float(t)
    return None


def _fmt(v: float | None, unit: str = "") -> str:
    if v is None:
        return "n/d"
    s = f"{v:,.2f}".replace(",", "\u202f").replace(".", ",")
    return f"{s} {unit}".strip()


@dataclass
class Measure:
    scope: str
    period: str
    value: float
    unit: str
    detail: str = ""


def _window_value(series: dict[str, float], window: int, rate: bool) -> tuple[str, float] | None:
    last = max(series)
    win = [k.month_add(last, -i) for i in range(window)]
    if any(p not in series for p in win):
        return None
    vals = [series[p] for p in win]
    period = last if window == 1 else f"{win[-1]}..{last}"
    return period, (sum(vals) / len(vals) if rate else sum(vals))


def measures(rule: dict, data: KpiData, forecast_cfg: dict) -> tuple[list[Measure], list[str]]:
    """Valeurs à comparer aux seuils (une par dimension) et motifs de non-évaluation."""
    kdef, rtype = data.kdef, rule["type"]
    unit = kdef.get("unit", "")
    rate = unit in k.RATE_UNITS
    window = max(1, int(rule.get("window_months") or 1))
    out: list[Measure] = []
    skipped: list[str] = []
    for dim, series in k.by_dimension(data.points).items():
        label = dim or "global"
        if not series:
            continue
        if kdef["grain"] != "mois":
            if rtype != "seuil_bas" and rtype != "seuil_haut":
                skipped.append(f"{label} : type {rtype} non applicable à un KPI {kdef['grain']}")
                continue
            last = max(series)
            out.append(Measure(dim, last, series[last], unit))
        elif rtype in ("seuil_bas", "seuil_haut"):
            w = _window_value(series, window, rate)
            if w is None:
                skipped.append(f"{label} : mois manquants pour la fenêtre de {window} mois")
                continue
            out.append(Measure(dim, w[0], w[1], unit, "moyenne simple des mois" if rate and window > 1 else ""))
        elif rtype == "variation_annuelle":
            cmp = k.compare(series, window, unit)
            v = cmp.get("variation_annuelle_points" if rate else "variation_annuelle_pct")
            if v is None:
                skipped.append(f"{label} : {cmp.get('note') or 'variation N-1 non calculable'}")
                continue
            out.append(Measure(dim, cmp["fenetre"], v, "points" if rate else "%",
                               f"{_fmt(cmp['valeur_fenetre'], unit)} contre {_fmt(cmp['valeur_fenetre_n_1'], unit)} un an plus tôt"))
        elif rtype == "variation_prevision":
            if dim:
                skipped.append(f"{label} : prévision limitée aux KPI globaux")
                continue
            periods = sorted(series)
            run = fc_mod.forecast(periods, [series[p] for p in periods], horizon=window,
                                  season_length=int(forecast_cfg.get("season_length", 12)),
                                  test_points=int(forecast_cfg.get("test_points", 6)),
                                  max_error_pct=float(forecast_cfg.get("max_error_pct", 15)), metric=kdef["id"])
            f = run.forecast
            if not f.reliable:
                skipped.append(f"prévision non fiable, règle non évaluée : {f.reliability_note}")
                continue
            base = [series.get(k.month_add(p.period, -12)) for p in f.points]
            if any(b is None for b in base):
                skipped.append("mois N-1 manquants pour comparer la prévision")
                continue
            total = sum(p.value for p in f.points)
            v = k.pct(total, sum(base))
            if v is None:
                continue
            out.append(Measure("", f"{f.points[0].period}..{f.points[-1].period}", v, "%",
                               f"prévu {_fmt(total, unit)} contre {_fmt(sum(base), unit)} (méthode {f.method}, "
                               f"erreur de test {f.backtest_error_pct} %)"))
    return out, skipped


def evaluate_rule(cfg: TeamConfig, rule: dict, data: KpiData) -> tuple[list[c.Alert], list[str]]:
    ms, skipped = measures(rule, data, cfg.forecast or {})
    alerts = []
    for m in ms:
        hit = breach(m.value, rule["type"], rule["thresholds"])
        if not hit:
            continue
        sev, threshold = hit
        where = f" - {m.scope}" if m.scope else ""
        status = "seuil à valider" if rule.get("status") == "a_valider" else "seuil validé"
        msg = (f"{data.kdef['label']}{where} : {_fmt(m.value, m.unit)} sur {m.period} "
               f"(seuil {sev} {_fmt(threshold, m.unit)}, {status})." + (f" {m.detail}." if m.detail else "")
               + f" Règle {rule['id']}.")
        alerts.append(c.Alert(rule_id=rule["id"], severity=sev, title=f"{rule.get('label', rule['id'])}{where}",
                              message=msg, metric=data.kdef["id"], scope=m.scope, period=m.period,
                              observed=round(m.value, 4), threshold=threshold,
                              rule_status=rule.get("status", "a_valider"), evidence=data.evidence))
    return alerts, skipped


def technical_alert(rule_id: str, title: str, message: str, metric: str, today: dt.date) -> c.Alert:
    return c.Alert(rule_id=rule_id, severity="attention", title=title, message=message[:2000], kind="technique",
                   metric=metric, period=today.isoformat(), rule_status="valide",
                   evidence=c.Evidence(tool=ACTOR, source=metric, query=""))


# ---------------- envoi ----------------

def notification_plan(cfg: TeamConfig) -> tuple[bool, str, str]:
    """(envoi autorisé, gravité minimale, motif). Envoi seulement si le bloc notifications est validé."""
    n = cfg.notifications or {}
    if not n:
        return False, "critique", "aucun canal d'envoi configuré pour l'équipe"
    if n.get("status") != "valide":
        return False, n.get("min_severity", "critique"), f"canal d'envoi au statut {n.get('status')} (non validé)"
    return True, n.get("min_severity", "critique"), ""


def digest(cfg: TeamConfig, alerts: list[dict], today: dt.date) -> tuple[str, str]:
    """Message récapitulatif généré par le code (aucun texte produit par le modèle)."""
    alerts = sorted(alerts, key=lambda a: (-SEV_RANK[a["severity"]], a["rule_id"], a.get("scope") or ""))
    crit = sum(a["severity"] == "critique" for a in alerts)
    subject = f"[DISCOVERY] {cfg.name} : {len(alerts)} nouvelle(s) alerte(s), dont {crit} critique(s) - {today.isoformat()}"
    lines = [f"Contrôle du {today.isoformat()} - équipe {cfg.name}.", ""]
    lines += [f"[{a['severity'].upper()}] {a['message']}" for a in alerts]
    if any(a.get("rule_status") == "a_valider" for a in alerts):
        lines += ["", "Les seuils marqués « à valider » sont provisoires et doivent être validés par le responsable métier."]
    lines += ["", "Détail et suivi : page Notifications de DISCOVERY."]
    return subject, "\n".join(lines)


# ---------------- exécution ----------------

def run_alerting(cfg: TeamConfig, source: KpiSource, repo: Any, notifier: Notifier | None = None,
                 today: dt.date | None = None, trigger: str = "planifie", actor: str = ACTOR) -> dict:
    """Une exécution complète : règles -> alertes dédoublonnées -> envoi éventuel -> journal. Ne lève pas d'exception
    pour une règle ou un envoi en échec : l'erreur devient une alerte technique et l'exécution est « partiel »."""
    today = today or dt.date.today()
    t0 = time.monotonic()
    rules = [r for r in cfg.rules if r.get("status") != "desactive"]
    run_id = repo.start_run(cfg.team_id, trigger, f"Contrôle des alertes du {today.isoformat()}", actor,
                            {"agent": "alerting", "rules": [r["id"] for r in rules]})
    repo.save_step(run_id, "alerting", "alerting", "en_cours", attempts=1, depends_on=[], started_at=repo.clock())
    cache: dict[str, KpiData | Exception] = {}
    new, repeated, technical, per_rule = [], [], [], {}

    def record(a: c.Alert) -> None:
        d = c.to_dict(a)
        aid, is_new = repo.record_alert(cfg.team_id, run_id, d, c.fingerprint(cfg.team_id, a.rule_id, a.scope or a.metric,
                                                                               a.period))
        d["alert_id"] = aid
        (new if is_new else repeated).append(d)
        if a.kind == "technique":
            technical.append(d)

    for rule in rules:
        kid = rule["kpi"]
        if kid not in cache:
            try:
                cache[kid] = source.fetch(cfg, kid, today)
            except Exception as e:                       # source indisponible, droit manquant, requête en échec
                cache[kid] = e
                record(technical_alert("TECH_SOURCE", f"Source indisponible pour le KPI {kid}",
                                       f"{type(e).__name__} : {e}", kid, today))
        data = cache[kid]
        if isinstance(data, Exception):
            per_rule[rule["id"]] = {"statut": "non_evalue", "motif": "source indisponible"}
            continue
        try:
            alerts, skipped = evaluate_rule(cfg, rule, data)
        except Exception as e:
            record(technical_alert("TECH_RULE", f"Évaluation impossible de la règle {rule['id']}",
                                   f"{type(e).__name__} : {e}", kid, today))
            per_rule[rule["id"]] = {"statut": "erreur", "motif": str(e)[:300]}
            continue
        for a in alerts:
            record(a)
        per_rule[rule["id"]] = {"statut": "evalue", "alertes": len(alerts), "non_evalues": skipped}

    allowed, min_sev, reason = notification_plan(cfg)
    to_send = [a for a in new if a["kind"] == "metier" and SEV_RANK[a["severity"]] >= SEV_RANK[min_sev]]
    sent: dict[str, Any] = {"envoye": False, "alertes": len(to_send)}
    if to_send and not allowed:
        sent["motif"] = reason
        repo.log("run", run_id, "envoi_non_autorise", actor, {"motif": reason, "alertes": len(to_send)})
    elif to_send and notifier is None:
        sent["motif"] = "aucun canal d'envoi fourni à l'exécution"
    elif to_send:
        subject, body = digest(cfg, to_send, today)
        try:
            res = notifier.send(subject, body, to_send, run_id)
            sent.update(envoye=True, canal=notifier.name, reponse=res)
            repo.log("run", run_id, "notification_envoyee", actor,
                     {"canal": notifier.name, "alertes": [a["alert_id"] for a in to_send], "reponse": res})
        except Exception as e:
            sent["motif"] = f"échec de l'envoi : {e}"
            record(technical_alert("TECH_NOTIFY", "Échec de l'envoi des alertes", f"{type(e).__name__} : {e}",
                                   notifier.name, today))

    status = "partiel" if technical else "termine"
    business_new = [a for a in new if a["kind"] == "metier"]
    summary = (f"{len(rules)} règle(s) évaluée(s) ; {len(business_new)} nouvelle(s) alerte(s) métier, "
               f"{len([a for a in repeated if a['kind'] == 'metier'])} déjà connue(s) ; "
               f"{len(technical)} erreur(s) technique(s) ; envoi : {'oui' if sent['envoye'] else 'non'}")
    report = {"run_id": run_id, "equipe": cfg.team_id, "date": today.isoformat(), "statut": status,
              "nouvelles": new, "deja_connues": repeated, "techniques": technical, "regles": per_rule,
              "envoi": sent, "synthese": summary}
    repo.save_step(run_id, "alerting", "alerting", "reussi" if not technical else "echec",
                   output={"synthese": summary, "regles": per_rule, "envoi": {k_: v for k_, v in sent.items() if k_ != "reponse"}},
                   ended_at=repo.clock(), duration_ms=int((time.monotonic() - t0) * 1000),
                   error="; ".join(a["message"] for a in technical)[:2000] or None)
    repo.end_run(run_id, status, summary)
    return report
