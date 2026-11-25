"""Team Builder (EIA Factory, étape 3) : découverte de la source -> proposition d'architecture -> déploiement.

La découverte réutilise celle du Transformation Center (plan existant ou nouveau périmètre). Chaque phase est
fermée par un contrôle AG08. Recette en mémoire ; seuls l'enregistrement du brouillon et la mise en service
écrivent, après confirmation, à votre nom.
"""
import pandas as pd
import streamlit as st

from backend import config as app_config
from backend import transformation as T
from backend.eia import store as es
from backend.eia import team_builder as tb
from backend.eia.adapters import SqlKpiSource
from ui import eia_ui as ui
from ui import state

st.title("Team Builder")
st.caption("La méta-équipe EIA Factory (AG01 découverte, AG10 architecture, AG09 déploiement, AG08 contrôles) "
           "projette une équipe d'agents sur vos données. KPI candidats et paramètres restent « à valider » ; aucun seuil "
           "n'est inventé. Rien n'est mis en service sans votre décision.")

try:
    w, sql, ident = state.user_session()
    me = ident.email
    repo = es.EiaRepository(es.SqlEiaStore(sql, state.settings().table))
except Exception as e:  # noqa: BLE001
    st.error(f"Identité utilisateur indisponible : {e}")
    st.stop()
ui.flash()
scope = app_config.data_scope()
K_DISC, K_OUT = "tb_discovery", "tb_out"


def _gates(gates: list) -> None:
    for g in gates:
        (st.success if g["reussi"] else st.error)(
            f"Contrôle AG08 · {g['phase']} : {'réussi' if g['reussi'] else 'échec'}")
        for b in g["bloquants"]:
            st.write(f"* Bloquant : {b}")
        for a in g["avertissements"]:
            st.write(f"* Avertissement : {a}")


def _run(upto: str, **kw) -> None:
    disc = st.session_state[K_DISC]
    with st.spinner("Exécution des agents et des contrôles…"):
        try:
            st.session_state[K_OUT] = tb.run(lambda: disc, SqlKpiSource(sql), upto=upto, data_scope=scope,
                                             owner=me, **kw)
        except tb.TeamBuilderError as e:
            st.error(str(e))


t1, t2, t3, t4 = st.tabs(["1. Découverte de la source", "2. Proposition d'architecture", "3. Déploiement",
                          "Équipes conçues"])

with t1:
    origin = st.radio("Source", ["Plan du Transformation Center", "Nouveau périmètre"], horizontal=True)
    if origin == "Plan du Transformation Center":
        with_disc = []
        try:
            svc = state.transformation_service()
            admin = state.team_repository().is_admin(me)
            with_disc = [p for p in (svc.get(x["plan_id"], me, admin) for x in svc.list_plans(me, admin))
                         if p.get("discovery")]
        except Exception as e:  # noqa: BLE001
            st.error(f"Lecture des plans impossible : {e}")
        if not with_disc:
            st.info("Aucun plan avec découverte. Lancez-la dans Transformation, ou choisissez un nouveau périmètre.")
        else:
            names = {p["plan_id"]: p["name"] for p in with_disc}
            pid = st.selectbox("Plan", list(names), format_func=names.get)
            plan = next(p for p in with_disc if p["plan_id"] == pid)
            st.caption(f"Découverte du {plan['discovery'].get('date')} : {plan['discovery'].get('perimetre')}")
            if st.button("Utiliser cette découverte", type="primary"):
                st.session_state[K_DISC] = plan["discovery"]
                _run("decouverte")
    else:
        cat = st.text_input("Catalogue", scope[0])
        sch = st.text_input("Schéma", scope[1])
        try:
            names_t = sorted(t.name for t in w.tables.list(catalog_name=cat, schema_name=sch))
        except Exception as e:  # noqa: BLE001
            st.error(f"Liste des tables impossible : {e}")
            names_t = []
        sel = st.multiselect(f"Tables ({T.MAX_TABLES} au maximum)", names_t)
        st.caption("Structure et statistiques agrégées lues avec vos droits, sans lire de lignes.")
        if st.button("Lancer la découverte", type="primary", disabled=not sel or len(sel) > T.MAX_TABLES):
            with st.spinner("Profil des tables…"):
                try:
                    st.session_state[K_DISC] = T.discover(
                        lambda c, s: list(w.tables.list(catalog_name=c, schema_name=s)), sql, cat, sch, prefix=None,
                        tables=sel)
                    _run("decouverte")
                except T.TransformationError as e:
                    st.error(str(e))
    out = st.session_state.get(K_OUT)
    if out:
        d = out["decouverte"]
        st.caption(f"{d['perimetre']} · {d['date']} · {d['avertissement']}")
        st.dataframe(pd.DataFrame(d["tables"]), hide_index=True, use_container_width=True)
        st.markdown("**KPI candidats (constats statistiques, à valider)**")
        st.dataframe(pd.DataFrame(out["kpi_candidats"]), hide_index=True, use_container_width=True)
        _gates(out["controles"][:1])

