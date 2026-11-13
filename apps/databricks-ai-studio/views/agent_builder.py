"""Assistant de création d'agent en 6 étapes."""
import streamlit as st

from backend.agent_runtime import AgentConfig
from ui import state
from ui.chat_panel import render_chat
from ui.components import ICONS

STEPS = ["Informations", "Modèle IA", "Instructions", "Outils", "Connaissances", "Test et publication"]
CATEGORIES = ["Général", "Qualité des données", "Analyse", "FinOps", "Documents", "Gouvernance", "Exploitation"]
s_cfg = state.settings()
user = state.current_user()

if "builder" not in st.session_state:
    b = {"step": 0, "agent_id": None, "name": "", "description": "", "icon": "smart_toy", "category": "Général",
         "model_endpoint": s_cfg.default_model, "instructions": "", "tool_ids": [], "knowledge_tables": [],
         "temperature": 0.1, "max_iterations": s_cfg.max_iterations}
    edit_id = st.session_state.pop("builder_edit_id", None)
    if edit_id:
        a = state.repository().get_agent(edit_id)
        cfg = state.repository().get_config(edit_id)
        if a and cfg:
            b.update(agent_id=edit_id, name=a["name"], description=a.get("description") or "",
                     icon=a.get("icon") or "smart_toy", category=a.get("category") or "Général",
                     model_endpoint=cfg.model_endpoint, instructions=cfg.instructions, tool_ids=cfg.tool_ids,
                     knowledge_tables=cfg.knowledge_tables, temperature=cfg.temperature or 0.0,
                     max_iterations=cfg.max_iterations)
    st.session_state["builder"] = b
b = st.session_state["builder"]

st.title("Agent Builder")
st.caption(("Modification de « " + b["name"] + " »") if b["agent_id"] else "Nouvel agent")
st.progress((b["step"] + 1) / len(STEPS), text=f"Étape {b['step'] + 1}/{len(STEPS)} : {STEPS[b['step']]}")
nav = st.columns(len(STEPS))
for i, name in enumerate(STEPS):
    if nav[i].button(name, key=f"step_{i}", type="primary" if i == b["step"] else "secondary",
                     use_container_width=True):
        b["step"] = i
        st.rerun()


def errors_for(step: int) -> list[str]:
    e = []
    if step >= 0 and not b["name"].strip():
        e.append("Le nom est obligatoire.")
    if step >= 1 and not b["model_endpoint"]:
        e.append("Choisissez un modèle.")
    if step >= 2 and len(b["instructions"].strip()) < 20:
        e.append("Les instructions doivent faire au moins 20 caractères.")
    return e


