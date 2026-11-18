"""Composants d'affichage communs (conversion des resultats SQL, indicateurs, messages)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

NUMERIC = {"INT", "LONG", "BIGINT", "SHORT", "SMALLINT", "TINYINT", "BYTE", "DOUBLE", "FLOAT", "DECIMAL"}


def to_df(result: dict) -> pd.DataFrame:
    """Resultat SqlClient (valeurs texte) -> DataFrame type selon le manifeste."""
    df = pd.DataFrame(result.get("rows") or [], columns=result.get("columns") or None)
    for col, typ in (result.get("types") or {}).items():
        if col not in df.columns or not typ:
            continue
        t = typ.upper()
        if t in NUMERIC:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif t == "BOOLEAN":
            df[col] = df[col].map(lambda v: None if v is None else str(v).lower() == "true")
        elif t in ("TIMESTAMP", "TIMESTAMP_NTZ", "DATE"):
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def num(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pct(value) -> str:
    v = num(value)
    return "n.d." if v is None else f"{v * 100:.1f} %"


def entier(value) -> str:
    v = num(value)
    return "0" if v is None else f"{int(v):,}".replace(",", " ")


def sql_error(message: str, exc: Exception) -> None:
    st.error(f"{message} : {str(exc)[:400]}")


def header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def no_source() -> None:
    st.warning("Aucune source selectionnee. Choisissez une source dans la barre laterale.")
    st.stop()
