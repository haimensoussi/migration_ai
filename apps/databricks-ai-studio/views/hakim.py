"""HakimAI, l'architecte de la plateforme : page dédiée (lecture seule, droits de l'utilisateur)."""
import json
import uuid

import streamlit as st

from backend import hakim
from backend.agent_runtime import AgentRuntime
from backend.model_client import ModelClient
from backend.tool_registry import ToolContext, ToolRegistry
from tools.hakim_tools import Platform
from ui import state

EXAMPLES = ["Comment créer une équipe d'agents ?", "Quels agents sont disponibles ?",
            "Pourquoi des appels d'outils échouent ce mois-ci ?", "Fais-moi une visite guidée"]

st.title(f"{hakim.NAME}")
st.caption(f"{hakim.PERSONA.capitalize()} : je vous guide dans DISCOVERY (agents, outils, équipes, chat, monitoring). "
           "Dans cette version, je lis et j'explique ; je ne crée ni ne modifie rien. J'agis avec vos droits.")
if not hakim.enabled():
    st.info("HakimAI est désactivé par l'administrateur (AI_STUDIO_HAKIM_ENABLED).")
    st.stop()

s = st.session_state.setdefault("hakim", {"conv": uuid.uuid4().hex, "history": [], "display": [], "turns": 0,
                                          "logged": 0})


def page_context() -> dict:
    """Objets sélectionnés ailleurs dans l'application (agent du chat, équipe), en lecture seule."""
    ctx = {"page": "HakimAI"}
    try:
        names = {a["agent_id"]: a["name"] for a in state.agents()}
        if st.session_state.get("chat_agent_id"):
            ctx["agent_du_chat"] = names.get(st.session_state["chat_agent_id"])
        sel = st.session_state.get("mine_sel")
        if sel:
            ctx["equipe_selectionnee"] = next((t["name"] for t in state.teams() if t["team_id"] == sel), None)
    except Exception:  # noqa: BLE001
        pass
    return ctx


def ask(question: str) -> None:
    w, sql, ident = state.user_session()
    cfg_s = state.settings()
    trepo = state.team_repository()
    ctx = ToolContext(sql=sql, workspace=w, max_rows=cfg_s.max_rows, user_email=ident.email,
                      platform=Platform(state.repository(), trepo, ident.email, trepo.is_admin(ident.email), page_context()))
    rt, cfg = AgentRuntime(ModelClient(w), ToolRegistry(hakim.TOOLS), ctx), hakim.config(cfg_s.default_model)
    user_msg = {"role": "user", "content": question}
    s["display"].append({"role": "user", "content": question})
    try:
        with st.spinner("HakimAI réfléchit…"):
            res = rt.run(cfg, s["history"] + [user_msg])
    except Exception as e:  # noqa: BLE001
        s["display"].append({"role": "assistant", "content": f"Je n'ai pas pu répondre : {e}"})
        return
    s["history"] = [m for m in res.messages if m["role"] != "system"]
    s["turns"] += 1
    s["display"].append({"role": "assistant", "content": res.final_text or "(réponse vide)",
                         "events": [{"outil": e.tool_id, "statut": e.status, "arguments": e.arguments,
                                     "erreur": e.error} for e in res.events],
                         "nav": hakim.navigation_targets(res.events)})
    try:   # journal : conversation et appels d'outils sous l'agent « hakimai »
        repo = state.repository()
        for ev in res.events:
            repo.log_tool_call(s["conv"], hakim.AGENT_ID, ident.email, ev)
        s["logged"] = repo.log_messages(s["conv"], cfg, ident.email, [user_msg] + list(res.new_messages),
                                        s["logged"], res.latency_ms)
    except Exception:  # noqa: BLE001
        pass


top = st.columns([4, 1])
if top[1].button("Nouvelle conversation", use_container_width=True):
    st.session_state.pop("hakim", None)
    st.rerun()

question = None
if not s["display"]:
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 2].button(ex, key=f"hakim_ex_{i}", use_container_width=True):
            question = ex

for m in s["display"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        for nav in m.get("nav") or []:
            st.page_link(nav["path"], label=f"Ouvrir {nav['title']}")
        if m.get("events"):
            with st.expander(f"{len(m['events'])} outil(s) consulté(s)"):
                for ev in m["events"]:
                    st.markdown(f"`{ev['outil']}` · {ev['statut']}" + (f" — {ev['erreur']}" if ev.get("erreur") else ""))
                    if ev.get("arguments"):
                        st.code(json.dumps(ev["arguments"], ensure_ascii=False), language="json")

typed = st.chat_input("Posez votre question à HakimAI")
question = (typed or question or "").strip()[:2000]
if question:
    if s["turns"] >= hakim.max_turns():
        st.warning("Limite de questions atteinte pour cette conversation : cliquez sur « Nouvelle conversation ».")
    else:
        ask(question)
        st.rerun()