with st.container(border=True):
    step = b["step"]
    if step == 0:
        b["name"] = st.text_input("Nom de l'agent", b["name"], max_chars=80)
        b["description"] = st.text_area("Description", b["description"], max_chars=500)
        c1, c2 = st.columns(2)
        b["icon"] = c1.selectbox("Icône", ICONS, index=ICONS.index(b["icon"]) if b["icon"] in ICONS else 0,
                                 format_func=lambda x: x.replace("_", " "))
        c1.markdown(f"Aperçu : :material/{b['icon']}:")
        b["category"] = c2.selectbox("Catégorie métier", CATEGORIES,
                                     index=CATEGORIES.index(b["category"]) if b["category"] in CATEGORIES else 0)
    elif step == 1:
        try:
            endpoints = state.chat_endpoints()
        except Exception as e:  # noqa: BLE001
            st.error(f"Liste des endpoints indisponible : {e}")
            endpoints = [b["model_endpoint"]]
        if b["model_endpoint"] not in endpoints:
            endpoints = [b["model_endpoint"]] + endpoints
        b["model_endpoint"] = st.selectbox("Endpoint Model Serving (chat, appel d'outils)", endpoints,
                                           index=endpoints.index(b["model_endpoint"]))
        c1, c2 = st.columns(2)
        b["temperature"] = c1.slider("Température", 0.0, 1.0, float(b["temperature"]), 0.05)
        b["max_iterations"] = c2.slider("Itérations maximales (outil + modèle)", 1, 12, int(b["max_iterations"]))
        st.caption("Seuls les endpoints prêts de type llm/v1/chat, visibles avec vos droits, sont proposés.")
    elif step == 2:
        b["instructions"] = st.text_area("Rôle et comportement de l'agent (prompt système)", b["instructions"],
                                         height=260, placeholder="Tu es un assistant qui ...")
        st.caption("Le cadre d'exécution (droits de l'utilisateur, tables autorisées, lecture seule) est ajouté automatiquement.")
    elif step == 3:
        tools = state.cached_tools()
        pub = [t for t in tools if t.status == "publie"]
        labels = {t.tool_id: f"{t.name} ({t.tool_id})" for t in pub}
        b["tool_ids"] = st.multiselect("Outils du Tool Catalog", list(labels), [t for t in b["tool_ids"] if t in labels],
                                       format_func=labels.get)
        for t in pub:
            if t.tool_id in b["tool_ids"]:
                st.markdown(f"- **{t.name}** : {t.description}")
        others = [t for t in tools if t.status != "publie"]
        if others:
            st.caption("Non disponibles dans le MVP : " + ", ".join(f"{t.tool_id} ({t.status})" for t in others))
    elif step == 4:
        st.write("Tables autorisées pour l'agent. Si la liste est vide, l'agent peut consulter toute table "
                 "accessible à l'utilisateur ; sinon describe_table, get_table_profile et execute_sql sont restreints à cette liste.")
        c1, c2, c3 = st.columns([2, 2, 1])
        cat = c1.text_input("Catalogue", "dataops_dev")
        sch = c2.text_input("Schéma", "description_du_reseau_bronze")
        if c3.button("Lister", icon=":material/search:"):
            try:
                from tools.uc_tools import list_tables
                from backend.tool_registry import ToolContext
                w_, sql_, _ = state.user_session()
                st.session_state["kb_tables"] = [t["table"] for t in list_tables(ToolContext(sql_, w_), cat, sch)["tables"]]
            except Exception as e:  # noqa: BLE001
                st.error(f"Lecture impossible avec vos droits : {e}")
        options = sorted(set(st.session_state.get("kb_tables", [])) | set(b["knowledge_tables"]))
        b["knowledge_tables"] = st.multiselect("Tables sélectionnées", options, b["knowledge_tables"])
        manual = st.text_input("Ajouter une table (catalog.schema.table)")
        if st.button("Ajouter") and manual.count(".") == 2:
            b["knowledge_tables"] = sorted(set(b["knowledge_tables"]) | {manual.strip()})
            st.rerun()
        st.caption("Documents PDF et index Vector Search : Knowledge Studio (phase 2).")
    else:
        errs = errors_for(5)
        if errs:
            for e in errs:
                st.warning(e)
        else:
            cfg = AgentConfig(agent_id=b["agent_id"] or "brouillon-" + user.email, version=0, name=b["name"],
                              model_endpoint=b["model_endpoint"], instructions=b["instructions"],
                              tool_ids=b["tool_ids"], knowledge_tables=b["knowledge_tables"],
                              temperature=b["temperature"], max_iterations=b["max_iterations"])
            st.markdown("**Test de l'agent (non enregistré dans l'historique)**")
            render_chat(cfg, key="builder", persist=False)

c1, c2, c3, c4 = st.columns(4)
if c1.button("Précédent", disabled=b["step"] == 0, icon=":material/arrow_back:"):
    b["step"] -= 1
    st.rerun()
if c2.button("Suivant", disabled=b["step"] == len(STEPS) - 1, icon=":material/arrow_forward:"):
    errs = errors_for(b["step"])
    if errs:
        st.warning(" ".join(errs))
    else:
        b["step"] += 1
        st.rerun()


def save(status: str):
    errs = errors_for(5)
    if errs:
        st.warning(" ".join(errs))
        return
    meta = {k: b[k] for k in ("name", "description", "icon", "category")}
    cfg = {k: b[k] for k in ("model_endpoint", "instructions", "tool_ids", "knowledge_tables",
                             "temperature", "max_iterations")}
    repo = state.repository()
    try:
        if b["agent_id"]:
            v = repo.save_version(b["agent_id"], meta, cfg, user.email, status)
            st.success(f"Version {v} enregistrée ({status}).")
        else:
            b["agent_id"] = repo.create_agent(meta, cfg, user.email, status)
            st.success(f"Agent créé ({status}).")
        state.refresh_data()
    except Exception as e:  # noqa: BLE001
        st.error(f"Enregistrement impossible : {e}")


if c3.button("Enregistrer en brouillon", icon=":material/save:"):
    save("brouillon")
if c4.button("Enregistrer et publier", type="primary", icon=":material/publish:"):
    save("publie")
