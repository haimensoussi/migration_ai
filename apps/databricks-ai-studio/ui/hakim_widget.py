"""Bulle HakimAI présente sur toutes les pages : panneau de discussion, conversation conservée d'une page à l'autre."""
from __future__ import annotations

import json
import uuid

import streamlit as st

from backend import hakim
from backend.agent_runtime import AgentRuntime
from backend.model_client import ModelClient
from backend.tool_registry import ToolContext, ToolRegistry
from tools.hakim_tools import Platform
from ui import state

CSS = """<style>
.st-key-hakim_fab { position: fixed; right: 28px; bottom: 26px; z-index: 999990; width: auto !important; }
.st-key-hakim_fab button { border-radius: 28px; min-height: 52px; padding: 0 20px; background: #B0124F; color: #fff;
  border: none; box-shadow: 0 6px 18px rgba(74,25,66,.28); font-weight: 700; }
.st-key-hakim_fab button:hover { background: #4A1942; color: #fff; }
</style>"""

EXAMPLES = ["Comment créer une équipe d'agents ?", "Quels agents sont disponibles ?",
            "Pourquoi des appels d'outils échouent cette semaine ?", "Fais-moi une visite guidée"]


def _session() -> dict:
    return st.session_state.setdefault("hakim", {"conv": uuid.uuid4().hex, "history": [], "display": [], "turns": 0,
                                                  "logged": 0})


def page_context(page_title: str) -> dict:
    """Page courante et objets sélectionnés (lecture de l'état des pages, sans effet de bord)."""
    ctx = {"page": page_title}
    try:
        names = {a["agent_id"]: a["name"] for a in state.agents()}
        if st.session_state.get("chat_agent_id"):
            ctx["agent_du_chat"] = names.get(st.session_state["chat_agent_id"])
        sel = st.session_state.get("mine_sel")
        if sel:
            ctx["equipe_selectionnee"] = next((t["name"] for t in state.teams() if t["team_id"] == sel), None)
    except Exception:  # noqa: BLE001  (contexte facultatif)
        pass
    return ctx


def _runtime(page: dict):
    w, sql, ident = state.user_session()
    s = state.settings()
    trepo = state.team_repository()
    platform = Platform(state.repository(), trepo, ident.email, trepo.is_admin(ident.email), page)
    ctx = ToolContext(sql=sql, workspace=w, max_rows=s.max_rows, user_email=ident.email, platform=platform)
    return AgentRuntime(ModelClient(w), ToolRegistry(hakim.TOOLS), ctx), hakim.config(s.default_model), ident.email


def _ask(question: str, page: dict) -> None:
    s = _session()
    rt, cfg, email = _runtime(page)
    user_msg = {"role": "user", "content": question}
    s["display"].append({"role": "user", "content": question})
    try:
        with st.spinner("HakimAI réfléchit…"):
            res = rt.run(cfg, s["history"] + [user_msg])
    except Exception as e:  # noqa: BLE001
        s["display"].append({"role": "assistant", "content": f"Je n'ai pas pu répondre : {e}", "events": [], "nav": []})
        return
    s["history"] = [m for m in res.messages if m["role"] != "system"]
    s["turns"] += 1
    events = [{"outil": e.tool_id, "statut": e.status, "arguments": e.arguments, "erreur": e.error} for e in res.events]
    s["display"].append({"role": "assistant", "content": res.final_text or "(réponse vide)", "events": events,
                         "nav": hakim.navigation_targets(res.events)})
    try:   # journal d'audit : conversation et appels d'outils sous l'agent « hakimai »
        repo = state.repository()
        for ev in res.events:
            repo.log_tool_call(s["conv"], hakim.AGENT_ID, email, ev)
        s["logged"] = repo.log_messages(s["conv"], cfg, email, [user_msg] + [m for m in res.new_messages],
                                        s["logged"], res.latency_ms)
    except Exception:  # noqa: BLE001  (la réponse reste affichée si la journalisation échoue)
        pass


@st.dialog(f"{hakim.NAME} · {hakim.PERSONA}", width="large")
def _panel(page: dict) -> None:
    s = _session()
    st.caption("Je vous guide dans DISCOVERY : agents, outils, équipes, chat, monitoring. Dans cette version, je lis et "
               "j'explique ; je ne crée ni ne modifie rien. J'agis avec vos droits.")
    pending = st.session_state.pop("hakim_pending", None)
    if pending:
        if s["turns"] >= hakim.max_turns():
            st.warning("Limite de questions atteinte pour cette conversation : recommencez une conversation.")
        else:
            _ask(pending, page)
    if not s["display"]:
        cols = st.columns(2)
        for i, ex in enumerate(EXAMPLES):
            if cols[i % 2].button(ex, key=f"hakim_ex_{i}", use_container_width=True):
                _ask(ex, page)
    for n, m in enumerate(s["display"]):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            for j, nav in enumerate(m.get("nav") or []):
                st.page_link(nav["path"], label=f"Ouvrir {nav['title']}", icon=":material/arrow_forward:")
            if m.get("events"):
                with st.expander(f"{len(m['events'])} outil(s) consulté(s)"):
                    for ev in m["events"]:
                        st.markdown(f"`{ev['outil']}` · {ev['statut']}" + (f" — {ev['erreur']}" if ev.get("erreur") else ""))
                        if ev.get("arguments"):
                            st.code(json.dumps(ev["arguments"], ensure_ascii=False), language="json")
    with st.form("hakim_form", clear_on_submit=True, border=False):
        q = st.text_area("Votre question", placeholder="Ex. Comment ajouter Margot à une équipe ?", height=80,
                         label_visibility="collapsed")
        c1, c2 = st.columns([1, 1])
        sent = c1.form_submit_button("Envoyer", type="primary", use_container_width=True)
        reset = c2.form_submit_button("Nouvelle conversation", use_container_width=True)
    if reset:
        st.session_state.pop("hakim", None)
        st.rerun(scope="fragment")
    if sent and q.strip():
        st.session_state["hakim_pending"] = q.strip()[:2000]
        st.rerun(scope="fragment")


def render(page_title: str) -> None:
    """Bulle flottante ; le panneau s'ouvre au clic et garde la conversation entre les pages."""
    if not hakim.enabled():
        return
    st.markdown(CSS, unsafe_allow_html=True)
    with st.container(key="hakim_fab"):
        clicked = st.button(f"{hakim.NAME}", icon=":material/assistant:", key="hakim_open",
                            help="L'architecte de la plateforme : posez une question sur DISCOVERY")
    if clicked:
        _panel(page_context(page_title))
