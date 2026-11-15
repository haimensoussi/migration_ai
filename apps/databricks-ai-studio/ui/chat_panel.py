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


def _show_delegation(ev: dict):
    args = ev.get("arguments") or {}
    res = ev.get("result") if isinstance(ev.get("result"), dict) else {}
    st_txt = "validation requise" if res.get("statut") == "validation_requise" else STATUS_TXT.get(ev["status"], ev["status"])
    n = f" n° {res['echange']}" if res.get("echange") else ""
    who = res.get("agent_affiche") or _DISPLAY.get(args.get("agent", ""), args.get("agent", "?"))
    with st.expander(f"Question posée à {who}{n} : {st_txt} ({ev['duration_ms']} ms)"):
        st.caption("Question transmise")
        st.markdown(str(args.get("question", "")))
        if ev["status"] == "succes":
            st.caption(f"Réponse de {who.split(',')[0]} ({AI_BADGE})")
            st.markdown(res.get("reponse") or res.get("message") or "(vide)")
            if res.get("outils"):
                st.caption("Outils appelés : " + ", ".join(f"{o['outil']} ({STATUS_TXT.get(o['statut'], o['statut'])})"
                                                        for o in res["outils"]))
        else:
            st.error(ev["error"])
    # Cartes produites par l'agent consulté : affichées hors du panneau, comme celles de l'agent principal
    maps = res.get("_ui_maps") or []
    if maps:
        from ui import map_view
        for i, m in enumerate(maps):
            st.caption(f"Carte produite par {who}")
            map_view.render({"result": m, "arguments": {"query": m.get("_ui_query", "")}}, key=f"{id(ev)}_{i}")


def _show_event(ev: dict):
    if ev["tool_id"] == "ask_agent":
        return _show_delegation(ev)
    if ev["tool_id"] == "render_map" and ev["status"] == "succes":
        from ui import map_view
        return map_view.render(ev)
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


from backend.personas import AI_BADGE  # noqa: E402

_DISPLAY: dict[str, str] = {}   # nom de l'agent -> « Prénom, rôle » (alimenté à chaque affichage du chat)


def _shown(name: str) -> str:
    return f"{_DISPLAY.get(name, name)} · {AI_BADGE}" if name else name


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
        head = f'<div class="dsc-agent">{html.escape(_shown(agent_name))}</div>' if agent_name else ""
        st.markdown(head + chips_html([tuple(c) for c in (chips or [])]), unsafe_allow_html=True)
        st.markdown(content)


def _welcome(cfg: AgentConfig):
    caps = capabilities_for(cfg.tool_ids)
    with st.chat_message("assistant", avatar=AV["assistant"]):
        body = (f'<div class="dsc-agent">{html.escape(_shown(cfg.name or "Agent"))}</div>'
                "<p>Bonjour ! Je peux vous accompagner dans l'exploration et l'analyse de vos données Databricks.</p>")
        if caps:
            body += '<div class="dsc-cap-title">Mes capacités</div>' + "".join(
                f'<div class="dsc-cap">{icon_img(i)}<span>{html.escape(t)}</span></div>' for i, t in caps)
        body += '<div class="dsc-cap-title">Par quoi souhaitez-vous commencer ?</div>'
        st.markdown(body, unsafe_allow_html=True)


