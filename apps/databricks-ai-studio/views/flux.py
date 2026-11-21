"""Rubrique Flux : flux Power Automate utilisables par les agents (lot 1, mode boîte d'échange). Streamlit 1.38."""
import datetime as dt
import json

import streamlit as st

from backend import flux
from backend.tool_registry import ToolError, validate_args
from tools import flow_tools
from ui import state
from ui.components import badge

S = st.session_state
me = state.current_user().email
repo = state.repository()
admins = set(state.settings().tool_admins)
S.setdefault("fx_rev", 0)

st.title("Flux Builder")
st.caption("Flux Power Automate utilisables comme outils par les agents. L'agent dépose une demande dans une table "
           "Delta ; le flux la lit avec le connecteur Azure Databricks, l'exécute et y écrit sa réponse. Aucun appel "
           "sortant depuis Databricks.")

flows = [t for t in state.cached_tools() if flux.is_flux(t) and (t.status == "publie" or t.owner == me)]
mine = [t for t in flows if t.owner == me]


def refresh():
    state.cached_tools.clear()
    st.rerun()


def load_draft(d: dict | None):
    S["fx_draft"] = d or {"name": "", "description": "", "type": "lecture", "parametres": [], "valeurs_fixes": {},
                          "reponse": "", "delai_minutes": 60}
    S["fx_rev"] += 1


if "fx_draft" not in S:
    load_draft(None)

tab_list, tab_edit, tab_test, tab_pa, tab_hist = st.tabs(
    ["Flux", "Créer ou modifier", "Banc de test", "Configurer Power Automate", "Historique"])

# --- Liste ------------------------------------------------------------------------------------------------------------
with tab_list:
    if not flows:
        st.info("Aucun flux pour le moment : créez-en un dans l'onglet « Créer ou modifier ».")
    for t in flows:
        c = t.config or {}
        with st.expander(f"{t.name} · {t.tool_id}", expanded=False):
            st.markdown(f"{badge(t.status)} · {c.get('type', 'lecture')} · v{t.version} · propriétaire {t.owner}"
                        + (" · confirmation de l'utilisateur avant envoi" if t.requires_confirmation else ""),
                       unsafe_allow_html=True)
            st.write(c.get("description", ""))
            if c.get("parametres"):
                st.dataframe([{"paramètre": p["nom"], "type": flux.TYPE_LABELS.get(p["type"], p["type"]),
                               "obligatoire": p["obligatoire"], "description": p["description"],
                               "valeurs": ", ".join(p.get("valeurs") or [])} for p in c["parametres"]],
                             use_container_width=True, hide_index=True)
            if c.get("valeurs_fixes") and t.owner == me:
                st.caption("Valeurs fixes (cachées au modèle) : " + ", ".join(c["valeurs_fixes"]))
            if c.get("reponse"):
                st.caption("Réponse attendue : " + c["reponse"])
            if t.owner == me:
                b1, b2, b3 = st.columns(3)
                if b1.button("Modifier", key=f"fx_edit_{t.tool_id}"):
                    load_draft(flux.draft_from_spec(t))
                    st.info("Flux chargé dans l'onglet « Créer ou modifier ».")
                target = {"publie": ("Retirer", "retire"), "brouillon": ("Publier", "publie"),
                          "retire": ("Repasser en brouillon", "brouillon")}[t.status]
                if b2.button(target[0], key=f"fx_status_{t.tool_id}"):
                    try:
                        repo.set_tool_status(t.tool_id, target[1], me)
                        refresh()
                    except PermissionError as e:
                        st.error(str(e))
                if t.status == "publie" and b3.button("Repasser en brouillon", key=f"fx_draft_{t.tool_id}"):
                    repo.set_tool_status(t.tool_id, "brouillon", me)
                    refresh()

