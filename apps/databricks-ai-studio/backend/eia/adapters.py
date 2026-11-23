"""EIA Core - adaptateurs des interfaces d'alerting (source de KPI, canal d'envoi).

Seuls ces adaptateurs connaissent l'extérieur. Les remplacer ne change pas le moteur (backend/eia/alerting.py).
- SqlKpiSource : tout client exposant query(statement, params=None, row_limit=None) -> {rows, truncated}
  (SqlClient de l'App aujourd'hui ; un client REST ou un autre moteur SQL demain).
- PowerAutomateNotifier : flux HTTPS Power Automate (déclencheur HTTP), même contrat que Smart Office.
- MemoryNotifier : essais à blanc et tests (aucun envoi).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from backend import sql_guard
from backend.eia import contracts as c
from backend.eia import kpi as k
from backend.eia.alerting import ACTOR, KpiData
from backend.eia.team_config import ALIAS, TeamConfig

MAX_KPI_ROWS = 5000


class SourceError(RuntimeError):
    pass


class SqlKpiSource:
    def __init__(self, client: Any, max_rows: int = MAX_KPI_ROWS):
        self.client, self.max_rows = client, max_rows

    def fetch(self, cfg: TeamConfig, kpi_id: str, today: dt.date) -> KpiData:
        kdef = cfg.kpi(kpi_id)
        statement = sql_guard.check_read_only(cfg.kpi_sql(kpi_id))       # déjà contrôlé au chargement : défense en profondeur
        r = self.client.query(statement, row_limit=self.max_rows)
        if r.get("truncated"):
            raise SourceError(f"Résultat tronqué au-delà de {self.max_rows} lignes")
        rows = r.get("rows") or []
        points, empty = k.to_points(rows, kdef["grain"])
        excluded: list[str] = []
        if kdef["grain"] == "mois":
            points, excluded = k.drop_incomplete(points, today)
        if not points:
            raise SourceError(f"Aucune valeur exploitable ({len(rows)} ligne(s) lue(s))")
        sources = ", ".join(cfg.sources[a] for a in sorted(set(ALIAS.findall(kdef["sql"]))))
        ev = c.Evidence(tool=ACTOR, source=sources, query=statement,
                        produced_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        return KpiData(kdef, points, ev, {"lignes_lues": len(rows), "valeurs_vides": empty,
                                          "mois_exclus_incomplets": excluded})


class MemoryNotifier:
    name = "memoire"

    def __init__(self, fail: Exception | None = None):
        self.sent: list[dict] = []
        self.fail = fail

    def send(self, subject: str, body: str, alerts: list[dict], run_id: str) -> dict:
        if self.fail:
            raise self.fail
        self.sent.append({"subject": subject, "body": body, "alerts": [a["alert_id"] for a in alerts], "run_id": run_id})
        return {"http_status": 200, "reponse_flux": "simulation"}


class PowerAutomateNotifier:
    """Envoi via le flux Power Automate. L'URL (signature SAS) est un secret lu dans l'environnement par `post`.

    Le flux s'exécute avec la connexion Office 365 de son propriétaire : les messages partent de sa boîte.
    """
    name = "power_automate"

    def __init__(self, notifications: dict, post: Callable[[dict], dict] | None = None,
                 check_recipients: Callable[[str], None] | None = None):
        if notifications.get("status") != "valide":
            raise ValueError("Canal Power Automate non validé dans la configuration de l'équipe")
        self.n = notifications
        if post is None or check_recipients is None:
            from tools import power_automate as pa      # contrôle d'hôte HTTPS Power Platform et des domaines
            post = post or pa.post_flow
            check_recipients = check_recipients or pa._check_recipients
        self.post, self.check = post, check_recipients

    def payload(self, subject: str, body: str, run_id: str) -> dict:
        to = ";".join(self.n["recipients"])
        return {"sessionId": run_id, "question": subject, "technology": self.n["technology"],
                "operation": self.n["operation"], "parameters": {"to": to, "subject": subject, "body": body},
                "status": self.n.get("flow_status", "approved"), "requires_confirmation": False}

    def send(self, subject: str, body: str, alerts: list[dict], run_id: str) -> dict:
        p = self.payload(subject, body, run_id)
        self.check(p["parameters"]["to"])
        return self.post(p)
