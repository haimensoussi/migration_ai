"""HakimAI, l'architecte de la plateforme : page dédiée (lecture seule, droits de l'utilisateur)."""
import json
import uuid

import streamlit as st

from backend import hakim, hakim_guard
from backend import hakim_plan as HP
from backend.agent_runtime import AgentRuntime
from backend.model_client import ModelClient
from backend.tool_registry import ToolContext, ToolRegistry
from tools.hakim_tools import Platform
from tools.hakim_write_tools import audit
from ui import state

WRITE_TOOLS = {t.tool_id for t in hakim.TOOLS if t.requires_confirmation}

EXAMPLES = ["Guide-moi pour transformer mon activité avec l'IA, étape par étape",
            "Montre la fréquentation 2025 par Direction Régionale Gares et fais-en un rapport",
            "Crée-moi un agent qui résume les anomalies qualité par dimension",
            "Crée un outil qui compte les gares par région", "Quels agents sont disponibles ?",
            ]

st.title(f"{hakim.NAME}")
st.caption(f"{hakim.PERSONA.capitalize()} : je vous guide dans DISCOVERY et je peux concevoir et créer pour vous des "
           "agents, des outils et des équipes, toujours en brouillon et après votre validation. Je ne publie jamais. "
           "J'agis avec vos droits.")
if not hakim.enabled():
    st.info("HakimAI est désactivé par l'administrateur (AI_STUDIO_HAKIM_ENABLED).")
    st.stop()

s = st.session_state.setdefault("hakim", {"conv": uuid.uuid4().hex, "history": [], "display": [], "turns": 0,
                                          "logged": 0, "drafts": {}, "pending": None})
s.setdefault("drafts", {})
s.setdefault("visuals", {})
s.setdefault("reports", {})
s.setdefault("pending", None)
s.setdefault("work_plan", {})   # plan de travail en cours (étapes annoncées), propre à la conversation


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
        if st.session_state.get("transfo_plan"):
            ctx["plan_transformation"] = st.session_state["transfo_plan"]
    except Exception:  # noqa: BLE001
        pass
    return ctx


def runtime():
    w, sql, ident = state.user_session()
    cfg_s = state.settings()
    trepo = state.team_repository()
    plat = Platform(state.repository(), trepo, ident.email, trepo.is_admin(ident.email), page_context(),
                    conv=s["conv"], drafts=s["drafts"], designer=state.build_designer,
                    tool_designer=state.build_tool_designer, visuals=s["visuals"], reports=s["reports"],
                    transformation=state.transformation_service(), work_plan=s["work_plan"], plan_required=True)
    ctx = ToolContext(sql=sql, workspace=w, max_rows=cfg_s.max_rows, user_email=ident.email, platform=plat)
    guard = lambda tid, args, msgs: hakim_guard.presentation_issue(tid, args, msgs, s["drafts"])  # noqa: E731
    return (AgentRuntime(ModelClient(w), ToolRegistry(hakim.TOOLS), ctx, before_confirm=guard),
            hakim.config(cfg_s.default_model), plat)


