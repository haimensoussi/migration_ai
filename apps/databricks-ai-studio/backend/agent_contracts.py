"""Phase 1 Agentic Mesh : l'agent comme produit (fiche contrat versionnée + indicateurs de qualité quotidiens).

Tables (dataops_dev.ai_studio, DDL dans database/schema.sql) :
- agent_contracts  : 1 ligne par agent et par version de contrat (historique conservé, la plus récente fait foi) ;
- agent_kpi_daily  : 1 ligne par jour et par agent, recalculée depuis conversations et tool_calls.
Les règles et seuils propres à SNCF Réseau ne sont pas fixés ici : statut de validation « a_valider » par défaut.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

DOMAINES = ["Supply Chain", "PTE", "UDR", "Transverse"]
STATUTS = {"a_valider": "À valider", "valide": "Validé", "refuse": "Refusé"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
MIN_PERIMETRE = 20
REVUE_MOIS = 6
MAX_TEXT = 2000

# Champ -> libellé (ordre d'affichage) ; tous obligatoires pour une fiche complète
REQUIRED = {
    "domaine": "Domaine",
    "perimetre": "Périmètre métier",
    "donnees": "Données lues",
    "limites": "Limites connues",
    "responsable_metier": "Responsable métier",
    "date_revue": "Date de revue",
}


def default_review_date(today: dt.date | None = None) -> dt.date:
    t = today or dt.date.today()
    m = t.month - 1 + REVUE_MOIS
    y, m = t.year + m // 12, m % 12 + 1
    return dt.date(y, m, min(t.day, 28))


def _date(v: Any) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def derive_actions(tool_ids: list | None, specs: dict) -> list[dict]:
    """Actions possibles déduites de la configuration (jamais déclarées à la main) : outils et agents consultés."""
    out = []
    for tid in tool_ids or []:
        tid = str(tid)
        if tid.startswith("agent:"):
            out.append({"id": tid, "type": "agent", "ecriture": False, "validation": False})
            continue
        s = specs.get(tid)
        out.append({"id": tid, "type": "outil", "ecriture": not getattr(s, "read_only", True) if s else None,
                    "validation": bool(getattr(s, "requires_confirmation", False)) if s else None})
    return out


def normalize(c: dict | None, knowledge_tables: list | None = None) -> dict:
    """Fiche nettoyée ; données lues préremplies avec les tables autorisées de l'agent."""
    c = dict(c or {})
    donnees = (c.get("donnees") or "").strip() or "\n".join(knowledge_tables or [])
    statut = c.get("statut_validation") if c.get("statut_validation") in STATUTS else "a_valider"
    return {
        "domaine": c.get("domaine") if c.get("domaine") in DOMAINES else "",
        "perimetre": (c.get("perimetre") or "").strip()[:MAX_TEXT],
        "donnees": donnees[:MAX_TEXT],
        "limites": (c.get("limites") or "").strip()[:MAX_TEXT],
        "responsable_metier": (c.get("responsable_metier") or "").strip().lower(),
        "date_revue": _date(c.get("date_revue")),
        "statut_validation": statut,
        "actions": c.get("actions") if isinstance(c.get("actions"), list) else [],
    }


def missing(c: dict) -> list[str]:
    """Libellés des champs manquants ou invalides (fiche complète si vide)."""
    n = normalize(c)
    out = []
    if not n["domaine"]:
        out.append(REQUIRED["domaine"])
    if len(n["perimetre"]) < MIN_PERIMETRE:
        out.append(f"{REQUIRED['perimetre']} ({MIN_PERIMETRE} caractères au moins)")
    if not n["donnees"]:
        out.append(REQUIRED["donnees"])
    if not n["limites"]:
        out.append(REQUIRED["limites"])
    if not EMAIL.match(n["responsable_metier"]):
        out.append(f"{REQUIRED['responsable_metier']} (e-mail)")
    if not n["date_revue"]:
        out.append(REQUIRED["date_revue"])
    return out


def completeness(c: dict | None) -> float:
    """Part des champs obligatoires renseignés et valides (0 à 1)."""
    if not c:
        return 0.0
    return round(1 - len(missing(c)) / len(REQUIRED), 2)