# --- Création / modification ------------------------------------------------------------------------------------------
with tab_edit:
    d, rev = S["fx_draft"], S["fx_rev"]
    editing = bool(d.get("tool_id")) and any(t.tool_id == d["tool_id"] for t in mine)
    st.caption(f"Modification de « {d['tool_id']} »" if editing else "Nouveau flux")
    if editing and st.button("Nouveau flux (vider le formulaire)", key=f"fx_new_{rev}"):
        load_draft(None)
        st.rerun()
    name = st.text_input("Nom du flux", d["name"], key=f"fx_name_{rev}")
    tool_id = d["tool_id"] if editing else flux.flux_id_for(name)
    st.caption(f"Identifiant de l'outil : `{tool_id}`")
    desc = st.text_area("Description pour le modèle : ce que fait le flux et quand l'utiliser", d["description"],
                        key=f"fx_desc_{rev}")
    kind = st.radio("Type", flux.KINDS, index=flux.KINDS.index(d.get("type", "lecture")), horizontal=True,
                    key=f"fx_kind_{rev}",
                    format_func=lambda k: "Lecture (renvoie une information)" if k == "lecture"
                    else "Action (envoie, crée ou modifie) : confirmation de l'utilisateur avant chaque envoi")
    st.markdown("**Paramètres demandés à l'agent**")
    rows = [{**p, "valeurs": ", ".join(p.get("valeurs") or [])} for p in d.get("parametres") or []]
    params = st.data_editor(
        rows or [{"nom": "", "type": "string", "obligatoire": True, "description": "", "valeurs": ""}],
        num_rows="dynamic", use_container_width=True, key=f"fx_params_{rev}",
        column_config={"nom": st.column_config.TextColumn("nom (a-z, 0-9, _)"),
                       "type": st.column_config.SelectboxColumn("type", options=list(flux.TYPES), required=True),
                       "obligatoire": st.column_config.CheckboxColumn("obligatoire"),
                       "description": st.column_config.TextColumn("description pour le modèle"),
                       "valeurs": st.column_config.TextColumn("valeurs (type enum, séparées par des virgules)")})
    st.markdown("**Valeurs fixes** (transmises au flux, jamais montrées au modèle ni modifiables par l'agent)")
    fixes = st.data_editor([{"nom": k, "valeur": str(v)} for k, v in (d.get("valeurs_fixes") or {}).items()]
                           or [{"nom": "", "valeur": ""}], num_rows="dynamic", use_container_width=True,
                           key=f"fx_fixes_{rev}")
    reponse = st.text_area("Réponse attendue du flux (pour le modèle)", d.get("reponse", ""), key=f"fx_rep_{rev}")
    delai = st.number_input("Délai au-delà duquel une demande non prise en charge est expirée (minutes)", 1, 1440,
                            int(d.get("delai_minutes") or 60), key=f"fx_delai_{rev}")
    draft = {"tool_id": tool_id, "name": name, "description": desc, "type": kind,
             "parametres": params if isinstance(params, list) else params.to_dict("records"),
             "valeurs_fixes": fixes if isinstance(fixes, list) else fixes.to_dict("records"),
             "reponse": reponse, "delai_minutes": delai}
    errs = flux.check(draft, repo.tool_owners(), me) if name else ["Nom du flux manquant."]
    for e in errs:
        st.warning(e)
    note = st.text_input("Note de version (facultatif)", key=f"fx_note_{rev}")
    if st.button("Enregistrer en brouillon", disabled=bool(errs), type="primary", key=f"fx_save_{rev}"):
        try:
            spec = flux.build_spec(draft, me, status="brouillon")
            v = repo.save_custom_tool(spec, me, {"enregistrement": "formulaire Flux"}, note)
            S["fx_draft"] = flux.draft_from_spec(spec)
            st.success(f"Flux {spec.tool_id} enregistré en brouillon (version {v}). Testez-le puis publiez-le.")
            state.cached_tools.clear()
        except (PermissionError, ValueError) as e:
            st.error(str(e))
    if kind == "action" and me.lower() not in admins:
        st.caption("Un flux de type action ne peut être publié que par un administrateur des outils.")

