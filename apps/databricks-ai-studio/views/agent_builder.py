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

# -- Copilote de conception (agents nouveaux uniquement) ---------------------
if not b["agent_id"]:
    with st.expander(":material/auto_awesome: Décrire votre agent en langage naturel",
                     expanded=not b.get("ai_result")):
        st.caption("Le copilote explore les données avec vos droits, choisit parmi les outils publiés et "
                   "pré-remplit les 6 étapes. Rien n'est enregistré sans votre action.")
        req = st.text_area("Votre besoin", key="ai_request", height=110,
                           placeholder="Ex. : Je veux un agent qui explique les résultats des contrôles qualité "
                                       "et résume les anomalies par dimension.")
        scope = st.text_input("Périmètre de données (facultatif, catalog.schema)", key="ai_scope",
                              placeholder="dataops_dev.description_du_reseau_bronze")
        if st.button("Générer le brouillon", type="primary", key="ai_go"):
            repo = state.repository()
            try:
                with st.spinner("Le copilote analyse votre besoin et explore les données..."):
                    res = state.build_designer().design(req, scope.strip() or None)
                b.update(res.draft)
                b["step"] = 0
                b["ai_result"] = {"warnings": res.warnings, "hypotheses": res.hypotheses,
                                  "test_questions": res.test_questions, "latency_ms": res.latency_ms,
                                  "explored": [f"{e.tool_id}({', '.join(str(v) for v in e.arguments.values())}) : "
                                               f"{'ok' if e.status == 'succes' else e.error}" for e in res.events]}
                try:
                    repo.log_generation("agent", user.email, req, scope.strip() or None, s_cfg.default_model,
                                        proposal=res.raw_proposal, draft=res.draft, warnings=res.warnings,
                                        latency_ms=res.latency_ms)
                except Exception as e:  # noqa: BLE001
                    st.warning(f"Génération non journalisée : {e}")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Génération impossible : {e}")
                try:
                    repo.log_generation("agent", user.email, req or "", scope.strip() or None, s_cfg.default_model,
                                        status="erreur", error=str(e))
                except Exception:  # noqa: BLE001
                    pass

# -- Amélioration assistée (agents existants) ---------------------------------
FIELDS = ("name", "description", "icon", "category", "model_endpoint", "instructions", "tool_ids",
          "knowledge_tables", "temperature", "max_iterations")
