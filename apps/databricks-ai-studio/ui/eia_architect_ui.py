"""Transformation Center : Enterprise Architect (AG10) et Engineering & Builder (AG09).

Onglets Data Mesh Architecture, EIA Architecture et Deployment, plus la lecture AG10 de l'onglet Data Discovery.
Toutes les étapes sont persistées (eia_architectures) ; chaque validation et le déploiement sont des décisions
humaines ; rien n'est créé sans confirmation.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from backend import teams as TM
from backend.eia import agent_models as am
from backend.eia import mesh_architect as ma
from backend.eia import org_designer as od
from backend.eia import store as es
from backend.eia import team_builder as tb
from backend.eia.contracts import ContractError
from ui import state
from ui.components import error_box

STATUS = {"brouillon": "Découpage en cours", "mesh_valide": "Data Mesh validé", "eia_valide": "EIA validée",
          "deployee": "Déployée (brouillons)", "retiree": "Retirée"}
ERRORS = (ma.MeshError, od.OrgError, ContractError)


def repo(sql) -> es.EiaRepository:
    return es.EiaRepository(es.SqlEiaStore(sql, state.settings().table))


def current(sql, plan_id: str) -> dict | None:
    try:
        return repo(sql).current_architecture(plan_id)
    except Exception:  # noqa: BLE001  (table absente : pas encore d'architecture)
        return None


def _do(label: str, fn, ok: str) -> None:
    try:
        fn()
        st.session_state["transfo_flash"] = ok
        st.rerun()
    except ERRORS as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        error_box(label, e)


def _cands(plan: dict) -> list[dict]:
    return tb.kpi_candidates(plan["discovery"]) if plan.get("discovery") else []


def _short(t: str) -> str:
    return ma._short(t)


# ---------------------------------------------------------------- 1. Data Discovery (lecture AG10)
def insights_section(plan: dict) -> None:
    if not plan.get("discovery"):
        return
    i = ma.insights(plan["discovery"], _cands(plan))
    with st.expander("Lecture de l'Enterprise Architect (AG10) : entités, processus, KPI, opportunités", expanded=False):
        st.caption(i["avertissement"] + " Ces résultats alimentent l'onglet Data Mesh Architecture.")
        m = st.columns(5)
        m[0].metric("Entités", len(i["entites"]))
        m[1].metric("Processus", len(i["processus"]))
        m[2].metric("KPI candidats", i["kpis"])
        m[3].metric("Opportunités IA", len(i["opportunites_ia"]))
        m[4].metric("Automatisation", len(i["opportunites_automatisation"]))
        st.dataframe(pd.DataFrame([{"Table": _short(e["table"]), "Entité": e["entite"], "Nature": e["nature"],
                                    "Références entrantes": e["references_entrantes"]} for e in i["entites"]]),
                     hide_index=True, use_container_width=True)
        if i["processus"]:
            st.markdown("**Processus métier** (cycle de vie déduit d'un statut daté)")
            st.dataframe(pd.DataFrame([{"Processus": p["processus"], "Statut": ", ".join(p["etapes"]),
                                        "Dates": ", ".join(p["dates"])} for p in i["processus"]]),
                         hide_index=True, use_container_width=True)
        opp = i["opportunites_ia"] + i["opportunites_automatisation"]
        if opp:
            st.markdown("**Opportunités d'IA et d'automatisation** (à valider)")
            st.dataframe(pd.DataFrame([{"Type": o["type"], "Opportunité": o["opportunite"], "Table": _short(o["table"]),
                                        "Statut": o["statut"]} for o in opp]), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- 2. Data Mesh Architecture
def mesh_tab(plan: dict, me: str, owner: bool, sql) -> None:
    st.subheader("Data Mesh Architecture")
    st.caption("L'Enterprise Architect (AG10, Data Mesh Architect) identifie les domaines métier en nombre optimal, "
               "leurs sous-domaines, data products et dépendances. Aucun nombre de domaines n'est imposé ; un seul "
               "domaine s'il suffit. Vous modifiez puis validez le découpage.")
    if not plan.get("discovery"):
        st.info("Lancez d'abord la découverte (onglet Data Discovery).")
        return
    d, c, pid = plan["discovery"], _cands(plan), plan["plan_id"]
    arch = current(sql, pid)
    if arch is None:
        ent = st.text_input("Nom de l'entreprise", plan["name"][:60], key=f"ea_ent_{pid}", disabled=not owner)
        if owner and st.button("Proposer le découpage Data Mesh (AG10)", type="primary"):
            _do("Proposition impossible", lambda: repo(sql).save_architecture(
                pid, ent, ma.propose_mesh(d, c, ent or "Entreprise"), me), "Découpage Data Mesh proposé et enregistré.")
        return
    mesh, status, aid = arch["mesh"], arch["status"], arch["arch_id"]
    editable = owner and status == "brouillon"
    st.markdown(f"**Architecture** : {arch['name']} · statut **{STATUS.get(status, status)}** · "
                f"mise à jour {str(arch.get('updated_at') or '')[:16]} par {arch.get('updated_by') or ''}")
    n_sub = sum(len(x["sous_domaines"]) for x in mesh["domaines"])
    m = st.columns(4)
    m[0].metric("Domaines", len(mesh["domaines"]))
    m[1].metric("Sous-domaines", n_sub)
    m[2].metric("Data products", sum(len(x["data_products"]) for x in mesh["domaines"]))
    m[3].metric("Dépendances", len(mesh["dependances"]))
    with st.expander("Justification des choix d'architecture", expanded=True):
        st.markdown("\n".join(f"* {j}" for j in mesh["justification"]))
        st.caption(mesh.get("avertissement", ""))
    names = {x["cle"]: x["nom"] for x in mesh["domaines"]}
    view = st.selectbox("Vue", ["global"] + list(names), format_func=lambda k: "Entreprise (tous les domaines)"
                        if k == "global" else f"Domaine {names[k]}", key=f"ea_mview_{aid}")
    st.graphviz_chart(ma.mesh_dot(mesh, None if view == "global" else view), use_container_width=True)
    for x in mesh["domaines"]:
        if view not in ("global", x["cle"]):
            continue
        with st.expander(f"Domaine {x['nom']} : {len(x['tables'])} table(s), {len(x['kpis'])} KPI",
                         expanded=view != "global"):
            st.markdown(f"**Responsabilités** : {x['responsabilites']}  \n**Propriétaire** : {x['proprietaire']}")
            st.dataframe(pd.DataFrame([{"Data product": p["nom"], "Type": p["type"], "Tables": ", ".join(
                _short(t) for t in p["tables"]), "KPI": len(p["kpis"]), "Consommé par": ", ".join(
                names.get(k, k) for k in p["consommateurs"])} for p in x["data_products"]]),
                hide_index=True, use_container_width=True)
            deps = [y for y in mesh["dependances"] if x["cle"] in (y["de"], y["vers"])]
            if deps:
                st.markdown("\n".join(f"* {names.get(y['de'])} dépend du data product `{y['data_product']}` de "
                                      f"{names.get(y['vers'])} ({y['liens']} lien(s))" for y in deps))
    if editable:
        st.markdown("**Modifier le découpage**")
        c1, c2, c3 = st.columns(3)
        with c1.form(f"ea_move_{aid}"):
            tabs = list(mesh["affectation"])
            t = st.selectbox("Table", tabs, format_func=_short)
            dest = st.selectbox("Vers le domaine", list(names) + ["__new__"],
                                format_func=lambda k: "Nouveau domaine" if k == "__new__" else names[k])
            new = st.text_input("Nom du nouveau domaine")
            if st.form_submit_button("Déplacer"):
                _do("Modification impossible", lambda: repo(sql).update_architecture(aid, "mesh", ma.move_table(
                    mesh, d, c, t, new if dest == "__new__" else dest), me), "Table déplacée.")
        with c2.form(f"ea_ren_{aid}"):
            k = st.selectbox("Domaine", list(names), format_func=names.get)
            nm = st.text_input("Nouveau nom")
            if st.form_submit_button("Renommer"):
                _do("Modification impossible", lambda: repo(sql).update_architecture(
                    aid, "mesh", ma.rename_domain(mesh, d, c, k, nm), me), "Domaine renommé.")
        with c3.form(f"ea_merge_{aid}"):
            keep = st.selectbox("Conserver", list(names), format_func=names.get)
            absorb = st.selectbox("Absorber", list(names), format_func=names.get, index=min(1, len(names) - 1))
            if st.form_submit_button("Fusionner", disabled=len(names) < 2):
                _do("Modification impossible", lambda: repo(sql).update_architecture(
                    aid, "mesh", ma.merge_domains(mesh, d, c, keep, absorb), me), "Domaines fusionnés.")
        b1, b2 = st.columns(2)
        if b1.button("Valider le découpage Data Mesh", type="primary", use_container_width=True):
            _do("Validation impossible", lambda: repo(sql).set_architecture_status(aid, "mesh_valide", me),
                "Découpage Data Mesh validé : passez à l'onglet EIA Architecture.")
        if b2.button("Recalculer la proposition AG10", use_container_width=True,
                     help="Remplace le découpage par une nouvelle proposition (après une nouvelle découverte)"):
            _do("Proposition impossible", lambda: repo(sql).update_architecture(
                aid, "mesh", ma.propose_mesh(d, c, mesh["entreprise"]), me), "Nouvelle proposition enregistrée.")
    elif owner and status == "mesh_valide":
        if st.button("Rouvrir le découpage pour le modifier"):
            _do("Réouverture impossible", lambda: repo(sql).set_architecture_status(aid, "brouillon", me),
                "Découpage rouvert.")
    elif status in ("eia_valide", "deployee"):
        st.caption("Découpage figé : l'EIA a été validée" + (" et déployée." if status == "deployee" else
                                                            " (rouvrez-la dans l'onglet EIA Architecture)."))


# ---------------------------------------------------------------- 3. EIA Architecture
def _agents_table(eia: dict, keys) -> pd.DataFrame:
    names = {v["domaine"]: v["nom"] for v in eia["domaines"]}
    return pd.DataFrame([{"Agent": a["nom"], "Catégorie": f"{a['categorie']} {a['categorie_nom']}",
                          "Appel": "@" + (a["reutilise"]["handle"] if a.get("reutilise") else a["handle"]),
                          "Domaines": ", ".join(names.get(k, k) for k in a["domaines"]),
                          "Mutualisé": "oui" if a.get("mutualise") else "", "Réutilisé": "oui" if a.get("reutilise") else "",
                          "Modèle": a["statut_modele"], "Autonomie": a["autonomie"], "Justification": a["justification"]}
                         for k, a in eia["agents"].items() if k in keys])


def eia_tab(plan: dict, me: str, owner: bool, sql) -> None:
    st.subheader("EIA Architecture")
    st.caption("L'Enterprise Architect (AG10, Agent Mesh Architect) conçoit une EIA par domaine validé (cycle "
               "CAPTER → COMPRENDRE → PRÉDIRE → ARBITRER → DÉCIDER (humain) → EXÉCUTER → APPRENDRE), puis optimise "
               "l'organisation globale sous HAKIM : capacités transverses mutualisées, réutilisation des agents publiés.")
    arch = current(sql, plan["plan_id"]) if plan.get("discovery") else None
    if not arch or arch["status"] == "brouillon":
        st.info("Validez d'abord le découpage (onglet Data Mesh Architecture).")
        return
    aid, status, eia = arch["arch_id"], arch["status"], arch["eia"]
    if owner and status == "mesh_valide":
        with st.form(f"ea_design_{aid}"):
            c1, c2 = st.columns(2)
            fil = c1.selectbox("Filière des équipes", list(TM.FILIERES),
                               index=list(TM.FILIERES).index(eia.get("filiere", "Transverse"))
                               if eia.get("filiere") in TM.FILIERES else 0)
            mut = c2.multiselect("Capacités à mutualiser entre domaines", list(ma.SHAREABLE),
                                 default=eia.get("mutualisation", list(ma.SHAREABLE)),
                                 format_func=lambda x: f"{x} {am.CATEGORIES[x]['nom']}")
            reuse = st.checkbox("Réutiliser les agents publiés de même catégorie couvrant les mêmes tables", True)
            if st.form_submit_button("Concevoir et optimiser l'EIA (AG10)", type="primary"):
                def _design():
                    taken = [a.get("handle") for a in state.agents()] + [t.get("handle") for t in state.teams()]
                    repo(sql).update_architecture(aid, "eia", ma.design_eia(
                        arch["mesh"], mutualiser=mut, filiere=fil, owner=me, taken=taken, existing=state.agents(),
                        reuse=reuse), me)
                _do("Conception impossible", _design, "Architecture EIA conçue et optimisée.")
    if not eia.get("agents"):
        st.info("Aucune architecture EIA : lancez la conception.")
        return
    o = eia["optimisation"]
    m = st.columns(5)
    m[0].metric("Équipes (chefs)", o["chefs"])
    m[1].metric("Agents", o["agents_optimises"], delta=-o["economie_agents"] if o["economie_agents"] else None,
                delta_color="inverse", help=f"Sans optimisation : {o['agents_sans_optimisation']}")
    m[2].metric("Mutualisés", len(o["mutualises"]))
    m[3].metric("Réutilisés", len(o["reutilises"]))
    m[4].metric("Composants à créer", o["a_creer"])
    st.caption(" ".join(o["notes"]))
    teams = {e["cle"]: e for e in eia["equipes"]}
    dnames = {v["domaine"]: v["nom"] for v in eia["domaines"]}
    opts = ["global"] + list(dnames) + list(teams) + ["__agent__"]
    view = st.selectbox("Navigation", opts, key=f"ea_eview_{aid}", format_func=lambda k: (
        "Entreprise intelligente (vue globale)" if k == "global" else "Fiche d'un agent" if k == "__agent__" else
        f"Domaine {dnames[k]}" if k in dnames else f"Équipe {teams[k]['nom']}"))
    sts = ma.statuses(eia, (arch["deployment"] or {}).get("selection"), arch["deployment"] or None) \
        if arch.get("deployment") else None
    if view == "__agent__":
        k = st.selectbox("Agent", list(eia["agents"]), format_func=lambda x: eia["agents"][x]["nom"],
                         key=f"ea_agent_{aid}")
        a = eia["agents"][k]
        st.markdown(f"**{a['nom']}** · {a['categorie']} {a['categorie_nom']} · @{a['handle']} · modèle "
                    f"{a['statut_modele']}" + (" · mutualisé" if a.get("mutualise") else ""))
        st.markdown(f"* **Mission** : {a['mission']}\n* **Autonomie** : {a['autonomie']}\n* **Justification** : "
                    f"{a['justification']}\n* **Outils** : {', '.join(a['outils']) or 'aucun'}\n* **Données** : "
                    f"{', '.join(_short(t) for t in a['tables'])}\n* **Équipes** : "
                    f"{', '.join(teams[e]['nom'] for e in a['equipes'])}")
        if a.get("reutilise"):
            st.info(f"Agent publié réutilisé : @{a['reutilise']['handle']} (non recréé).")
        with st.expander("Instructions générées"):
            st.code(od.instructions(a, eia), language="markdown")
    else:
        st.graphviz_chart(ma.eia_dot(eia, view, sts), use_container_width=True)
        keys = {k for e in eia["equipes"] if view in ("global", e["domaine"], e["cle"]) for k in e["membres"]}
        st.dataframe(_agents_table(eia, keys), hide_index=True, use_container_width=True)
        for v in eia["domaines"]:
            if view in ("global", v["domaine"], v["equipe"]):
                with st.expander(f"Cycle d'intelligence et flux : {v['nom']}", expanded=view != "global"):
                    st.dataframe(pd.DataFrame([{"Étape": s["etape"], "Porteur": eia["agents"][s["porteur"]]["nom"]
                                                if s["porteur"] in eia["agents"] else (s["porteur"] or "—"),
                                                "Couvert": "oui" if s["couvert"] else "non", "Motif": s["motif"]}
                                               for s in v["cycle"]]), hide_index=True, use_container_width=True)
                    nm = lambda x: eia["agents"][x]["nom"] if x in eia["agents"] else "Humain"  # noqa: E731
                    st.markdown("\n".join(f"* {nm(f['de'])} → {nm(f['vers'])} : {f['objet']}" for f in v["flux"]))
    with st.expander("Optimisation globale : capacités et décisions"):
        st.dataframe(pd.DataFrame([{"Capacité": x["capacite"], "Catégorie": x["categorie"], "Décision": x["decision"],
                                    "Justification": x["justification"]} for x in o["capacites"]]),
                     hide_index=True, use_container_width=True)
        if eia.get("interactions"):
            st.markdown("**Collaboration entre domaines**")
            st.markdown("\n".join(f"* {teams[x['de']]['nom']} dépend de {teams[x['vers']]['nom']} ({x['objet']})"
                                  for x in eia["interactions"]))
    with st.expander("Points de validation humaine et avertissements"):
        st.markdown("\n".join(f"* {v}" for v in eia["validations_humaines"] + eia["avertissements"]))
    if owner and status == "mesh_valide":
        c1, c2 = st.columns(2)
        if c1.button("Valider l'architecture EIA", type="primary", use_container_width=True):
            _do("Validation impossible", lambda: repo(sql).set_architecture_status(aid, "eia_valide", me),
                "Architecture EIA validée : passez à l'onglet Deployment.")
        if c2.button("Rouvrir le découpage Data Mesh", use_container_width=True):
            _do("Réouverture impossible", lambda: repo(sql).set_architecture_status(aid, "brouillon", me),
                "Découpage rouvert.")
    elif owner and status == "eia_valide" and st.button("Rouvrir l'architecture EIA pour la modifier"):
        _do("Réouverture impossible", lambda: repo(sql).set_architecture_status(aid, "mesh_valide", me),
            "Architecture EIA rouverte.")
    st.divider()


# ---------------------------------------------------------------- 4. Deployment
def deploy_tab(plan: dict, me: str, owner: bool, sql) -> None:
    st.subheader("Deployment")
    st.caption("L'Engineering & Builder Agent (AG09) construit, configure et déploie l'organisation validée : agents "
               "(outils, actions, données), chefs et équipes, en brouillon, après votre confirmation. Les interactions "
               "sont contrôlées ; la publication reste réservée à un administrateur.")
    arch = current(sql, plan["plan_id"]) if plan.get("discovery") else None
    if not arch or arch["status"] not in ("eia_valide", "deployee"):
        st.info("Validez d'abord l'architecture EIA (onglet EIA Architecture).")
        return
    aid, eia, dep = arch["arch_id"], arch["eia"], arch["deployment"] or {}
    dnames = {v["domaine"]: v["nom"] for v in eia["domaines"]}
    st.markdown("**Architecture finale** : " + ", ".join(
        f"{dnames[e['domaine']]} ({len(e['membres'])} agents, chef @{e['chef_handle']})" for e in eia["equipes"]))
    deployable = [k for k, a in eia["agents"].items() if a["deployable"]]
    if arch["status"] == "eia_valide" and owner:
        sel = st.multiselect("Agents à construire et déployer", deployable, default=dep.get("selection") or deployable,
                             format_func=lambda k: f"{eia['agents'][k]['nom']} (@{eia['agents'][k]['handle']})",
                             key=f"ea_sel_{aid}")
    else:
        sel = dep.get("selection") or deployable
    st.graphviz_chart(ma.eia_dot(eia, "global", ma.statuses(eia, sel, dep if dep.get("agents") else None)),
                      use_container_width=True)
    todo = [e for e in eia["equipes"] if any(k in sel for k in e["membres"])]
    st.dataframe(pd.DataFrame(
        [{"Composant": a["nom"], "Type": "agent", "Appel": "@" + a["handle"],
          "Action AG09": "réutiliser" if a.get("reutilise") else "créer (brouillon)",
          "Outils": ", ".join(a["outils"]), "Données": len(a["tables"])} for k, a in eia["agents"].items() if k in sel]
        + [{"Composant": e["nom"], "Type": "équipe + chef", "Appel": f"@{e['handle']} / @{e['chef_handle']}",
            "Action AG09": "créer (brouillon)", "Outils": "délégation aux membres", "Données": 0} for e in todo]),
        hide_index=True, use_container_width=True)
    if arch["status"] == "eia_valide" and owner:
        key = f"ea_confirm_{aid}"
        if not st.session_state.get(key):
            if st.button(f"Construire et déployer {len(sel)} agent(s) et {len(todo)} équipe(s) (AG09)", type="primary",
                         disabled=not sel):
                st.session_state[key] = True
                st.rerun()
        else:
            st.warning("Confirmez : AG09 crée les agents, chefs et équipes en brouillon, à votre nom.")
            c1, c2 = st.columns(2)
            if c2.button("Annuler", use_container_width=True):
                st.session_state.pop(key, None)
                st.rerun()
            if c1.button("Confirmer le déploiement", type="primary", use_container_width=True):
                st.session_state.pop(key, None)

                def _deploy():
                    r = repo(sql)
                    res = od.deploy(eia, sel, state.repository(), state.team_repository(), me)
                    state.refresh_data()
                    checks = ma.verify(eia, res, state.agents(force=True) if _force_ok() else state.agents(),
                                       state.teams(force=True))
                    r.update_architecture(aid, "deployment", {**res, "selection": list(sel), "controles": checks}, me)
                    if res["statut"] == "brouillon":
                        r.set_architecture_status(aid, "deployee", me)
                    else:
                        raise od.OrgError(f"Échec partiel : {res.get('erreur')}. {res.get('suite')}")
                _do("Déploiement impossible", _deploy, "Organisation déployée en brouillon ; contrôles enregistrés.")
    if dep.get("agents") or dep.get("equipes"):
        st.markdown(f"**Résultat du déploiement** : {dep.get('statut')}" + (f" — {dep['erreur']}" if dep.get("erreur") else ""))
        st.dataframe(pd.DataFrame([{"Composant": x["nom"], "Appel": "@" + x["handle"], "Identifiant": x["agent_id"],
                                    "Réutilisé": "oui" if x.get("reutilise") else ""} for x in dep.get("agents") or []]),
                     hide_index=True, use_container_width=True)
        checks = dep.get("controles") or []
        if checks:
            ok = sum(1 for x in checks if x["ok"])
            (st.success if ok == len(checks) else st.error)(f"Interactions contrôlées : {ok} / {len(checks)} réussies.")
            st.dataframe(pd.DataFrame([{"Contrôle": x["controle"], "Résultat": "OK" if x["ok"] else "Échec",
                                        "Détail": x["detail"]} for x in checks]), hide_index=True, use_container_width=True)
        st.caption((dep.get("suite") or "") + " Une fois publiées, HAKIM sollicite les équipes et agents par leur "
                   "nom d'appel (@).")
    if owner and arch["status"] in ("eia_valide", "deployee"):
        with st.popover("Retirer cette architecture"):
            st.caption("L'architecture passe au statut retiré ; les agents et équipes déjà créés restent à archiver depuis "
                       "Mes agents / Équipes. Une nouvelle architecture pourra être proposée.")
            if st.button("Confirmer le retrait", key=f"ea_retire_{aid}"):
                _do("Retrait impossible", lambda: repo(sql).set_architecture_status(aid, "retiree", me),
                    "Architecture retirée.")
    st.divider()


def _force_ok() -> bool:
    """state.agents accepte-t-il force= ? (relecture sans cache après création)."""
    import inspect
    return "force" in inspect.signature(state.agents).parameters