def review_overdue(c: dict | None, today: dt.date | None = None) -> bool:
    d = _date((c or {}).get("date_revue"))
    return bool(d and d < (today or dt.date.today()))


def changed(old: dict | None, new: dict) -> bool:
    """Vrai si le contenu diffère (évite une nouvelle version à chaque enregistrement de l'agent)."""
    if not old:
        return True
    keys = ("domaine", "perimetre", "donnees", "limites", "responsable_metier", "date_revue", "actions")
    a, b = normalize(old), normalize(new)
    return any(a[k] != b[k] for k in keys)


def summarize_kpi(rows: list[dict]) -> dict:
    """Agrège des lignes agent_kpi_daily (période) en un résumé affichable ; taux nul si aucun appel."""
    def tot(k):
        return sum(int(r.get(k) or 0) for r in rows)
    calls, ok = tot("appels_outils"), tot("appels_succes")
    rep = tot("reponses")
    lat = sum(float(r.get("latence_moy_ms") or 0) * int(r.get("reponses") or 0) for r in rows)
    return {"jours_actifs": sum(1 for r in rows if int(r.get("questions") or 0) or int(r.get("appels_outils") or 0)),
            "conversations": tot("conversations"), "questions": tot("questions"), "reponses": rep,
            "appels_outils": calls, "appels_succes": ok, "appels_erreur": tot("appels_erreur"),
            "appels_refuse": tot("appels_refuse"),
            "taux_succes_outils": round(ok / calls, 3) if calls else None,
            "latence_moy_ms": round(lat / rep) if rep else None}


def kpi_refresh_sql(kpi_table: str, conv_table: str, calls_table: str, days: int) -> str:
    """Recalcul idempotent des N derniers jours (une seule instruction : remplacement atomique de la fenêtre)."""
    n = int(days)
    if not 1 <= n <= 3660:
        raise ValueError("days doit être compris entre 1 et 3660")
    win = f"date_sub(current_date(), {n - 1})"
    return f"""
INSERT INTO {kpi_table} REPLACE WHERE jour >= {win}
WITH conv AS (
  SELECT to_date(created_at) AS jour, agent_id,
         count(DISTINCT conversation_id) AS conversations,
         count(DISTINCT user_name) AS utilisateurs,
         count_if(role = 'user') AS questions,
         count_if(role = 'assistant' AND latency_ms IS NOT NULL) AS reponses,
         avg(CASE WHEN role = 'assistant' THEN latency_ms END) AS latence_moy_ms,
         max(CASE WHEN role = 'assistant' THEN latency_ms END) AS latence_max_ms
  FROM {conv_table} WHERE to_date(created_at) >= {win} GROUP BY ALL),
calls AS (
  SELECT to_date(created_at) AS jour, agent_id, count(*) AS appels_outils,
         count_if(status = 'succes') AS appels_succes, count_if(status = 'erreur') AS appels_erreur,
         count_if(status = 'refuse') AS appels_refuse, avg(duration_ms) AS duree_outil_moy_ms
  FROM {calls_table} WHERE to_date(created_at) >= {win} GROUP BY ALL)
SELECT coalesce(c.jour, t.jour) AS jour, coalesce(c.agent_id, t.agent_id) AS agent_id,
       coalesce(c.conversations, 0) AS conversations, coalesce(c.utilisateurs, 0) AS utilisateurs,
       coalesce(c.questions, 0) AS questions, coalesce(c.reponses, 0) AS reponses,
       CAST(c.latence_moy_ms AS DOUBLE) AS latence_moy_ms, CAST(c.latence_max_ms AS BIGINT) AS latence_max_ms,
       coalesce(t.appels_outils, 0) AS appels_outils, coalesce(t.appels_succes, 0) AS appels_succes,
       coalesce(t.appels_erreur, 0) AS appels_erreur, coalesce(t.appels_refuse, 0) AS appels_refuse,
       CASE WHEN t.appels_outils > 0 THEN t.appels_succes / t.appels_outils END AS taux_succes_outils,
       CAST(t.duree_outil_moy_ms AS DOUBLE) AS duree_outil_moy_ms, current_timestamp() AS computed_at
FROM conv c FULL OUTER JOIN calls t ON c.jour = t.jour AND c.agent_id = t.agent_id"""


