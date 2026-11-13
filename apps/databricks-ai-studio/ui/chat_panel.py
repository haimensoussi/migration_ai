"""Panneau de conversation réutilisable (Chat & Test, étape 6 de l'Agent Builder)."""
from __future__ import annotations

import json
import uuid

import pandas as pd
import streamlit as st

from backend.agent_runtime import AgentConfig, ToolEvent, TurnResult
from ui import state

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


def render_chat(cfg: AgentConfig, key: str, persist: bool = True):
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

    for item in s["display"]:
        if item["kind"] == "event":
            with st.chat_message("assistant", avatar=":material/handyman:"):
                _show_event(item["event"])
        else:
            with st.chat_message(item["role"]):
                st.markdown(item["content"])

    repo = state.repository()

    def log_event(ev: ToolEvent):
        if persist:
            repo.log_tool_call(s["conversation_id"], cfg.agent_id, user.email, ev)

    def handle(res: TurnResult, user_msg: dict | None):
        for ev in res.events:
            s["display"].append({"kind": "event", "event": _ev_dict(ev)})
        if res.pending:
            s["pending"] = {"pending": res.pending, "messages": res.messages}
        else:
            s["pending"] = None
            s["history"] = [m for m in res.messages if m["role"] != "system"]
            s["display"].append({"kind": "msg", "role": "assistant", "content": res.final_text or "(réponse vide)"})
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
                        rt = state.build_runtime(on_tool_event=log_event)
                        res = rt.resume(cfg, s["pending"]["messages"], {p["call"]["id"]: decision})
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
                rt = state.build_runtime(on_tool_event=log_event)
                res = rt.run(cfg, s["history"] + [user_msg])
                handle(res, user_msg)
            except state.UserAuthMissing as e:
                s["display"].append({"kind": "msg", "role": "assistant", "content": f"**Accès refusé** : {e}"})
            except Exception as e:  # noqa: BLE001
                s["display"].append({"kind": "msg", "role": "assistant",
                                     "content": f"**Erreur d'exécution** : {e}"})
        st.rerun()
