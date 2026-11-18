"""Agent Studio SaaS : créer, versionner, publier et tester les agents de l'organisation courante (Streamlit 1.38).

Toutes les règles (prérequis, modèles, actions, tables, droits) sont appliquées par backend.saas.agent_studio.
"""
import streamlit as st

from backend.model_client import ModelClient
from backend.saas.agent_studio import SAAS_DATA_TOOLS, AgentStudio
from backend.saas.models import SaasError
from backend.tool_registry import ToolContext
from ui import state
from ui.components import error_box
from ui.saas_context import ROLE_LABELS, current_context, identity_or_stop

S = st.session_state
identity = identity_or_stop()
svc = state.tenant_service()
studio = AgentStudio(svc, state.cached_tools)
STATUS = {"brouillon": "Brouillon", "publie": "Publié", "archive": "Archivé"}

st.title("Agent Studio")
try:
    ctx, _ = current_context(identity)
except Exception as e:  # noqa: BLE001
    error_box("Lecture des organisations impossible", e)
    st.stop()
if not ctx:
    st.info("Aucune organisation active.")
    st.stop()
try:
    steps = studio.org_setup(ctx)
    agents = studio.list_agents(ctx)
except SaasError as e:
    st.warning(str(e))
    st.stop()
except Exception as e:  # noqa: BLE001
    error_box("Agent Studio indisponible", e)
    st.stop()

can_manage = ctx.can("agents.manage")
if msg := S.pop("as_flash", None):
    st.success(msg)


def act(label, fn, success=None):
    try:
        out = fn()
        if success:
            S["as_flash"] = success
            st.rerun()
        return out
    except SaasError as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        error_box(label, e)
    return None


# -- Choix de l'agent ----------------------------------------------------------------------------------
NEW = "__nouveau__"
choices = ([NEW] if can_manage else []) + [a["agent_id"] for a in agents]
if not choices:
    st.info("Aucun agent publié accessible avec votre rôle.")
    st.stop()
by_id = {a["agent_id"]: a for a in agents}
if "as_agent_next" in S:   # agent créé au tour précédent : sélectionné avant la création du widget
    S["as_agent"] = S.pop("as_agent_next")
if S.get("as_agent") not in choices:
    S["as_agent"] = choices[0] if choices[0] != NEW or len(choices) == 1 else choices[1]


def label(aid):
    if aid == NEW:
        return "+ Nouvel agent"
    a = by_id[aid]
    pub = f"v{a['published']['version']} publiée" if a["published"] else "non publié"
    return f"{a['name']} · {pub}"


aid = st.selectbox("Agent", choices, key="as_agent", format_func=label)
agent = by_id.get(aid)
tab_names = (["Configuration", "Versions"] if can_manage else []) + (["Tester"] if agent else [])
tabs = dict(zip(tab_names, st.tabs(tab_names)))

# -- Configuration -------------------------------------------------------------------------------------
if "Configuration" in tabs:
    with tabs["Configuration"]:
        base = agent["latest"] if agent else None
        cfg = dict(base["config"]) if base else {}
        if base and base["status"] != "brouillon":
            st.info(f"La version {base['version']} est {STATUS[base['status']].lower()} : enregistrer créera la "
                    f"version {base['version'] + 1} en brouillon.")
        ia = steps.get("ia") or {}
        models = ia.get("allowed_endpoints") or []
        catalog = studio.tool_catalog(steps)
        tenant = ctx.tenant
        with st.form(f"as_form_{aid}"):
            c1, c2 = st.columns([2, 1])
            name = c1.text_input("Nom", base["name"] if base else "")
            roles = [r for r, ro in sorted(svc.roles().items(), key=lambda x: x[1].rank)]
            cur_role = cfg.get("min_role", "user")
            min_role = c2.selectbox("Rôle minimal pour l'utiliser", roles, roles.index(cur_role) if cur_role in roles else 0,
                                    format_func=lambda r: ROLE_LABELS.get(r, r))
            description = st.text_input("Description", cfg.get("description", ""))
            instructions = st.text_area("Instructions système", cfg.get("instructions", ""), height=180,
                                        help="20 à 8 000 caractères : rôle, ton, périmètre, règles de réponse.")
            m1, m2, m3 = st.columns(3)
            cur_model = cfg.get("model_endpoint", ia.get("default_endpoint", ""))
            model = m1.selectbox("Modèle (Model Serving)", models, models.index(cur_model) if cur_model in models else 0)
            temperature = m2.slider("Température", 0.0, 1.0, float(cfg.get("temperature", ia.get("temperature", 0.2))), 0.05)
            max_iterations = m3.number_input("Itérations maximum", 1, 10, int(cfg.get("max_iterations", 6)))
            tools = st.multiselect("Actions autorisées", sorted(catalog), [t for t in cfg.get("tool_ids", []) if t in catalog],
                                   format_func=lambda t: f"{catalog[t].name} ({catalog[t].category})",
                                   help="Actions de données (" + ", ".join(SAAS_DATA_TOOLS) + ") : au moins une table "
                                        "de connaissance de l'organisation est requise.")
            tables = st.text_area(f"Tables de connaissance (schéma {tenant.data_schema}, une par ligne)",
                                  "\n".join(cfg.get("knowledge_tables", [])), height=80,
                                  disabled=tenant.data_schema_status != "provisionne",
                                  help=None if tenant.data_schema_status == "provisionne" else
                                  "Schéma non provisionné : demandez-le à l'administrateur de la plateforme.")
            connectors = st.text_input("Connecteurs (identifiants, séparés par des virgules)",
                                       ", ".join(cfg.get("connector_ids", [])),
                                       help="Connecteurs actifs de l'organisation (module Connecteurs, phase suivante).")
            if st.form_submit_button("Enregistrer le brouillon", type="primary"):
                form = {"name": name, "description": description, "instructions": instructions, "model_endpoint": model,
                        "temperature": temperature, "max_iterations": max_iterations, "tool_ids": tools,
                        "knowledge_tables": tables.replace("\n", ","), "connector_ids": connectors, "min_role": min_role}
                out = act("Enregistrement", lambda: studio.save_draft(ctx, agent and aid, form))
                if out:
                    S["as_agent_next"] = out["agent_id"]
                    S["as_flash"] = f"« {out['name']} » enregistré (version {out['version']}, brouillon)."
                    st.rerun()

