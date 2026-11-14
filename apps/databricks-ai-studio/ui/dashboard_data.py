"""Lectures d'indicateurs pour l'accueil (requêtes en lecture seule sur les tables de configuration).

Placées dans la couche interface pour ne pas modifier le backend ; elles réutilisent le client SQL
du service principal de l'App, limité au schéma de configuration.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from ui import state


def _q(sql: str) -> list[dict]:
    repo = state.repository()
    return repo.sql.query(sql.replace("{P}", repo.s.prefix))["rows"]


@st.cache_data(ttl=60, show_spinner=False)
def trends() -> dict:
    a = _q("""SELECT count(*) AS n FROM {P}.`agents`
              WHERE status <> 'archive' AND created_at >= date_trunc('MONTH', current_timestamp())""")[0]
    c = _q("""SELECT
        count(DISTINCT CASE WHEN created_at >= current_timestamp() - INTERVAL 30 DAYS THEN conversation_id END) AS n30,
        count(DISTINCT CASE WHEN created_at < current_timestamp() - INTERVAL 30 DAYS
                             AND created_at >= current_timestamp() - INTERVAL 60 DAYS THEN conversation_id END) AS p30
        FROM {P}.`conversations`""")[0]
    n30, p30 = int(c["n30"] or 0), int(c["p30"] or 0)
    conv = f"{(n30 - p30) / p30 * 100:+.0f} %" if p30 else (f"+{n30} sur 30 j" if n30 else "")
    return {"agents_mois": int(a["n"] or 0), "conversations": conv}


@st.cache_data(ttl=60, show_spinner=False)
def activity_7_days() -> list[dict]:
    rows = _q("""SELECT to_date(created_at) AS jour, count(DISTINCT conversation_id) AS n
                 FROM {P}.`conversations` WHERE created_at >= date_sub(current_date(), 6) GROUP BY 1""")
    by_day = {str(r["jour"]): int(r["n"] or 0) for r in rows}
    today = dt.date.today()
    days = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
    return [{"jour": d, "conversations": by_day.get(d.isoformat(), 0)} for d in days]
