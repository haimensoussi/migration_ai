"""Accès aux services depuis Streamlit : cache des clients, identité de l'utilisateur."""
from __future__ import annotations

import hashlib

import streamlit as st

from backend.agent_repository import AgentRepository
from backend.agent_runtime import AgentRuntime, ToolEvent
from backend.config import Settings, load_settings
from backend.model_client import ModelClient
from backend.security import UserAuthMissing, UserIdentity, app_client, resolve_user
from backend.sql_client import SqlClient
from backend.tool_registry import ToolContext, ToolRegistry


@st.cache_resource
def settings() -> Settings:
    return load_settings()


@st.cache_resource
def _app_w():
    return app_client()


@st.cache_resource
def repository() -> AgentRepository:
    s = settings()
    return AgentRepository(SqlClient(_app_w(), s.warehouse_id, s.sql_timeout_s), s)


def _headers() -> dict:
    try:
        return dict(st.context.headers)
    except Exception:  # noqa: BLE001
        return {}


def user_session():
    """(WorkspaceClient, SqlClient, UserIdentity) de l'utilisateur ; mis en cache par jeton dans la session."""
    headers = _headers()
    token = next((v for k, v in headers.items() if k.lower() == "x-forwarded-access-token"), "")
    key = hashlib.sha256(token.encode()).hexdigest()[:16]
    cached = st.session_state.get("_user_session")
    if cached and cached[0] == key:
        return cached[1]
    w, ident = resolve_user(headers, _app_w().config.host)
    s = settings()
    value = (w, SqlClient(w, s.warehouse_id, s.sql_timeout_s), ident)
    st.session_state["_user_session"] = (key, value)
    return value


def current_user() -> UserIdentity:
    try:
        return user_session()[2]
    except UserAuthMissing:
        h = _headers()
        email = next((v for k, v in h.items() if k.lower() == "x-forwarded-email"), "inconnu")
        return UserIdentity(email=email, mode="jeton absent")


@st.cache_data(ttl=60, show_spinner=False)
def cached_tools():
    return repository().list_tools()


def registry() -> ToolRegistry:
    return ToolRegistry(cached_tools())


@st.cache_data(ttl=300, show_spinner=False)
def _chat_endpoints(_w, key: str):
    return ModelClient(_w).list_chat_endpoints()


def chat_endpoints() -> list[str]:
    w, _, ident = user_session()
    return [e["name"] for e in _chat_endpoints(w, ident.email)]


def build_runtime(on_tool_event=None) -> AgentRuntime:
    w, sql, _ = user_session()
    ctx = ToolContext(sql=sql, workspace=w, max_rows=settings().max_rows)
    return AgentRuntime(ModelClient(w), registry(), ctx, on_tool_event=on_tool_event)


def refresh_data():
    cached_tools.clear()
    st.session_state.pop("_agents_cache", None)


def agents(force: bool = False) -> list[dict]:
    if force or "_agents_cache" not in st.session_state:
        st.session_state["_agents_cache"] = repository().list_agents()
    return st.session_state["_agents_cache"]


__all__ = ["settings", "repository", "user_session", "current_user", "registry", "chat_endpoints",
           "build_runtime", "refresh_data", "agents", "ToolEvent", "UserAuthMissing"]