# -- Versions ------------------------------------------------------------------------------------------
if "Versions" in tabs and agent:
    with tabs["Versions"]:
        vs = act("Versions", lambda: studio.versions(ctx, aid)) or []
        st.dataframe([{"Version": v["version"], "Statut": STATUS[v["status"]], "Nom": v["name"],
                       "Modèle": v["config"].get("model_endpoint"), "Actions": ", ".join(v["config"].get("tool_ids", [])),
                       "Créée par": v["created_by"], "Modifiée le": str(v["updated_at"])[:16]} for v in reversed(vs)],
                     hide_index=True, use_container_width=True)
        drafts = [v["version"] for v in vs if v["status"] != "publie"]
        c1, c2, c3 = st.columns([1, 1, 1])
        if drafts:
            ver = c1.selectbox("Version à publier", list(reversed(drafts)), label_visibility="collapsed")
            if c2.button(f"Publier la version {ver}", type="primary", use_container_width=True):
                act("Publication", lambda: studio.publish(ctx, aid, ver), f"Version {ver} publiée.")
        if agent["published"] and c3.button("Retirer la publication", use_container_width=True):
            act("Retrait", lambda: studio.archive(ctx, aid), "Publication retirée (version archivée).")

# -- Test conversationnel ------------------------------------------------------------------------------
if "Tester" in tabs:
    with tabs["Tester"]:
        versions = ([None] if agent["published"] else []) + ([agent["latest"]["version"]] if can_manage and (
            not agent["published"] or agent["latest"]["version"] != agent["published"]["version"]) else [])
        if not versions:
            st.info("Aucune version utilisable.")
        else:
            ver = st.radio("Version", versions, horizontal=True, key=f"as_ver_{aid}",
                           format_func=lambda v: f"Publiée (v{agent['published']['version']})" if v is None
                           else f"Brouillon v{v} (test)")
            key = f"as_chat_{ctx.tenant_id}_{aid}_{ver}"
            history = S.setdefault(key, [])
            events_log = S.setdefault(f"{key}_ev", [])
            if st.button("Nouvelle conversation", key=f"{key}_reset"):
                S[key], S[f"{key}_ev"] = [], []
                st.rerun()
            for m in history:
                if m["role"] in ("user", "assistant") and m.get("content"):
                    with st.chat_message(m["role"]):
                        st.markdown(m["content"])
            if events_log:
                with st.expander(f"Actions exécutées ({len(events_log)})"):
                    for line in events_log:
                        st.caption(line)
            prompt = st.chat_input("Votre message")
            if prompt:
                with st.chat_message("user"):
                    st.markdown(prompt)
                convo = list(history)
                convo.append({"role": "user", "content": prompt})
                infra = steps.get("infrastructure") or {}
                try:
                    w, sql, _ = state.user_session()
                    tctx = ToolContext(sql=sql, workspace=w, max_rows=int(infra.get("max_rows", 200)),
                                       conversation_id=key)
                    with st.spinner("L'agent réfléchit..."):
                        res = studio.run_turn(ctx, aid, ver, convo, ModelClient(w), tctx)
                except SaasError as e:
                    st.error(str(e))
                except Exception as e:  # noqa: BLE001
                    error_box("Exécution de l'agent en échec", e)
                else:
                    S[key] = list(res.messages[1:])   # conversation complète, sans le message système
                    S[f"{key}_ev"] = events_log + [f"{e.tool_id} : {e.status}" + (f" — {e.error}" if e.error else "")
                                                   for e in res.events]
                    if res.pending:
                        S[key].append({"role": "assistant", "content": "Une action demande une validation humaine, "
                                       "non prise en charge dans le test : reformulez sans cette action."})
                    st.rerun()
            st.caption("Chaque message est exécuté avec vos droits Databricks, journalisé (saas_executions) et mesuré "
                       "(saas_usage).")
