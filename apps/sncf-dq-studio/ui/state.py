"""Acces aux services depuis Streamlit : clients mis en cache, identite, roles, source selectionnee."""
from __future__ import annotations

import hashlib

import streamlit as st

from backend.app_repository import AppRepository
from backend.config import Settings, load_settings, running_in_databricks_app
from backend.dq_repository import DqRepository
from backend.roles import UserRoles, resolve_roles
from backend.security import UserAuthMissing, UserIdentity, app_client, header, resolve_user
from backend.sql_client import SqlClient


@st.cache_resource
def settings() -> Settings:
    return load_settings()


@st.cache_resource
def app_w():
    """Client du service principal de l'App."""
    return app_client()


@st.cache_resource
def sp_sql() -> SqlClient:
    s = settings()
    return SqlClient(app_w(), s.warehouse_id, s.sql_timeout_s)


def _headers() -> dict:
    try:
        return dict(st.context.headers)
    except Exception:  # noqa: BLE001
        return {}


def user_session():
    """(WorkspaceClient, SqlClient, UserIdentity) de l'utilisateur, mis en cache par jeton dans la session."""
    headers = _headers()
    token = header(headers, "X-Forwarded-Access-Token") or ""
    key = hashlib.sha256(token.encode()).hexdigest()[:16]
    cached = st.session_state.get("_user_session")
    if cached and cached[0] == key:
        return cached[1]
    w, ident = resolve_user(headers, app_w().config.host, running_in_databricks_app())
    s = settings()
    value = (w, SqlClient(w, s.warehouse_id, s.sql_timeout_s), ident)
    st.session_state["_user_session"] = (key, value)
    st.session_state.pop("_roles", None)
    return value


def current_user() -> UserIdentity:
    return user_session()[2]


def app_repo() -> AppRepository:
    _, sql, _ = user_session()
    s = settings()
    return AppRepository(read_sql=sql, write_sql=sp_sql(), catalog=s.catalog, schema=s.app_schema)


def user_roles() -> UserRoles:
    if "_roles" not in st.session_state:
        ident = current_user()
        try:
            rows = app_repo().roles_rows(ident.email)
            st.session_state["_roles_error"] = None
        except Exception as e:  # noqa: BLE001  (pas d'acces a app_roles : lecteur)
            rows = []
            st.session_state["_roles_error"] = str(e)[:300]
        st.session_state["_roles"] = resolve_roles(ident.email, rows, settings().admins)
    return st.session_state["_roles"]


def sources(force: bool = False) -> list[dict]:
    if force or "_sources" not in st.session_state:
        st.session_state["_sources"] = app_repo().sources()
    return st.session_state["_sources"]


def select_source_sidebar() -> dict | None:
    """Selecteur de source (liste blanche app_sources) affiche dans la barre laterale."""
    try:
        srcs = sources()
    except Exception as e:  # noqa: BLE001
        st.sidebar.error("Liste des sources indisponible (droit SELECT sur "
                         f"{settings().app_fqn}.app_sources requis).")
        st.session_state["_sources_error"] = str(e)[:500]
        return None
    if not srcs:
        st.sidebar.warning("Aucune source active dans app_sources.")
        return None
    codes = [s["code_source"] for s in srcs]
    default = st.session_state.get("source_code") or settings().default_source
    idx = codes.index(default) if default in codes else 0
    labels = {s["code_source"]: f"{s.get('libelle') or s['code_source']} ({s['bronze_schema']})" for s in srcs}
    code = st.sidebar.selectbox("Source analysee", codes, index=idx, format_func=lambda c: labels[c])
    st.session_state["source_code"] = code
    return next(s for s in srcs if s["code_source"] == code)


def current_source() -> dict | None:
    code = st.session_state.get("source_code")
    try:
        return next((s for s in sources() if s["code_source"] == code), None)
    except Exception:  # noqa: BLE001
        return None


def dq_repo(source: dict) -> DqRepository:
    _, sql, _ = user_session()
    return DqRepository(sql, settings().catalog, source["dq_prefix"])


__all__ = ["settings", "app_w", "sp_sql", "user_session", "current_user", "app_repo", "user_roles", "sources",
           "select_source_sidebar", "current_source", "dq_repo", "UserAuthMissing"]