def handle(res, logged_prefix: list[dict], warnings: list[dict] | None = None) -> None:
    """Met à jour l'historique, l'affichage, la fiche en attente et le journal."""
    s["history"] = [m for m in res.messages if m["role"] != "system"]
    s["pending"] = {"pending": res.pending, "messages": res.messages} if res.pending else None
    events = [{"outil": e.tool_id, "statut": e.status, "arguments": e.arguments, "erreur": e.error}
              for e in res.events]
    text = "\n\n".join(m["content"] for m in res.new_messages if m.get("role") == "assistant" and m.get("content"))
    # Étapes du plan : affichées si le plan est annoncé dans ce tour ou s'il restait des étapes à faire ;
    # leur état vient des outils réellement appelés (jamais du modèle).
    open_before = any(x["etat"] != "fait" for x in HP.lines(s["work_plan"]))
    HP.record(s["work_plan"], [(e.tool_id, e.status) for e in res.events])
    announced = any(e.tool_id == HP.PLAN_TOOL and e.status == "succes" for e in res.events)
    steps = HP.lines(s["work_plan"]) if (announced or (open_before and events)) else []
    if text or events:
        ok = [e.result for e in res.events if e.status == "succes" and isinstance(e.result, dict)]
        s["display"].append({"role": "assistant", "content": text, "events": events, "steps": steps,
                             "nav": hakim.navigation_targets(res.events),
                             "warning": hakim_guard.warning_text(warnings) if warnings else None,
                             "visuals": [r["visuel_id"] for r in ok if r.get("visuel_id")],
                             "reports": [r["rapport_id"] for r in ok if r.get("rapport_id")],
                             "excels": [r["_ui_excel"] for r in ok if r.get("_ui_excel")]})
    if any(e.tool_id in WRITE_TOOLS and e.status == "succes" for e in res.events):
        state.refresh_data()
    try:   # journal : conversation et appels d'outils sous l'agent « hakimai »
        repo, user = state.repository(), state.user_session()[2].email
        for ev in res.events:
            repo.log_tool_call(s["conv"], hakim.AGENT_ID, user, ev)
        s["logged"] = repo.log_messages(s["conv"], hakim.config(state.settings().default_model), user,
                                        logged_prefix + list(res.new_messages), s["logged"], res.latency_ms)
    except Exception:  # noqa: BLE001
        pass


def ask(question: str) -> None:
    rt, cfg, _ = runtime()
    user_msg = {"role": "user", "content": question}
    s["display"].append({"role": "user", "content": question})
    s["turns"] += 1
    try:
        with st.spinner("HakimAI réfléchit…"):
            res, warnings = hakim_guard.verify_turn(rt, cfg, rt.run(cfg, s["history"] + [user_msg]))
    except Exception as e:  # noqa: BLE001
        s["display"].append({"role": "assistant", "content": f"Je n'ai pas pu répondre : {e}"})
        return
    handle(res, [user_msg], warnings)


def decide(approved: bool) -> None:
    pend = s["pending"]
    rt, cfg, plat = runtime()
    call = pend["pending"]
    if not approved:
        try:
            audit(plat, call["tool"], "", None, call.get("arguments") or {}, None, None, "refuse")
        except Exception:  # noqa: BLE001
            pass
        # Réponse écrite par l'application : le modèle n'est pas rappelé après un refus.
        lines = hakim.describe_action(call["tool"], call.get("arguments") or {}, s["drafts"])
        handle(hakim_guard.refusal_result(pend["messages"], call["call"]["id"], lines[0] if lines else None), [])
        return
    try:
        with st.spinner("Exécution…"):
            res, warnings = hakim_guard.verify_turn(rt, cfg, rt.resume(cfg, pend["messages"], {call["call"]["id"]: True}))
    except Exception as e:  # noqa: BLE001
        s["pending"] = None
        s["display"].append({"role": "assistant", "content": f"Erreur pendant l'exécution : {e}"})
        return
    handle(res, [], warnings)


def show_visual(v, key: str) -> None:
    if not v:
        return
    if v["type"] == "carte":
        from ui import map_view
        st.caption(v["titre"])
        map_view.render({"result": v["carte"], "arguments": {"query": v["requete"]}}, key=key)
        with st.expander(f"{v['id']} · requête ({v['carte'].get('nombre_points')} points)"):
            st.code(v["requete"], language="sql")
    else:
        from ui import chart_view
        chart_view.render(v, key=key)