if b["agent_id"]:
    with st.expander(":material/auto_fix_high: Améliorer cet agent avec l'IA",
                     expanded=st.session_state.pop("builder_improve", False) or bool(b.get("ai_improve"))):
        st.caption("Le copilote relit la configuration en cours, peut tenir compte des erreurs récentes de "
                   "l'agent et propose une version complète. Vous comparez puis appliquez ; l'enregistrement "
                   "crée une nouvelle version.")
        imp_req = st.text_area("Que voulez-vous améliorer ? (facultatif)", key="ai_improve_request", height=90,
                               placeholder="Ex. : réponses plus courtes avec un tableau, ajouter le profilage, "
                                           "mieux gérer les tables vides.")
        use_errors = st.checkbox("Tenir compte des erreurs récentes de l'agent", value=True, key="ai_improve_err")
        if st.button("Proposer des améliorations", type="primary", key="ai_improve_go"):
            repo = state.repository()
            current = {k: b[k] for k in FIELDS}
            try:
                signals = repo.recent_agent_errors(b["agent_id"]) if use_errors else []
                with st.spinner("Le copilote analyse l'agent..."):
                    res = state.build_designer().improve(current, imp_req, signals)
                from backend.agent_designer import config_diff
                b["ai_improve"] = {"draft": res.draft, "changes": res.changes, "warnings": res.warnings,
                                   "hypotheses": res.hypotheses, "test_questions": res.test_questions,
                                   "diff": config_diff(current, res.draft), "latency_ms": res.latency_ms,
                                   "signals": len(signals)}
                try:
                    repo.log_generation("amelioration", user.email, imp_req or "(amélioration générale)", b["agent_id"],
                                        s_cfg.default_model, proposal=res.raw_proposal, draft=res.draft,
                                        warnings=res.warnings, latency_ms=res.latency_ms)
                except Exception as e:  # noqa: BLE001
                    st.warning(f"Génération non journalisée : {e}")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Amélioration impossible : {e}")

        imp = b.get("ai_improve")
        if imp:
            st.markdown(f"**Proposition du copilote** ({imp['latency_ms'] / 1000:.1f} s, "
                        f"{imp['signals']} erreur(s) récente(s) prise(s) en compte)")
            for c in imp["changes"]:
                st.markdown(f"- {c}")
            for wmsg in imp["warnings"]:
                st.warning(wmsg)
            if not imp["diff"]:
                st.info("Aucune différence avec la configuration actuelle.")
            for d in imp["diff"]:
                if d["cle"] == "instructions":
                    import difflib
                    st.markdown("**Instructions**")
                    st.code("\n".join(difflib.unified_diff((d["actuel"] or "").splitlines(),
                                                           (d["propose"] or "").splitlines(),
                                                           "actuel", "propose", lineterm="")), language="diff")
                elif "ajouts" in d:
                    st.markdown(f"**{d['champ']}** : ajouts {d['ajouts'] or 'aucun'} · retraits {d['retraits'] or 'aucun'}")
                else:
                    st.markdown(f"**{d['champ']}** : `{d['actuel']}` devient `{d['propose']}`")
            if imp["hypotheses"]:
                with st.expander("Hypothèses du copilote"):
                    for h in imp["hypotheses"]:
                        st.markdown(f"- {h}")
            c_ok, c_no = st.columns(2)
            if c_ok.button("Appliquer au brouillon", type="primary", key="ai_improve_apply", disabled=not imp["diff"]):
                b.update({k: v for k, v in imp["draft"].items() if k in FIELDS})
                b["ai_result"] = {"warnings": [], "hypotheses": imp["hypotheses"],
                                  "test_questions": imp["test_questions"], "latency_ms": imp["latency_ms"],
                                  "explored": []}
                b.pop("ai_improve", None)
                b["step"] = 5
                st.rerun()
            if c_no.button("Ignorer la proposition", key="ai_improve_drop"):
                b.pop("ai_improve", None)
                st.rerun()

ai = b.get("ai_result")
if ai:
    st.info(f"Brouillon généré par l'IA en {ai['latency_ms'] / 1000:.1f} s : relisez chaque étape, testez, "
            "puis enregistrez. Toute règle ou tout seuil proposé reste à valider par le responsable métier.")
    for wmsg in ai["warnings"]:
        st.warning(wmsg)
    if ai["hypotheses"] or ai["explored"]:
        with st.expander("Hypothèses et exploration du copilote"):
            for h in ai["hypotheses"]:
                st.markdown(f"- {h}")
            if ai["explored"]:
                st.caption("Outils appelés pendant la conception")
                for x in ai["explored"]:
                    st.caption(x)
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
        if c3.button("Lister"):
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
            if ai and ai.get("test_questions"):
                st.markdown("**Questions de test suggérées par le copilote**")
                for q in ai["test_questions"]:
                    st.markdown(f"- {q}")
            st.markdown("**Test de l'agent (non enregistré dans l'historique)**")
            render_chat(cfg, key="builder", persist=False)

c1, c2, c3, c4 = st.columns(4)
if c1.button("Précédent", disabled=b["step"] == 0):
    b["step"] -= 1
    st.rerun()
if c2.button("Suivant", disabled=b["step"] == len(STEPS) - 1):
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


if c3.button("Enregistrer en brouillon"):
    save("brouillon")
if c4.button("Enregistrer et publier", type="primary"):
    save("publie")
