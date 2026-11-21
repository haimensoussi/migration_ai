"""HakimAI Voix (prototype) : conversation vocale temps réel, lecture seule, droits de l'utilisateur."""
import os
import uuid

import streamlit as st

from backend import hakim, voice
from backend.tool_registry import ToolContext, ToolRegistry
from tools.hakim_tools import Platform
from ui import state
from ui.voice_call import voice_call

st.title("HakimAI Voix")
st.caption("Prototype : parlez à HakimAI comme au téléphone. En lecture seule (aide sur la plateforme, agents, "
           "activité), avec vos droits. Pour créer ou modifier, utilisez la page HakimAI.")
if not hakim.enabled():
    st.info("HakimAI est désactivé par l'administrateur (AI_STUDIO_HAKIM_ENABLED).")
    st.stop()
ok, why = voice.status()
if not ok:
    st.info(why)
    st.stop()

cfg = voice.settings()
st.warning("Votre voix, sa transcription et les réponses transitent par OpenAI (hors Databricks). "
           "N'énoncez aucune donnée sensible. Session limitée à "
           f"{cfg['max_seconds'] // 60} min et {cfg['max_tool_calls']} appels d'outils.")

v = st.session_state.setdefault("hakim_voice", {"conv": uuid.uuid4().hex, "secret": None, "error": None,
                                                "results": [], "seen": set(), "calls": set(), "history": []})


def tool_runtime():
    w, sql, ident = state.user_session()
    trepo = state.team_repository()
    plat = Platform(state.repository(), trepo, ident.email, trepo.is_admin(ident.email), {"page": "HakimAI Voix"},
                    conv=v["conv"], drafts={}, designer=state.build_designer,
                    tool_designer=state.build_tool_designer, visuals={}, reports={},
                    transformation=state.transformation_service())
    ctx = ToolContext(sql=sql, workspace=w, max_rows=state.settings().max_rows, user_email=ident.email,
                      platform=plat, conversation_id=v["conv"], agent_id=hakim.AGENT_ID)
    return ToolRegistry(voice.voice_specs(hakim.TOOLS)), ctx, ident.email


def on_start(seq: str) -> None:
    """La réponse (clé ou erreur) porte le numéro de la demande : le navigateur ignore les réponses périmées."""
    v.update(conv=uuid.uuid4().hex, secret=None, error=None, results=[], calls=set())
    try:
        body = voice.session_config(voice.voice_specs(hakim.TOOLS), cfg["model"], cfg["voice"])
        minted = voice.mint_client_secret(os.environ.get("OPENAI_API_KEY", ""), body)
        v["secret"] = {"value": minted["value"], "nonce": seq}
    except voice.VoiceError as e:
        v["error"] = {"for": seq, "message": str(e)}


def on_tools(calls: list[dict]) -> None:
    v["secret"] = None   # la clé éphémère a servi : elle n'est plus renvoyée au navigateur
    registry, ctx, user = tool_runtime()
    for c in calls or []:
        cid = str(c.get("call_id") or "")
        if not cid or cid in v["calls"]:
            continue
        v["calls"].add(cid)
        if len(v["calls"]) > cfg["max_tool_calls"]:   # plafond vérifié aussi côté serveur
            v["results"].append({"call_id": cid, "output": '{"erreur": "Limite d\'appels d\'outils atteinte."}'})
            continue
        ev, out = voice.run_tool(registry, ctx, str(c.get("name") or ""), c.get("arguments") or "{}", cid)
        v["results"].append({"call_id": cid, "output": out})
        try:
            state.repository().log_tool_call(v["conv"], hakim.AGENT_ID, user, ev)
        except Exception:  # noqa: BLE001 - le journal ne bloque pas la conversation
            pass
    v["results"] = v["results"][-30:]


def on_end(evt: dict) -> None:
    v["secret"] = None
    v["history"].insert(0, {"conversation": v["conv"][:8], "durée (s)": evt.get("duration_s"),
                            "appels d'outils": len(v["calls"]), "erreur": evt.get("error") or ""})
    v["history"] = v["history"][:10]


event = voice_call(secret=v["secret"], results=v["results"], error=v["error"], max_seconds=cfg["max_seconds"],
                   max_tool_calls=cfg["max_tool_calls"], calls_url=voice.CALLS_URL)
if isinstance(event, dict) and event.get("seq") and event["seq"] not in v["seen"]:
    v["seen"].add(event["seq"])
    kind = event.get("kind")
    if kind == "start":
        on_start(event["seq"])
    elif kind == "tools":
        on_tools(event.get("calls") or [])
    elif kind == "end":
        on_end(event)
    st.rerun()

if v["history"]:
    with st.expander("Sessions de cette visite"):
        st.dataframe(v["history"], hide_index=True, use_container_width=True)