def show_report(r, key: str) -> None:
    if not r:
        return
    st.markdown(f"**Rapport : {r['titre']}**")
    c1, c2 = st.columns(2)
    name = "".join(ch if ch.isalnum() else "_" for ch in r["titre"])[:60] or "rapport"
    c1.download_button("Télécharger en HTML", r["html"], file_name=f"{name}.html", mime="text/html", key=f"h_{key}",
                       use_container_width=True)
    c2.download_button("Télécharger en Markdown", r["markdown"], file_name=f"{name}.md", mime="text/markdown",
                       key=f"m_{key}", use_container_width=True)
    with st.expander("Aperçu du rapport"):
        st.markdown(r["markdown"])


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
        for x in m.get("steps") or []:   # « Étape N — Titre », une ligne chacune, avec son état
            st.markdown(f"{x['libelle']}  ·  *{HP.STATES.get(x['etat'], x['etat'])}*")
        st.markdown(m["content"])
        if m.get("warning"):
            st.warning(m["warning"])
        for vid in m.get("visuals") or []:
            show_visual(s["visuals"].get(vid), key=f"{s['conv']}_{vid}")
        for rid in m.get("reports") or []:
            show_report(s["reports"].get(rid), key=f"{s['conv']}_{rid}")
        for i, x in enumerate(m.get("excels") or []):
            from ui import report_view
            report_view.render_excel(x, key=f"{s['conv']}_{id(m)}_{i}")
        for nav in m.get("nav") or []:
            st.page_link(nav["path"], label=f"Ouvrir {nav['title']}")
        if m.get("events"):
            with st.expander(f"{len(m['events'])} outil(s) consulté(s)"):
                for ev in m["events"]:
                    st.markdown(f"`{ev['outil']}` · {ev['statut']}" + (f" — {ev['erreur']}" if ev.get("erreur") else ""))
                    if ev.get("arguments"):
                        st.code(json.dumps(ev["arguments"], ensure_ascii=False), language="json")

if s["pending"]:
    call = s["pending"]["pending"]
    with st.container(border=True):
        st.markdown(f"**Validation requise : {next((t.name for t in hakim.TOOLS if t.tool_id == call['tool']), call['tool'])}**")
        for line in hakim.describe_action(call["tool"], call.get("arguments") or {}, s["drafts"]):
            st.markdown(f"* {line}")
        with st.expander("Paramètres exacts"):
            st.code(json.dumps(call.get("arguments") or {}, ensure_ascii=False, indent=2), language="json")
        c1, c2 = st.columns(2)
        ok = c1.button("Valider", type="primary", use_container_width=True, key="hakim_ok")
        no = c2.button("Refuser", use_container_width=True, key="hakim_no")
        if ok or no:
            decide(bool(ok))
            st.rerun()

try:
    _trepo = state.team_repository()
    _me = state.user_session()[2].email
    if _trepo.is_admin(_me):
        _r = state.repository().sql.query(
            f"SELECT action_id, user_name, object_type, object_id, arguments, before_state, created_at "
            f"FROM {state.settings().table('copilot_actions')} WHERE tool_id = 'demande_publication' "
            "AND status = 'en_attente' ORDER BY created_at DESC LIMIT 20")["rows"]
        if _r:
            with st.expander(f"Demandes de publication en attente ({len(_r)})"):
                for x in _r:
                    info = json.loads(x["before_state"] or "{}")
                    msg = json.loads(x["arguments"] or "{}").get("message") or ""
                    a1, a2 = st.columns([5, 1])
                    a1.markdown(f"{x['object_type']} « {info.get('nom', x['object_id'])} » · {x['user_name']} · "
                                f"{str(x['created_at'])[:16]}" + (f" — {msg}" if msg else ""))
                    if a2.button("Traitée", key=f"hakim_req_{x['action_id']}"):
                        state.repository().sql.execute(
                            f"UPDATE {state.settings().table('copilot_actions')} SET status = 'traitee' "
                            "WHERE action_id = :id AND status = 'en_attente'", {"id": x["action_id"]})
                        st.rerun()
except Exception:  # noqa: BLE001
    pass

typed = None if s["pending"] else st.chat_input("Posez votre question à HakimAI")
question = (typed or question or "").strip()[:2000]
if question and not s["pending"]:
    if s["turns"] >= hakim.max_turns():
        st.warning("Limite de questions atteinte pour cette conversation : cliquez sur « Nouvelle conversation ».")
    else:
        ask(question)
        st.rerun()
