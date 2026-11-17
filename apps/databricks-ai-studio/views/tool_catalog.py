import json

import pandas as pd
import streamlit as st

from backend import tool_builder as tb
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from ui import state
from ui.components import badge

st.title("Catalogue d'outils")
tools = [t for t in state.cached_tools() if t.category != "Flux"]   # flux : page Flux
if not tools:
    st.warning("Catalogue vide : initialisez-le dans Paramètres.")
    st.stop()
me = state.current_user().email
S = st.session_state
S.setdefault("td_rev", 0)


def visible(t) -> bool:
    """Outils intégrés et outils créés publiés ; brouillons et outils retirés : visibles par leur propriétaire seul."""
    return not tb.is_custom(t) or t.status == "publie" or t.owner == me


def load_draft(draft: dict, meta: dict | None = None):
    S["td_draft"], S["td_meta"] = draft, meta or {}
    S.pop("td_test", None)
    S["td_rev"] += 1


tab_cat, tab_new, tab_mine = st.tabs(["Catalogue", "Créer avec l'IA", "Mes outils"])

# --- Catalogue ----------------------------------------------------------------------------------------------
with tab_cat:
    c1, c2, c3 = st.columns([3, 2, 2])
    q = c1.text_input("Rechercher un outil").lower().strip()
    shown = [t for t in tools if visible(t)]
    cats = ["Toutes"] + sorted({t.category for t in shown})
    cat = c2.selectbox("Catégorie", cats)
    stat = c3.selectbox("Statut", ["Tous", "publie", "brouillon", "planifie", "indisponible", "retire"])
    sel = [t for t in shown if (cat == "Toutes" or t.category == cat) and (stat == "Tous" or t.status == stat)
           and (not q or q in f"{t.tool_id} {t.name} {t.description}".lower())]
    st.caption(f"{len(sel)} outil(s)")
    cols = st.columns(2)
    for i, t in enumerate(sel):
        with cols[i % 2].container(border=True):
            st.markdown(f"#### {t.name}")
            origin = f" · créé par {t.owner}" if tb.is_custom(t) else ""
            st.markdown(f"`{t.tool_id}` · {t.category} · v{t.version}{origin} {badge(t.status)}", unsafe_allow_html=True)
            st.write(t.description)
            st.caption(f"Identité : {t.identity} · lecture seule : {'oui' if t.read_only else 'non'} · "
                       f"validation humaine : {'oui' if t.requires_confirmation else 'non'}")
            with st.expander("Fiche technique"):
                st.markdown(f"Exécuteur : `{t.executor}`")
                if t.config.get("sql"):
                    st.code(t.config["sql"], language="sql")
                if t.config.get("function"):
                    st.markdown(f"Fonction : `{t.config['function']}`")
                st.caption("Schéma d'entrée")
                st.json(t.input_schema)
                st.caption("Schéma de sortie")
                st.json(t.output_schema)
            if t.status == "publie" or (tb.is_custom(t) and t.owner == me):
                with st.expander("Tester l'outil"):
                    example = (t.config.get("examples") if tb.is_custom(t) else None) or \
                        {k: "" for k in t.input_schema.get("required", [])}
                    raw = st.text_area("Arguments JSON", json.dumps(example, ensure_ascii=False), key=f"args_{t.tool_id}")
                    if st.button("Exécuter", key=f"run_{t.tool_id}"):
                        try:
                            w_, sql_, _ = state.user_session()
                            out = ToolRegistry([t]).run(t, ToolContext(sql_, w_, max_rows=state.settings().max_rows),
                                                        json.loads(raw or "{}"))
                            st.json(out)
                        except (ToolError, json.JSONDecodeError) as e:
                            st.error(str(e))
                        except Exception as e:  # noqa: BLE001
                            st.error(f"Erreur technique : {e}")