# --- Banc de test -----------------------------------------------------------------------------------------------------
with tab_test:
    testable = [t for t in flows if t.owner == me or t.status == "publie"]
    if not testable:
        st.info("Enregistrez d'abord un flux.")
    else:
        t = st.selectbox("Flux à tester", testable, format_func=lambda x: f"{x.name} ({x.tool_id}, {x.status})",
                         key="fx_test_sel")
        st.caption("La demande est marquée test=true dans la table : le flux peut la traiter sans effet réel.")
        with st.form(f"fx_test_form_{t.tool_id}"):
            args = {}
            props = t.input_schema.get("properties") or {}
            for p in (t.config or {}).get("parametres") or []:
                if p["nom"] not in props:
                    continue
                lab = f"{p['nom']}{' *' if p['obligatoire'] else ''} · {p['description']}"
                if p["type"] == "boolean":
                    args[p["nom"]] = st.checkbox(lab)
                elif p["type"] == "integer":
                    args[p["nom"]] = int(st.number_input(lab, step=1, value=0))
                elif p["type"] == "number":
                    args[p["nom"]] = float(st.number_input(lab, value=0.0))
                elif p["type"] == "date":
                    args[p["nom"]] = st.date_input(lab, dt.date.today()).isoformat()
                elif p["type"] == "enum":
                    args[p["nom"]] = st.selectbox(lab, p["valeurs"])
                else:
                    args[p["nom"]] = st.text_input(lab)
            sent = st.form_submit_button("Déposer une demande de test")
        if sent:
            try:
                clean = validate_args(t.input_schema, {k: v for k, v in args.items() if v not in (None, "")})
                r = flow_tools.submit(repo.sql, t, clean, me, conversation_id="banc-de-test", test=True)
                S["fx_last"] = r["demande_id"]
                st.success(f"Demande {r['demande_id']} déposée (en_attente).")
            except ToolError as e:
                st.error(str(e))
        if S.get("fx_last"):
            st.markdown(f"Dernière demande : `{S['fx_last']}`")
            if st.button("Actualiser le statut", key="fx_refresh"):
                pass
            try:
                st.json(flow_tools.read_request(repo.sql, S["fx_last"], me))
            except ToolError as e:
                st.error(str(e))

# --- Configuration Power Automate -------------------------------------------------------------------------------------
with tab_pa:
    own = [t for t in flows if t.owner == me]
    if not own:
        st.info("Aucun flux dont vous êtes propriétaire.")
    else:
        t = st.selectbox("Flux", own, format_func=lambda x: f"{x.name} ({x.tool_id})", key="fx_pa_sel")
        table = state.settings().table(flux.TABLE)
        st.warning("À vérifier dans votre environnement Power Platform : disponibilité du connecteur Azure Databricks et "
                   "identité utilisée (elle doit pouvoir lire et modifier " + table + ").")
        st.markdown(
            "1. Déclencheur **Récurrence** (par exemple toutes les 2 minutes).\n"
            "2. Action Azure Databricks d'exécution SQL avec la requête **1** : demandes en attente.\n"
            "3. **Appliquer à chacun** sur les lignes : requête **2** (prise en charge), puis **Analyser JSON** sur "
            "`parametres` avec le schéma ci-dessous.\n"
            "4. Votre traitement (Outlook, Teams, SharePoint...). Si `test` vaut true, ne pas produire d'effet réel.\n"
            "5. Requête **3** avec la réponse en JSON, ou requête **4** en cas d'erreur.\n\n"
            "Dans les requêtes 3 et 4, doubler les apostrophes du contenu inséré (expression "
            "`replace(variable, '''', '''''')`) pour éviter de casser la requête.")
        st.markdown("**Schéma JSON de `parametres`**")
        st.code(json.dumps(flux.json_schema(t), ensure_ascii=False, indent=2), language="json")
        for title, q in flux.pa_queries(t, table).items():
            st.markdown(f"**{title}**")
            st.code(q, language="sql")

# --- Historique -------------------------------------------------------------------------------------------------------
with tab_hist:
    opts = ["Tous"] + [t.tool_id for t in flows]
    f = st.selectbox("Flux", opts, key="fx_hist_sel")
    try:
        rows = repo.list_flux_requests(me, None if f == "Tous" else f, 100)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune demande.")
    except Exception as e:  # noqa: BLE001 (table absente : initialisation dans Paramètres)
        st.error(f"Historique indisponible : {e}")