with t2:
    out = st.session_state.get(K_OUT)
    if not out or not out["controles"][0]["reussi"]:
        st.info("Terminez d'abord la découverte (contrôle AG08 réussi).")
    else:
        with st.form("tb_design"):
            team_id = st.text_input("Identifiant de l'équipe", placeholder="marketing_pilote")
            name = st.text_input("Nom de l'équipe", placeholder="Marketing (pilote)")
            obj_txt = st.text_area("Objectifs (un par ligne)", height=80)
            ids = [k["id"] for k in out["kpi_candidats"]]
            kpis = st.multiselect(f"KPI retenus ({tb.MAX_KPIS} au plus)", ids, default=ids[:tb.MAX_KPIS])
            if st.form_submit_button("Proposer l'architecture", type="primary"):
                params = dict(team_id=team_id.strip(), name=name.strip(), kpi_ids=kpis,
                              objectives=[x.strip() for x in obj_txt.splitlines() if x.strip()])
                st.session_state["tb_params"] = params
                _run("architecture", **params)
        out = st.session_state.get(K_OUT) or {}
        a = out.get("architecture")
        if a:
            st.markdown(f"**Modèle d'équipe** : {a['modele_equipe']} · modèles {' + '.join(a['modeles'])} · "
                        f"rôles {', '.join(a['roles'])}")
            for r in a["justification"]:
                st.write(f"* {r}")
            st.markdown("**À valider par le métier**")
            for r in a["a_valider"]:
                st.write(f"* {r}")
            with st.expander("Configuration générée"):
                st.json(a["config"])
            _gates(out["controles"][1:2])

with t3:
    out = st.session_state.get(K_OUT) or {}
    params = st.session_state.get("tb_params")
    ok_arch = len(out.get("controles") or []) > 1 and out["controles"][1]["reussi"]
    if not ok_arch or not params:
        st.info("Validez d'abord l'architecture (contrôle AG08 réussi).")
    else:
        if st.button("Lancer la recette (cycle complet en aperçu)", type="primary"):
            _run("deploiement", **params)
        out = st.session_state.get(K_OUT) or {}
        r = out.get("recette")
        if r:
            cols = st.columns(5)
            for col, (lab, key) in zip(cols, (("KPI exploitables", "kpi_exploitables"), ("Constats", "constats"),
                                              ("Prévisions fiables", "previsions_fiables"), ("Alertes", "alertes"),
                                              ("Requêtes KPI", "requetes_kpi"))):
                col.metric(lab, r.get(key))
            for adj in out["architecture"].get("ajustements") or []:
                st.warning(f"Ajustement AG09 : prévision retirée pour {', '.join(adj['previsions_retirees'])} ; "
                           f"prévisions retenues : {', '.join(adj['previsions']) or 'aucune'}")
            _gates(out["controles"][2:])
            row = tb.build(out["architecture"], out["controles"], r, me)
            ui.confirm_button("Enregistrer l'équipe en brouillon", "tb_save",
                              lambda: f"Brouillon enregistré : {repo.save_team_config(row)}", primary=True)

with t4:
    try:
        rows = repo.team_configs()
    except Exception as e:  # noqa: BLE001
        st.error(f"Lecture impossible : {e}")
        rows = []
    if not rows:
        st.info("Aucune équipe conçue pour l'instant.")
    for r in rows:
        with st.container(border=True):
            st.markdown(f"**{r['name']}** (`{r['team_id']}` v{r['version']}) · {r['status']} · {' + '.join(r['models'])}")
            st.caption(f"{r['config_id']} · créé par {r['created_by']} le {r['created_at']}"
                       + (f" · décidé par {r['decided_by']}" if r.get("decided_by") else ""))
            missing = tb.deployable(r)
            for m in missing:
                st.write(f"* {m}")
            if r["status"] == "brouillon":
                ui.confirm_button("Mettre en service", f"tb_on_{r['config_id']}", disabled=bool(missing),
                                  action=lambda r=r: repo.set_team_config_status(
                                      r["config_id"], "en_service", me, tb.deployable(r)) or "Équipe mise en service.")
            if r["status"] in ("brouillon", "en_service"):
                ui.confirm_button("Retirer", f"tb_off_{r['config_id']}",
                                  action=lambda r=r: repo.set_team_config_status(r["config_id"], "retiree", me)
                                  or "Équipe retirée.")
