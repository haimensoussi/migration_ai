"""Panneau de conversation réutilisable (Chat & Test, étape 6 de l'Agent Builder)."""
from __future__ import annotations

import dataclasses
import html
import json
import os
import uuid

import pandas as pd
import streamlit as st

from backend.agent_runtime import AgentConfig, ToolEvent, TurnResult
from ui import state
from ui.discovery_icons import (ASSETS, AVATAR_ASSISTANT, AVATAR_TOOL, AVATAR_USER, capabilities_for, chips_for,
                                chips_html, icon_img, with_presentation)

STATUS_ICON = {"succes": ":material/check_circle:", "erreur": ":material/error:", "refuse": ":material/block:"}
STATUS_TXT = {"succes": "succès", "erreur": "erreur", "refuse": "refusé"}


def _show_event(ev: dict):
    title = f"Outil `{ev['tool_id']}` : {STATUS_TXT.get(ev['status'], ev['status'])} ({ev['duration_ms']} ms)"
    with st.expander(f'{STATUS_ICON.get(ev["status"], "")} {title}'):
        st.caption("Arguments")
        st.json(ev["arguments"])
        if ev["status"] == "succes":
            res = ev["result"]
            rows = None
            if isinstance(res, dict):
                rows = res.get("lignes") or res.get("profil") or res.get("colonnes") or res.get("tables")
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            with st.popover("Résultat JSON"):
                st.json(res)
        else:
            st.error(ev["error"])


def _ev_dict(ev: ToolEvent) -> dict:
    return {"tool_id": ev.tool_id, "arguments": ev.arguments, "status": ev.status,
            "result": json.loads(json.dumps(ev.result, default=str)) if ev.result is not None else None,
            "error": ev.error, "duration_ms": ev.duration_ms}


def _avatar(path: str, fallback: str) -> str:
    return path if os.path.isfile(path) else fallback


AV = {"user": _avatar(AVATAR_USER, ":material/person:"),
      "assistant": _avatar(AVATAR_ASSISTANT, ":material/train:"),
      "tool": _avatar(AVATAR_TOOL, ":material/play_arrow:")}


def _inject_css():
    css_file = ASSETS / "css" / "chat.css"
    if css_file.is_file():
        st.markdown(f"<style>{css_file.read_text()}</style>", unsafe_allow_html=True)


def render_discovery_message(role: str, content: str, agent_name: str = "", chips: list | None = None):
    """Affiche un message DISCOVERY : avatar, nom de l'agent, icônes métier (interface) puis Markdown du modèle.

    Le contenu produit par l'agent est rendu en Markdown simple (HTML non autorisé) ; seuls l'en-tête et les
    icônes, construits par l'interface à partir de valeurs échappées, utilisent du HTML.
    """
    if role == "user":
        with st.chat_message("user", avatar=AV["user"]):
            st.markdown('<span class="dsc-msg-user"></span>', unsafe_allow_html=True)
            st.markdown(content)
        return
    with st.chat_message("assistant", avatar=AV["assistant"]):
        head = f'<div class="dsc-agent">DISCOVERY — {html.escape(agent_name)}</div>' if agent_name else ""
        st.markdown(head + chips_html([tuple(c) for c in (chips or [])]), unsafe_allow_html=True)
        st.markdown(content)


def _welcome(cfg: AgentConfig):
    caps = capabilities_for(cfg.tool_ids)
    with st.chat_message("assistant", avatar=AV["assistant"]):
        body = (f'<div class="dsc-agent">DISCOVERY — {html.escape(cfg.name or "Agent")}</div>'
                "<p>Bonjour ! Je peux vous accompagner dans l'exploration et l'analyse de vos données Databricks.</p>")
        if caps:
            body += '<div class="dsc-cap-title">Mes capacités</div>' + "".join(
                f'<div class="dsc-cap">{icon_img(i)}<span>{html.escape(t)}</span></div>' for i, t in caps)
        body += '<div class="dsc-cap-title">Par quoi souhaitez-vous commencer ?</div>'
        st.markdown(body, unsafe_allow_html=True)