class ContractRepository:
    """Lecture / écriture des fiches contrat et des indicateurs (SqlClient de l'App)."""

    def __init__(self, sql, settings):
        self.sql, self.s = sql, settings

    def _row(self, r: dict) -> dict:
        out = dict(r)
        try:
            out["actions"] = json.loads(r.get("actions") or "[]")
        except (TypeError, ValueError):
            out["actions"] = []
        out["date_revue"] = _date(r.get("date_revue"))
        return out

    def latest_all(self) -> dict[str, dict]:
        r = self.sql.query(f"""
            SELECT * FROM {self.s.table('agent_contracts')}
            QUALIFY row_number() OVER (PARTITION BY agent_id ORDER BY version DESC) = 1""")
        return {x["agent_id"]: self._row(x) for x in r["rows"]}

    def latest(self, agent_id: str) -> dict | None:
        r = self.sql.query(f"SELECT * FROM {self.s.table('agent_contracts')} WHERE agent_id = :a "
                           "ORDER BY version DESC LIMIT 1", {"a": agent_id})
        return self._row(r["rows"][0]) if r["rows"] else None

    def history(self, agent_id: str) -> list[dict]:
        r = self.sql.query(f"SELECT version, created_by, created_at, statut_validation FROM "
                           f"{self.s.table('agent_contracts')} WHERE agent_id = :a ORDER BY version DESC",
                           {"a": agent_id})
        return r["rows"]

    def save(self, agent_id: str, contract: dict, user: str) -> int | None:
        """Ajoute une version si le contenu a changé ; renvoie la version créée (None si inchangé).

        Toute modification repasse la fiche « à valider » : la validation métier porte sur un contenu précis.
        """
        old = self.latest(agent_id)
        new = normalize(contract)
        if not changed(old, new):
            return None
        version = int(old["version"]) + 1 if old else 1
        self.sql.execute(f"""
            INSERT INTO {self.s.table('agent_contracts')} (agent_id, version, domaine, perimetre, donnees, actions,
              limites, responsable_metier, date_revue, statut_validation, created_by, created_at)
            VALUES (:a, CAST(:v AS INT), :d, :p, :don, :act, :l, :r, CAST(:dr AS DATE), 'a_valider', :u,
                    current_timestamp())""",
            {"a": agent_id, "v": version, "d": new["domaine"], "p": new["perimetre"], "don": new["donnees"],
             "act": json.dumps(new["actions"], ensure_ascii=False), "l": new["limites"],
             "r": new["responsable_metier"], "dr": new["date_revue"].isoformat() if new["date_revue"] else None,
             "u": user})
        return version

    def refresh_kpi(self, days: int = 35) -> None:
        self.sql.execute(kpi_refresh_sql(self.s.table("agent_kpi_daily"), self.s.table("conversations"),
                                         self.s.table("tool_calls"), days))

    def kpi_rows(self, days: int = 30, agent_id: str | None = None) -> list[dict]:
        n = int(days)
        where = "AND agent_id = :a" if agent_id else ""
        r = self.sql.query(f"SELECT * FROM {self.s.table('agent_kpi_daily')} WHERE jour >= "
                           f"date_sub(current_date(), {n - 1}) {where} ORDER BY jour",
                           {"a": agent_id} if agent_id else None)
        return r["rows"]

    def kpi_by_agent(self, days: int = 30) -> dict[str, dict]:
        rows: dict[str, list] = {}
        for r in self.kpi_rows(days):
            rows.setdefault(r["agent_id"], []).append(r)
        return {a: summarize_kpi(v) for a, v in rows.items()}

    def last_refresh(self):
        r = self.sql.query(f"SELECT max(computed_at) AS t FROM {self.s.table('agent_kpi_daily')}")
        return r["rows"][0]["t"] if r["rows"] else None