# --- Créer avec l'IA -------------------------------------------------------------------------------------------
with tab_new:
    st.markdown("Décrivez l'outil voulu : le copilote explore les données avec vos droits, propose un outil "
                "(requête SQL paramétrée en lecture seule ou fonction Unity Catalog), le vérifie, puis vous le testez "
                "avant de l'enregistrer. Aucun code n'est généré ni exécuté : seulement une requête contrôlée.")
    req = st.text_area("Votre besoin", key="td_request", height=90,
                       placeholder="Ex. : un outil qui liste les gares voyageurs d'un département avec leurs coordonnées")
    scope = st.text_input("Périmètre de données (catalogue.schéma, facultatif)", "dataops_dev.ai_studio",
                          key="td_scope", help="Le copilote commence par explorer ce schéma.")
    if st.button("Proposer un outil", type="primary"):
        try:
            with st.spinner("Le copilote explore les données et construit l'outil..."):
                res = state.build_tool_designer().design(req, scope)
            if res.draft is None:
                S.pop("td_draft", None)
                st.warning("Demande non couverte par les types d'outils disponibles : " + res.unsupported)
            else:
                load_draft(res.draft, {"hypotheses": res.hypotheses, "changes": res.changes,
                                       "exploration": len(res.events), "tentatives": res.attempts,
                                       "latence_ms": res.latency_ms, "erreurs_copilote": res.check.errors})
        except ToolError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.error(f"Erreur technique du copilote : {e}")

    draft = S.get("td_draft")
    if draft:
        rev, meta = S["td_rev"], S.get("td_meta") or {}
        st.divider()
        if meta.get("latence_ms"):
            st.caption(f"Proposition en {meta['latence_ms'] / 1000:.1f} s · {meta.get('exploration', 0)} étape(s) "
                       f"d'exploration · {meta.get('tentatives', 1)} proposition(s)")
        for h in meta.get("hypotheses") or []:
            st.info("Hypothèse : " + h)
        for ch in meta.get("changes") or []:
            st.caption("Modification : " + ch)

        c1, c2, c3 = st.columns([3, 2, 2])
        name = c1.text_input("Nom", draft["name"], key=f"td_name_{rev}")
        tool_id = c2.text_input("Identifiant", draft["tool_id"], key=f"td_id_{rev}")
        cats = tb.CATEGORIES + sorted({t.category for t in tools} - set(tb.CATEGORIES))
        category = c3.selectbox("Catégorie", cats, index=cats.index(draft["category"]) if draft["category"] in cats else 0,
                                key=f"td_cat_{rev}")
        description = st.text_area("Description (lue par les agents)", draft["description"], key=f"td_desc_{rev}")
        kinds = list(tb.EXECUTORS)
        kind = st.radio("Type", kinds, index=kinds.index(draft["type"]), format_func=tb.TYPE_LABELS.get,
                        horizontal=True, key=f"td_type_{rev}")
        sql_txt, fn, fn_kind = draft["sql"], draft["function"], draft["function_kind"]
        http = {k: draft.get(k) for k in ("connection", "method", "path", "body", "query", "headers")}

        def _js(v):
            return "" if v in (None, {}) else json.dumps(v, ensure_ascii=False, indent=1)
        if kind == "sql_template":
            sql_txt = st.text_area("Requête SQL (paramètres :nom)", draft["sql"], height=160, key=f"td_sql_{rev}")
        elif kind == "http_connection":
            h1, h2, h3 = st.columns([2, 1, 3])
            http["connection"] = h1.text_input("Connexion HTTP Unity Catalog", draft.get("connection") or "",
                                               key=f"td_conn_{rev}", help="Créée par un administrateur du metastore ; "
                                               "les identifiants restent dans la connexion.")
            methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
            http["method"] = h2.selectbox("Méthode", methods, index=methods.index(draft.get("method") or "GET")
                                          if (draft.get("method") or "GET") in methods else 0, key=f"td_meth_{rev}")
            http["path"] = h3.text_input("Chemin (paramètres {{nom}})", draft.get("path") or "/", key=f"td_path_{rev}")
            if http["method"] != "GET":
                http["body"] = st.text_area("Corps JSON (paramètres {{nom}})", _js(draft.get("body")), height=140,
                                            key=f"td_body_{rev}")
                st.info("Appel en écriture : validation humaine à chaque appel ; publication réservée aux "
                        "administrateurs des outils.")
            else:
                http["body"] = None
            q1, q2 = st.columns(2)
            http["query"] = q1.text_area("Paramètres de requête JSON", _js(draft.get("query")), key=f"td_query_{rev}")
            http["headers"] = q2.text_area("En-têtes fixes JSON (sans identifiants)", _js(draft.get("headers")),
                                           key=f"td_head_{rev}")
        else:
            f1, f2 = st.columns([3, 1])
            fn = f1.text_input("Fonction Unity Catalog", draft["function"], key=f"td_fn_{rev}")
            fn_kind = f2.selectbox("Résultat", ["scalar", "table"], index=0 if draft["function_kind"] == "scalar" else 1,
                                   key=f"td_fk_{rev}")
        st.caption("Paramètres")
        pdf = pd.DataFrame(draft["parameters"] or [], columns=["name", "type", "description", "required", "example"])
        pdf["example"] = pdf["example"].map(lambda v: "" if v is None else str(v))
        edited = st.data_editor(pdf, num_rows="dynamic", use_container_width=True, key=f"td_params_{rev}",
                                column_config={
                                    "name": st.column_config.TextColumn("Nom"),
                                    "type": st.column_config.SelectboxColumn("Type", options=list(tb.PARAM_TYPES)),
                                    "description": st.column_config.TextColumn("Description"),
                                    "required": st.column_config.CheckboxColumn("Obligatoire"),
                                    "example": st.column_config.TextColumn("Exemple")})
        enums = {p["name"]: p.get("enum") for p in draft["parameters"]}
        params = [{"name": str(r["name"] or "").strip(), "type": r["type"] or "string",
                   "description": str(r["description"] or ""), "required": bool(r["required"]),
                   "example": r["example"], "enum": enums.get(str(r["name"] or "").strip())}
                  for r in edited.to_dict("records") if str(r.get("name") or "").strip()]
        max_rows = st.number_input("Lignes renvoyées au plus", 1, tb.MAX_ROWS, int(draft["max_rows"]), key=f"td_max_{rev}")
        current = tb.normalize({"tool_id": tool_id, "name": name, "category": category, "description": description,
                                "type": kind, "sql": sql_txt, "function": fn, "function_kind": fn_kind, **http,
                                "parameters": params, "max_rows": max_rows, "hypotheses": draft["hypotheses"]})
        S["td_draft"] = current
        fp = tb.fingerprint(current)

        if current["parameters"]:
            st.caption("Valeurs de test")
        tcols = st.columns(max(1, min(4, len(current["parameters"]))))
        test_args = {}
        for i, p in enumerate(current["parameters"]):
            v = tcols[i % len(tcols)].text_input(f"{p['name']} ({p['type']})",
                                                 "" if p.get("example") is None else str(p["example"]),
                                                 key=f"td_arg_{rev}_{p['name']}")
            test_args[p["name"]] = tb.coerce(v, p["type"])

        b1, b2 = st.columns([1, 3])
        if b1.button("Vérifier et tester", type="primary"):
            w_, sql_, _ = state.user_session()
            with st.spinner("Vérification (accès, compilation) puis test..."):
                existing = {t.tool_id: t for t in tools}
                chk = tb.check(current, existing, me, sql_)
                result = None
                if chk.ok:
                    spec = tb.build_spec(current, me)
                    result = tb.run_test(spec, test_args, ToolContext(sql_, w_, max_rows=state.settings().max_rows))
            S["td_test"] = {"fp": fp, "errors": chk.errors, "warnings": chk.warnings, "result": result}
        with b2.popover("Améliorer avec l'IA"):
            imp = st.text_input("Que faut-il changer ?", key=f"td_imp_{rev}",
                                placeholder="Ex. : rendre le segment DRG facultatif")
            if st.button("Proposer la modification"):
                try:
                    last = (S.get("td_test") or {}).get("result")
                    with st.spinner("Le copilote améliore l'outil..."):
                        res = state.build_tool_designer().improve(current, imp, last)
                    if res.draft is None:
                        st.warning(res.unsupported)
                    else:
                        load_draft(res.draft, {"hypotheses": res.hypotheses, "changes": res.changes,
                                               "exploration": len(res.events), "tentatives": res.attempts,
                                               "latence_ms": res.latency_ms})
                        st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"Erreur du copilote : {e}")

        tst = S.get("td_test")
        if tst and tst["fp"] == fp:
            for e in tst["errors"]:
                st.error(e)
            for wn in tst["warnings"]:
                st.warning(wn)
            r = tst["result"]
            if r and r["ok"] and "statut_http" in r:
                st.success(f"Test réussi : HTTP {r['statut_http']} en {r['duree_ms']} ms")
                st.code(r.get("reponse") or "", language="json")
            elif r and r["ok"]:
                st.success(f"Test réussi : {r['nombre_lignes']} ligne(s) en {r['duree_ms']} ms"
                           + (" (résultat tronqué à la limite)" if r.get("tronque") else ""))
                if r.get("apercu"):
                    st.dataframe(pd.DataFrame(r["apercu"]), use_container_width=True, hide_index=True)
            elif r:
                st.error("Test en échec : " + r["erreur"])
            ready = not tst["errors"] and r and r["ok"]
            note = st.text_input("Note de version (facultatif)", key=f"td_note_{rev}")
            s1, s2 = st.columns(2)
            for col, label, status in ((s1, "Enregistrer en brouillon", "brouillon"),
                                       (s2, "Enregistrer et publier", "publie")):
                if col.button(label, disabled=not ready, key=f"td_save_{status}"):
                    try:
                        spec = tb.build_spec(current, me, status=status)
                        v = state.repository().save_custom_tool(spec, me, r, note)
                        state.refresh_data()
                        where = "publié : disponible dans l'Agent Builder" if status == "publie" else "brouillon"
                        st.success(f"Outil « {spec.name} » enregistré (version {v}, {where}).")
                    except PermissionError as e:
                        st.error(str(e))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Enregistrement impossible : {e}")
        elif tst:
            st.caption("L'outil a été modifié depuis le dernier test : relancez « Vérifier et tester ».")
        else:
            st.caption("Étape suivante : « Vérifier et tester ». L'enregistrement n'est possible qu'après un test réussi.")