def render_chat(cfg: AgentConfig, key: str, persist: bool = True, category: str | None = None):
    _inject_css()
    # Consigne de présentation ajoutée à l'exécution, après les instructions de l'agent (non enregistrée)
    run_cfg = dataclasses.replace(cfg, instructions=with_presentation(cfg.instructions))
    sk = f"chat_{key}"
    if sk not in st.session_state:
        st.session_state[sk] = {"conversation_id": uuid.uuid4().hex, "history": [], "display": [],
                                "pending": None, "next_index": 0}
    s = st.session_state[sk]
    user = state.current_user()

    top = st.columns([4, 1])
    top[0].caption(f"Modèle `{cfg.model_endpoint}` · outils : {', '.join(cfg.tool_ids) or 'aucun'} · "
                   f"identité : {user.email} ({user.mode})")
    if top[1].button("Nouvelle conversation", key=f"reset_{key}"):
        del st.session_state[sk]
        st.rerun()

    if not s["display"]:
        _welcome(cfg)
    for item in s["display"]:
        if item["kind"] == "event":
            with st.chat_message("assistant", avatar=AV["tool"]):
                st.markdown('<span class="dsc-msg-tool"></span>', unsafe_allow_html=True)
                _show_event(item["event"])
        else:
            render_discovery_message(item["role"], item["content"], item.get("agent", ""), item.get("chips"))

    repo = state.repository()

    def log_event(ev: ToolEvent):
        if persist:
            repo.log_tool_call(s["conversation_id"], cfg.agent_id, user.email, ev)

    def handle(res: TurnResult, user_msg: dict | None):
        turn_events = [_ev_dict(ev) for ev in res.events]
        for ev in turn_events:
            s["display"].append({"kind": "event", "event": ev})
        if res.pending:
            s["pending"] = {"pending": res.pending, "messages": res.messages}
        else:
            s["pending"] = None
            s["history"] = [m for m in res.messages if m["role"] != "system"]
            s["display"].append({"kind": "msg", "role": "assistant", "content": res.final_text or "(réponse vide)",
                                 "agent": cfg.name, "chips": chips_for(turn_events, category)})
        if persist:
            try:
                to_log = ([user_msg] if user_msg else []) + [m for m in res.new_messages if m["role"] != "system"]
                s["next_index"] = repo.log_messages(s["conversation_id"], cfg, user.email, to_log,
                                                    s["next_index"], res.latency_ms)
            except Exception as e:  # noqa: BLE001
                st.warning(f"Historique non enregistré : {e}")

    if s["pending"]:
        p = s["pending"]["pending"]
        with st.container(border=True):
            st.warning(f"Validation requise : l'agent veut exécuter `{p['tool']}`.")
            st.json(p["arguments"])
            c1, c2 = st.columns(2)
            decision = None
            if c1.button("Approuver", key=f"ok_{key}", type="primary"):
                decision = True
            if c2.button("Refuser", key=f"no_{key}"):
                decision = False
            if decision is not None:
                with st.spinner("Exécution..."):
                    try:
                        rt = state.build_runtime(on_tool_event=log_event, conversation_id=s["conversation_id"])
                        res = rt.resume(run_cfg, s["pending"]["messages"], {p["call"]["id"]: decision})
                        handle(res, None)
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Erreur d'exécution : {e}")
                st.rerun()

    prompt = st.chat_input("Écrivez votre message...", key=f"input_{key}", disabled=bool(s["pending"]))
    if prompt:
        user_msg = {"role": "user", "content": prompt}
        s["display"].append({"kind": "msg", "role": "user", "content": prompt})
        with st.spinner("L'agent réfléchit..."):
            try:
                rt = state.build_runtime(on_tool_event=log_event, conversation_id=s["conversation_id"])
                res = rt.run(run_cfg, s["history"] + [user_msg])
                handle(res, user_msg)
            except state.UserAuthMissing as e:
                s["display"].append({"kind": "msg", "role": "assistant", "content": f"**Accès refusé** : {e}",
                                     "agent": cfg.name, "chips": chips_for([], category, error=True)})
            except Exception as e:  # noqa: BLE001
                s["display"].append({"kind": "msg", "role": "assistant", "content": f"**Erreur d'exécution** : {e}",
                                     "agent": cfg.name, "chips": chips_for([], category, error=True)})
        st.rerun()