def render_chat(cfg: AgentConfig, key: str, persist: bool = True, category: str | None = None):
    _inject_css()
    # La consigne de présentation est ajoutée à l'exécution (runtime_for), jamais enregistrée
    sk = f"chat_{key}"
    if sk not in st.session_state:
        st.session_state[sk] = {"conversation_id": uuid.uuid4().hex, "history": [], "display": [],
                                "pending": None, "next_index": 0}
    s = st.session_state[sk]
    user = state.current_user()

    top = st.columns([4, 1])
    from backend.orchestrator import plain_tools, sub_agent_ids
    deleg = f" · agents partenaires : {len(sub_agent_ids(cfg.tool_ids))}" if sub_agent_ids(cfg.tool_ids) else ""
    top[0].caption(f"Modèle `{cfg.model_endpoint}` · outils : {', '.join(plain_tools(cfg.tool_ids)) or 'aucun'}{deleg} · "
                   f"identité : {user.email} ({user.mode})")
    if top[1].button("Nouvelle conversation", key=f"reset_{key}"):
        del st.session_state[sk]
        st.rerun()

    for wmsg in s.get("orch_warnings") or []:
        st.caption(f"Orchestration : {wmsg}")
    if not s["display"]:
        _welcome(cfg)
    for item in s["display"]:
        if item["kind"] == "notice":
            st.caption(item["content"])
        elif item["kind"] == "event":
            with st.chat_message("assistant", avatar=AV["tool"]):
                st.markdown('<span class="dsc-msg-tool"></span>', unsafe_allow_html=True)
                _show_event(item["event"])
        else:
            render_discovery_message(item["role"], item["content"], item.get("agent", ""), item.get("chips"))

    repo = state.repository()
    from backend import personas
    everyone = state.mentionable_agents() or []
    _DISPLAY.update({a["name"]: personas.display(a) for a in everyone if a.get("name") and a.get("kind") != "team"})
    mentionables = [a for a in everyone if a.get("agent_id") != cfg.agent_id]
    me_row = next((a for a in everyone if a.get("agent_id") == cfg.agent_id and a.get("kind") != "team"), {})

    def make_logger(agent_id: str):
        def _log(ev: ToolEvent):
            if persist:
                try:
                    repo.log_tool_call(s["conversation_id"], agent_id, user.email, ev)
                except Exception:  # noqa: BLE001 - la journalisation ne bloque pas la conversation
                    pass
        return _log

    def log_sub(agent_id: str, ev: ToolEvent):
        make_logger(agent_id)(ev)

    def runtime_for(speaker: AgentConfig):
        presented = dataclasses.replace(speaker, instructions=with_presentation(speaker.instructions))
        rt_, exec_cfg, warns = state.build_runtime_for(presented, on_tool_event=make_logger(speaker.agent_id),
                                                       conversation_id=s["conversation_id"], on_sub_event=log_sub)
        s["orch_warnings"] = warns
        return rt_, exec_cfg

    def log_msgs(speaker: AgentConfig, msgs: list[dict], latency):
        if not persist:
            return
        try:
            s["next_index"] = repo.log_messages(s["conversation_id"], speaker, user.email, msgs, s["next_index"], latency)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Historique non enregistré : {e}")

    def handle(res: TurnResult, log_user: dict | None, speaker: AgentConfig, cat: str | None, main: bool):
        """Affiche et journalise un tour ; met à jour l'historique de l'agent principal."""
        turn_events = [_ev_dict(ev) for ev in res.events]
        for ev in turn_events:
            s["display"].append({"kind": "event", "event": ev})
        if res.pending:
            s["pending"] = {"pending": res.pending, "messages": res.messages, "speaker": speaker,
                            "category": cat, "main": main}
        else:
            s["pending"] = None
            text = res.final_text or "(réponse vide)"
            if main:
                s["history"] = [m for m in res.messages if m["role"] != "system"]
            else:   # réponse d'un agent mentionné : conservée comme contexte pour l'agent principal
                block = f"[Réponse de {speaker.name}]\n{text}"
                last = s["history"][-1] if s["history"] else None
                if last and last["role"] == "assistant" and str(last.get("content", "")).startswith("[Réponse de "):
                    last["content"] += "\n\n" + block     # un seul message assistant : alternance préservée
                else:
                    s["history"].append({"role": "assistant", "content": block})
            s["display"].append({"kind": "msg", "role": "assistant", "content": text, "agent": speaker.name,
                                 "chips": chips_for(turn_events, cat)})
        log_msgs(speaker, ([log_user] if log_user else []) + [m for m in res.new_messages if m["role"] != "system"],
                 res.latency_ms)
        return res

    def fail(speaker_name: str, cat, e: Exception):
        label = "Accès refusé" if isinstance(e, state.UserAuthMissing) else "Erreur d'exécution"
        s["display"].append({"kind": "msg", "role": "assistant", "content": f"**{label}** : {e}",
                             "agent": speaker_name, "chips": chips_for([], cat, error=True)})

    def recent_context(limit: int = 6) -> str:
        msgs = [d for d in s["display"] if d["kind"] == "msg"][:-1][-limit:]
        return "\n".join(f"- {'Utilisateur' if d['role'] == 'user' else d.get('agent') or 'Agent'} : "
                         f"{str(d['content'])[:1500]}" for d in msgs)

    def run_mentions(prompt: str, found) -> None:
        """L'agent mentionné répond lui-même ; s'il y en a plusieurs, l'agent principal fait la synthèse."""
        question = found.text or prompt
        s["history"].append({"role": "user", "content": prompt})
        first = True
        answered = 0
        for a in found.agents:
            mcfg = repo.get_config(a["agent_id"])
            if mcfg is None:
                s["display"].append({"kind": "notice", "content": f"Configuration de « {a['name']} » introuvable."})
                continue
            ctx_txt = recent_context()
            content = (f"Contexte récent de la discussion (pour information) :\n{ctx_txt}\n\n" if ctx_txt else "") + \
                f"Question qui t'est adressée par l'utilisateur :\n{question}"
            try:
                rt, exec_cfg = runtime_for(mcfg)
                res = rt.run(exec_cfg, [{"role": "user", "content": content}])
                handle(res, {"role": "user", "content": prompt} if first else None, mcfg, a.get("category"), main=False)
                first = False
                answered += 1
                if res.pending:
                    s["display"].append({"kind": "notice", "content": "Validation requise : les agents suivants "
                                         "répondront après votre décision s'ils sont mentionnés de nouveau."})
                    return
            except Exception as e:  # noqa: BLE001
                fail(a["name"], a.get("category"), e)
        if answered >= 2:
            try:
                rt, exec_cfg = runtime_for(cfg)
                synth = {"role": "user", "content": "Fais une synthèse courte des réponses des agents mentionnés "
                                                    "ci-dessus, en citant chaque agent. N'ajoute aucun résultat."}
                handle(rt.run(exec_cfg, s["history"] + [synth]), None, cfg, category, main=True)
            except Exception as e:  # noqa: BLE001
                fail(cfg.name, category, e)

    if s["pending"]:
        p = s["pending"]["pending"]
        speaker = s["pending"].get("speaker") or cfg
        with st.container(border=True):
            st.warning(f"Validation requise : l'agent « {speaker.name} » veut exécuter `{p['tool']}`.")
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
                        pend = s["pending"]
                        rt, exec_cfg = runtime_for(speaker)
                        res = rt.resume(exec_cfg, pend["messages"], {p["call"]["id"]: decision})
                        handle(res, None, speaker, pend.get("category", category), main=pend.get("main", True))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Erreur d'exécution : {e}")
                st.rerun()

    # Boutons de mention : le prochain message est adressé à l'agent choisi
    if mentionables and not s["pending"]:
        st.caption("Adresser le prochain message à un agent (ou tapez @ dans votre message) :")
        cols = st.columns(min(len(mentionables), 5))
        for i, a in enumerate(mentionables[:5]):
            if cols[i].button(f"@{personas.mention(a)}", key=f"mention_{key}_{a['agent_id']}", use_container_width=True,
                              help=" — ".join(x for x in (personas.display(a), a.get("tagline")) if x)):
                s["mention_prefix"] = personas.mention(a)
                st.rerun()
        if s.get("mention_prefix"):
            c_a, c_b = st.columns([4, 1])
            c_a.caption(f"Prochain message adressé à @{s['mention_prefix']}")
            if c_b.button("Annuler", key=f"mention_cancel_{key}"):
                s.pop("mention_prefix", None)
                st.rerun()

    placeholder = "Écrivez votre message... (@ pour interroger un autre agent)"
    if mentionables:
        try:   # liste @ et Tab ajoutées à la saisie standard ; en cas d'échec, la saisie reste utilisable
            from ui import mention_input as mention_ui
            if mention_ui.enabled():
                mention_ui.inject(mentionables)
        except Exception:  # noqa: BLE001
            pass
    prompt = st.chat_input(placeholder, key=f"input_{key}", disabled=bool(s["pending"]))
    if prompt:
        prefix = s.pop("mention_prefix", None)
        if prefix and "@" not in prompt:
            prompt = f"@{prefix} {prompt}"
        from backend.mentions import parse_mentions
        me_agent = {"agent_id": cfg.agent_id, "name": cfg.name, "handle": me_row.get("handle"),
                    "aliases": me_row.get("aliases") or []}
        found = parse_mentions(prompt, mentionables + [me_agent]) if "@" in prompt else None
        if found:
            found.agents = [a for a in found.agents if a["agent_id"] != cfg.agent_id]   # @agent courant : flux normal
        s["display"].append({"kind": "msg", "role": "user", "content": prompt})
        if found:
            for tok, sugg in found.unknown:
                s["display"].append({"kind": "notice", "content": f"Agent « @{tok} » inconnu ou non accessible"
                                     + (f" ; vouliez-vous dire : {', '.join(sugg)} ?" if sugg else ".")})
            if found.truncated:
                s["display"].append({"kind": "notice", "content": "Au plus 3 agents mentionnés par message : "
                                     "les suivants sont ignorés."})
        with st.spinner("L'agent réfléchit..."):
            if found and found.agents:
                run_mentions(prompt, found)
            else:
                user_msg = {"role": "user", "content": prompt}
                try:
                    rt, exec_cfg = runtime_for(cfg)
                    handle(rt.run(exec_cfg, s["history"] + [user_msg]), user_msg, cfg, category, main=True)
                except Exception as e:  # noqa: BLE001
                    fail(cfg.name, category, e)
        st.rerun()
