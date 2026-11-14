import streamlit as st

from ui import state
from ui.chat_panel import render_chat

st.title("Chat & Test")
user = state.current_user()
try:
    agents = [a for a in state.agents() if a["status"] == "publie" or a["owner"] == user.email]
except Exception as e:  # noqa: BLE001
    st.error(f"Lecture des agents impossible : {e}")
    st.stop()
if not agents:
    st.info("Aucun agent disponible.")
    st.stop()

ids = [a["agent_id"] for a in agents]
default = st.session_state.get("chat_agent_id")
idx = ids.index(default) if default in ids else 0
names = {a["agent_id"]: f"{a['name']} (v{a['current_version']}, {a['status']})" for a in agents}
agent_id = st.selectbox("Agent", ids, index=idx, format_func=names.get)
st.session_state["chat_agent_id"] = agent_id

cfg = state.repository().get_config(agent_id)
if cfg is None:
    st.error("Configuration introuvable.")
    st.stop()
with st.expander("Configuration de l'agent"):
    st.markdown(f"**Instructions**\n\n{cfg.instructions}")
    st.write("Tables autorisées :", cfg.knowledge_tables or "toutes celles accessibles à l'utilisateur")
category = next((a.get("category") for a in agents if a["agent_id"] == agent_id), None)
render_chat(cfg, key=f"{agent_id}_v{cfg.version}", category=category)