# --- Mes outils ------------------------------------------------------------------------------------------------
with tab_mine:
    mine = [t for t in tools if tb.is_custom(t) and t.owner == me]
    if not mine:
        st.info("Vous n'avez pas encore créé d'outil. Utilisez l'onglet « Créer avec l'IA ».")
    for t in mine:
        with st.container(border=True):
            st.markdown(f"**{t.name}** · `{t.tool_id}` · v{t.version} {badge(t.status)}", unsafe_allow_html=True)
            st.caption(t.description)
            a1, a2, a3, a4 = st.columns(4)
            actions = []
            if t.status != "publie":
                actions.append((a1, "Publier", "publie"))
            if t.status == "publie":
                actions.append((a1, "Repasser en brouillon", "brouillon"))
            if t.status != "retire":
                actions.append((a2, "Retirer", "retire"))
            for col, label, status in actions:
                if col.button(label, key=f"mt_{status}_{t.tool_id}"):
                    try:
                        state.repository().set_tool_status(t.tool_id, status, me)
                        state.refresh_data()
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(str(e))
            if a3.button("Modifier", key=f"mt_edit_{t.tool_id}"):
                load_draft(tb.draft_from_spec(t))
                st.success("Outil chargé dans l'onglet « Créer avec l'IA ».")
            with a4.popover("Versions"):
                try:
                    versions = state.repository().tool_versions(t.tool_id)
                except Exception as e:  # noqa: BLE001
                    versions = []
                    st.error(str(e))
                for v in versions:
                    test = json.loads(v.get("test_result") or "{}")
                    st.markdown(f"**v{v['version']}** · {str(v['created_at'])[:16]} · "
                                f"test {'réussi' if test.get('ok') else 'en échec'}"
                                + (f" · {v['note']}" if v.get("note") else ""))
                    if st.button("Restaurer dans l'éditeur", key=f"mt_rest_{t.tool_id}_{v['version']}"):
                        from backend.tool_registry import ToolSpec
                        load_draft(tb.draft_from_spec(ToolSpec.from_row(json.loads(v["spec"]))))
                        st.success("Version chargée dans « Créer avec l'IA » : testez puis enregistrez.")
