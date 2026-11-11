"""Interface conversationnelle de l'agent llm_call migré depuis HORIZON (Databricks App, Streamlit).
L'App n'appelle que l'endpoint Model Serving de l'agent ; elle ne contacte aucun LLM directement."""
import os

import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from agent_client import MODELS, AgentCallError, build_request, call_agent

ENDPOINT = os.getenv("LLM_CALL_ENDPOINT", "agents_dataops_dev-knowledge-horizon_llm_call_agent")

st.set_page_config(page_title="Assistant llm_call", page_icon="💬", layout="wide")
ss = st.session_state
ss.setdefault("history", [])   # [{'role', 'content', 'outputs'?, 'error'?}]
ss.setdefault("totals", {"calls": 0, "tokens": 0, "micro_eur": 0.0, "usd": 0.0})


@st.cache_resource
def client() -> WorkspaceClient:
    # Marge pour le réveil de l'endpoint (scale-to-zero)
    return WorkspaceClient(config=Config(http_timeout_seconds=300, retry_timeout_seconds=300))


def metrics_line(o: dict) -> str:
    f = o.get("finops") or {}
    parts = [f"Modèle : `{o.get('model_used', '?')}`",
             f"Tokens : {o.get('prompt_tokens', '?')} + {o.get('completion_tokens', '?')} = {o.get('tokens_used', '?')}",
             f"Temps : {o.get('processing_time_ms', 0):.0f} ms"]
    if f:
        parts.append(f"Coût : {f.get('total_cost_micro_eur', 0):.2f} µ€ ({f.get('total_cost_usd', 0):.6f} USD)")
    return " · ".join(parts)


# ---------------------------------------------------------------- paramètres
with st.sidebar:
    st.title("💬 Assistant llm_call")
    st.caption(f"Agent migré depuis HORIZON — endpoint `{ENDPOINT}`")
    model = st.selectbox("Modèle", MODELS, index=0)
    use_temp = st.checkbox("Fixer la température", value=False, help="Sinon, valeur par défaut du modèle.")
    temperature = st.slider("Température", 0.0, 1.0, 0.7, 0.05, disabled=not use_temp)
    use_max = st.checkbox("Limiter la longueur de réponse", value=True)
    max_tokens = st.number_input("max_tokens", min_value=1, max_value=8192, value=1024, step=64, disabled=not use_max)
    system = st.text_area("Consigne système (facultative)", height=100,
                          placeholder="Ex. : Tu es un assistant SNCF Réseau. Réponds en français, de façon concise.")
    st.divider()
    t = ss.totals
    c1, c2 = st.columns(2)
    c1.metric("Appels", t["calls"])
    c2.metric("Tokens", t["tokens"])
    st.metric("Coût de la session", f"{t['micro_eur']:.2f} µ€", help=f"{t['usd']:.6f} USD — grille FinOps de l'Action HORIZON")
    if st.button("Nouvelle conversation", use_container_width=True):
        ss.history = []
        ss.totals = {"calls": 0, "tokens": 0, "micro_eur": 0.0, "usd": 0.0}
        st.rerun()

# ---------------------------------------------------------------- conversation
st.title("Assistant llm_call")
st.caption("Les coûts sont calculés par l'agent avec la grille FinOps de l'Action HORIZON d'origine. "
           "L'estimation environnementale (Ecologits) est désactivée : service injoignable depuis Databricks.")

for m in ss.history:
    with st.chat_message(m["role"]):
        if m.get("error"):
            st.error(f"**{m['error']['code']}** — {m['error']['message']}")
        else:
            st.markdown(m["content"])
        if m.get("outputs"):
            st.caption(metrics_line(m["outputs"]))
            with st.expander("Sorties de l'agent (custom_outputs)"):
                st.json(m["outputs"])

prompt = st.chat_input("Votre message")
if prompt:
    ss.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    # Seuls les échanges réussis sont renvoyés à l'agent (les messages d'erreur ne font pas partie du dialogue)
    dialogue, pending_user = [], None
    for m in ss.history:
        if m["role"] == "user":
            pending_user = m
        elif not m.get("error") and pending_user is not None:
            dialogue += [pending_user, m]
            pending_user = None
    dialogue.append(ss.history[-1])
    req = build_request(dialogue, system, model, float(temperature) if use_temp else None,
                        int(max_tokens) if use_max else None)
    with st.chat_message("assistant"):
        with st.spinner("L'agent répond… (le premier appel peut prendre plus longtemps si l'endpoint se réveille)"):
            try:
                r = call_agent(client(), ENDPOINT, req)
                msg = {"role": "assistant", "content": r["content"], "outputs": r["outputs"]}
                o, f = r["outputs"], r["outputs"].get("finops") or {}
                ss.totals["calls"] += 1
                ss.totals["tokens"] += int(o.get("tokens_used") or 0)
                ss.totals["micro_eur"] += float(f.get("total_cost_micro_eur") or 0)
                ss.totals["usd"] += float(f.get("total_cost_usd") or 0)
            except AgentCallError as e:
                msg = {"role": "assistant", "content": "", "error": {"code": e.code, "message": e.message}}
    ss.history.append(msg)
    st.rerun()
