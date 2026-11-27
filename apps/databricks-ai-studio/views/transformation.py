"""Transformation : plan guidé par HakimAI (étapes 1 à 7). L'utilisateur décide ici."""
import pandas as pd
import streamlit as st

from backend import transformation as T
from backend.eia import mesh_architect as MA
from ui import eia_architect_ui as EA
from ui import state
from ui.components import error_box

ST_LABEL = {"fait": "Fait", "en_cours": "En cours", "a_faire": "À faire", "lot_b2": "Lot B2"}
ITEM_STATUS = {"propose": "Proposé", "valide": "Validé", "rejete": "Rejeté"}

st.title("Transformation")
st.caption("EIA Transformation Center : du patrimoine de données à l'architecture cible de l'Entreprise Intelligente "
           "Augmentée. HakimAI propose, vous décidez ici. La découverte lit la structure et des statistiques agrégées "
           "du périmètre choisi, avec vos droits, sans lire de lignes. Rien n'est créé sans votre validation.")


@st.cache_data(ttl=300, show_spinner=False)
def _catalogs(_w, user: str) -> dict:
    """Catalogues visibles par l'utilisateur, avec leur nature (fédéré = connexion externe Unity Catalog)."""
    out = {}
    for c in _w.catalogs.list():
        kind = getattr(getattr(c, "catalog_type", None), "value", "") or ""
        conn = getattr(c, "connection_name", None)
        out[c.name] = {"FOREIGN_CATALOG": "fédéré" + (f" : {conn}" if conn else ""),
                       "DELTASHARING_CATALOG": "Delta Sharing", "SYSTEM_CATALOG": "système"}.get(kind, "")
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _schemas(_w, user: str, catalog: str) -> list:
    return sorted(s.name for s in _w.schemas.list(catalog_name=catalog) if s.name != "information_schema")


@st.cache_data(ttl=300, show_spinner=False)
def _tables(_w, user: str, catalog: str, schema: str) -> list:
    return sorted(((t.name, t.comment or "") for t in _w.tables.list(catalog_name=catalog, schema_name=schema)),
                  key=lambda x: x[0])

try:
    w, sql, ident = state.user_session()
    me = ident.email
    admin = state.team_repository().is_admin(me)
    svc = state.transformation_service()
    plans = svc.list_plans(me, admin)
except Exception as e:  # noqa: BLE001
    error_box("Lecture des plans impossible", e)
    st.stop()


def act(label: str, fn, ok: str):
    try:
        fn()
        st.session_state["transfo_flash"] = ok
        st.rerun()
    except T.TransformationError as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        error_box(label, e)


if msg := st.session_state.pop("transfo_flash", None):
    st.success(msg)

c1, c2 = st.columns([3, 2])
with c2.popover("Nouveau plan", use_container_width=True):
    with st.form("transfo_new", clear_on_submit=True):
        name = st.text_input("Nom du plan", placeholder="Transformation IA - Gares et Connexions")
        if st.form_submit_button("Créer", type="primary"):
            def _create():
                st.session_state["transfo_plan"] = svc.create(name, me)["plan_id"]
            act("Création impossible", _create, "Plan créé.")

if not plans:
    st.info("Aucun plan. Créez-en un, ou demandez à HakimAI : « Guide-moi pour transformer mon activité avec l'IA ».")
    if st.button("Ouvrir HakimAI", type="primary"):
        st.switch_page("views/hakim.py")
    st.stop()

ids = [p["plan_id"] for p in plans]
if st.session_state.get("transfo_plan") not in ids:
    st.session_state["transfo_plan"] = ids[0]
labels = {p["plan_id"]: p["name"] + ("" if p["owner"] == me else f" ({p['owner']})") for p in plans}
plan_id = c1.selectbox("Plan", ids, format_func=labels.get, key="transfo_plan")

try:
    plan = svc.get(plan_id, me, admin)
    items = svc.items(plan_id, me, admin)
except Exception as e:  # noqa: BLE001
    error_box("Lecture du plan impossible", e)
    st.stop()
owner = plan["owner"] == me
if not owner:
    st.info(f"Plan de {plan['owner']} : consultation seule (seul le propriétaire le modifie et décide).")

catalog = T.platform_catalog(state.agents(), state.repository().list_tools(), state.teams())
steps = svc.progress(plan, items, catalog)
tracking = svc.tracking(items, catalog)
arch = EA.current(sql, plan_id)
stages = MA.stages(plan, arch)
for col, (n, ph) in zip(st.columns(len(stages)), enumerate(stages, 1)):
    col.metric(f"{n} · {ph['libelle']}", ST_LABEL[ph["statut"]])
st.caption("Démarche : Data Discovery → Data Mesh Architecture → EIA Architecture → Deployment. L'Enterprise "
           "Architect (AG10) conçoit, l'Engineering & Builder (AG09) déploie, HAKIM supervise, vous validez.")
pending = sum(1 for i in items if i["status"] == "propose")
st.info("**Prochaine action** : " + T.next_action(steps)
        + (f" — {pending} élément(s) en attente de votre décision." if pending else ""))
for warning in svc.coherence(items):
    st.warning(warning)
b1, b2 = st.columns(2)
if b1.button("Continuer avec HakimAI", type="primary", use_container_width=True):
    st.switch_page("views/hakim.py")
if b2.button("Générer une équipe EIA (Team Builder)", use_container_width=True, disabled=not plan.get("discovery"),
             help="Réutilise la découverte de ce plan : architecture d'équipe, contrôles AG08 et recette"):
    st.switch_page("views/team_builder.py")

t_disc, t_mesh, t_eia, t_dep = st.tabs([f"{n} · {s['libelle']}" for n, s in enumerate(stages, 1)])
t1 = t2 = t3 = t4 = t_disc          # cadrage, découverte, domaines et objectifs, AI Opportunities
t5 = t_gap = t_eia                  # cible TO-BE et écarts, après l'architecture EIA
t6 = t7 = t_dep                     # feuille de route et suivi, après le déploiement
with t_disc:
    EA.insights_section(plan)
with t_mesh:
    EA.mesh_tab(plan, me, owner, sql)
with t_eia:
    EA.eia_tab(plan, me, owner, sql)
with t_dep:
    EA.deploy_tab(plan, me, owner, sql)

with t1:
    st.subheader("Cadrage")
    ctx = plan["context"]
    with st.form("transfo_ctx"):
        values = {k: st.text_area(label, ctx.get(k, ""), height=80, disabled=not owner)
                  for k, label in T.CONTEXT_FIELDS.items()}
        if st.form_submit_button("Enregistrer le cadrage", disabled=not owner):
            act("Enregistrement impossible", lambda: svc.set_context(plan_id, me, values), "Cadrage enregistré.")

with t2:
    st.subheader("Découverte des données")
    d = plan["discovery"]
    s = state.settings()
    per = T.perimeter_args(plan["context"], s.catalog, s.schema)
    st.markdown("**Périmètre de données**")
    if not owner:
        st.caption(f"Périmètre : {per['catalog']}.{per['schema']}"
                   + (f", {len(per['tables'])} table(s)" if per["tables"] else f", tables {per['prefix']}*"))
    else:
        try:
            cats = _catalogs(w, me)
        except Exception as e:  # noqa: BLE001
            error_box("Liste des catalogues impossible", e)
            cats = {}
        names_c = sorted(set(cats) | {per["catalog"]})
        cat = st.selectbox("Source de données (catalogue Unity Catalog, y compris catalogues fédérés)", names_c,
                           index=names_c.index(per["catalog"]),
                           format_func=lambda c: f"{c} ({cats[c]})" if cats.get(c) else c, key=f"eia_cat_{plan_id}")
        try:
            schemas = _schemas(w, me, cat)
        except Exception as e:  # noqa: BLE001
            error_box("Liste des schémas impossible", e)
            schemas = []
        sch = None
        if schemas:
            sch = st.selectbox("Schéma", schemas, index=schemas.index(per["schema"]) if per["schema"] in schemas else 0,
                               key=f"eia_sch_{plan_id}_{cat}")
        else:
            st.info("Aucun schéma visible dans ce catalogue avec vos droits.")
        tables_uc = []
        if sch:
            try:
                tables_uc = _tables(w, me, cat, sch)
            except Exception as e:  # noqa: BLE001
                error_box("Liste des tables impossible", e)
        names_t = [n for n, _ in tables_uc]
        comments = dict(tables_uc)
        default = []
        if (cat, sch) == (per["catalog"], per["schema"]):
            default = per["tables"] or [n for n in names_t if per["prefix"] and n.startswith(per["prefix"])]
        default = [n for n in default if n in names_t][:T.MAX_TABLES]
        sel = st.multiselect(f"Tables à analyser ({T.MAX_TABLES} au maximum)", names_t, default=default,
                             format_func=lambda n: f"{n} — {comments[n][:60]}" if comments.get(n) else n,
                             key=f"eia_tab_{plan_id}_{cat}_{sch}")
        st.caption("Structure et statistiques agrégées lues avec vos droits, sans lire de lignes : 1 à 3 requêtes par "
                   "table sur l'entrepôt SQL, plus la lecture des étiquettes Unity Catalog du schéma.")
        if st.button("Relancer la découverte" if d else "Lancer la découverte", type="primary",
                     disabled=not sel or len(sel) > T.MAX_TABLES):
            def _run():
                svc.set_perimeter(plan_id, me, cat, sch, sel)
                svc.set_discovery(plan_id, me, T.discover(
                    lambda c, sc: list(w.tables.list(catalog_name=c, schema_name=sc)), sql, cat, sch, prefix=None,
                    tables=sel,
                    tags=lambda c, sc: (sql.query(T.column_tags_query(c), {"schema": sc}) or {}).get("rows", [])))
            with st.spinner("Lecture de la structure et calcul des statistiques..."):
                act("Découverte impossible", _run, "Périmètre et découverte enregistrés.")
    if not d:
        st.info("Pas encore de découverte.")
    else:
        st.caption(f"{d['perimetre']} — {d['date']}. {d['avertissement']}")
        if d.get("avertissement_etiquettes"):
            st.caption(d["avertissement_etiquettes"])
        syn = T.asis_summary(d, items)
        m = st.columns(5)
        m[0].metric("Tables analysées", syn["tables"])
        m[1].metric("Lignes", f"{syn['lignes']:,}".replace(",", " "))
        m[2].metric("Colonnes sans description", f"{syn['colonnes_sans_description']} / {syn['colonnes']}")
        m[3].metric("Liens probables", syn["liens"])
        m[4].metric("Colonnes sensibles (à confirmer)", syn["colonnes_sensibles"])
        st.markdown("**Synthèse de l'existant (AS-IS)**")
        asis = [f"{syn['tables']} table(s) analysée(s)" + (f", {syn['tables_en_erreur']} en erreur" if syn["tables_en_erreur"]
                                                         else "") + f", {syn['colonnes']} colonnes.",
                f"Documentation : {syn['tables_sans_description']} table(s) et {syn['colonnes_sans_description']} "
                "colonne(s) sans description.",
                f"Clés et relations : {syn['tables_avec_cle']} table(s) avec une clé candidate confirmée ; {syn['liens']} "
                f"lien(s) probable(s), dont {syn['liens_incomplets']} avec des valeurs sans correspondance.",
                f"Domaines métier : {syn['domaines_valides']} validé(s), {syn['domaines_proposes']} proposé(s) ; objectifs : "
                f"{syn['objectifs_valides']} validé(s), {syn['objectifs_proposes']} proposé(s)."]
        st.markdown("\n".join(f"* {x}" for x in asis))
        st.markdown("**Cartographie du patrimoine**")
        st.caption("Tables et liens probables. Trait plein : 100 % des valeurs retrouvées ; pointillé : correspondance "
                   "partielle ou non mesurée ; fond orangé : colonnes potentiellement sensibles.")
        st.graphviz_chart(T.heritage_dot(d), use_container_width=True)
        ok = [t for t in d["tables"] if "erreur" not in t]
        st.dataframe(pd.DataFrame([{"Table": t["table"], "Lignes": t["lignes"], "Colonnes": len(t["colonnes"]),
                                    "Clés candidates": ", ".join(c["nom"] for c in t["colonnes"] if c["cle_candidate"]),
                                    "Description": t["commentaire"]} for t in ok]),
                     hide_index=True, use_container_width=True)
        for t in d["tables"]:
            if "erreur" in t:
                st.error(f"{t['table']} : {t['erreur']}")
        for t in ok:
            with st.expander(f"Colonnes de {t['table']}"):
                st.dataframe(pd.DataFrame([{"Colonne": c["nom"], "Type": c["type"], "Rempli (%)": c["remplissage_pct"],
                                            "Distinctes (approx.)": c["valeurs_distinctes"], "Min": c.get("min"),
                                            "Max": c.get("max"), "Description": c["commentaire"]}
                                           for c in t["colonnes"]]), hide_index=True, use_container_width=True)
        st.markdown("**Liens probables** (à vérifier)")
        if d["liens_probables"]:
            st.dataframe(pd.DataFrame(d["liens_probables"]), hide_index=True, use_container_width=True)
        else:
            st.caption("Aucun lien détecté par les noms de colonnes.")
        st.markdown("**Constats statistiques**")
        st.markdown("\n".join(f"* {c}" for c in d["constats"]) or "Aucun.")
        st.markdown("**Données potentiellement sensibles** (indices à confirmer par le responsable des données)")
        sens = d.get("donnees_sensibles") or []
        if sens:
            st.dataframe(pd.DataFrame([{"Table": x["table"].split(".")[-1], "Colonne": x["colonne"],
                                        "Catégorie": x["categorie"], "Source": x["source"], "Statut": x["statut"]}
                                       for x in sens]), hide_index=True, use_container_width=True)
        else:
            st.caption("Aucun indice, ni par le nom des colonnes ni par les étiquettes Unity Catalog.")
        st.markdown("**Informations métier**")
        st.caption("Complétez ce que les descriptions techniques ne disent pas : rôle de la table, responsable, usage.")
        notes = plan["context"].get("_notes_metier") or {}
        edited = st.data_editor(
            pd.DataFrame([{"Table": t["table"], "Description Unity Catalog": t["commentaire"],
                           "Information métier": notes.get(t["table"], "")} for t in ok]),
            hide_index=True, use_container_width=True, key=f"eia_notes_{plan_id}",
            disabled=["Table", "Description Unity Catalog"] if owner else True)
        if owner and st.button("Enregistrer les informations métier"):
            act("Enregistrement impossible", lambda: svc.set_business_notes(
                plan_id, me, dict(zip(edited["Table"], edited["Information métier"].fillna("")))),
                "Informations métier enregistrées.")

def render_items(kinds, empty: str) -> None:
    """Éléments d'une étape, avec leurs preuves, rattachements et décisions."""
    if not any(i["item_type"] in kinds for i in items):
        st.info(empty)
    for kind in kinds:
        group = [i for i in items if i["item_type"] == kind]
        if not group:
            continue
        h, btn = st.columns([4, 1])
        h.markdown(f"**{T.ITEM_PLURALS[kind] if len(group) > 1 else T.ITEM_LABELS[kind]}** ({len(group)})")
        todo = [i["item_id"] for i in group if i["status"] == "propose"]
        if owner and len(todo) > 1 and btn.button(f"Tout valider ({len(todo)})", key=f"all_{kind}"):
            act("Décision impossible", lambda todo=todo: svc.decide_many(plan_id, me, todo, "valide"),
                f"{len(todo)} élément(s) validé(s).")
        for i in group:
            with st.container(border=True):
                a, b = st.columns([4, 1])
                a.markdown(f"**{i['name']}**" + (f" — domaine : {i['payload']['domaine']}"
                                                 if i["payload"].get("domaine") else ""))
                b.markdown(f"`{ITEM_STATUS[i['status']]}`")
                if i["payload"].get("description"):
                    a.write(i["payload"]["description"])
                if i["evidence"].get("tables"):
                    a.caption("Preuves : " + ", ".join(i["evidence"]["tables"]))
                if i["payload"].get("hypotheses"):
                    a.caption("Hypothèses à vérifier : " + " ; ".join(i["payload"]["hypotheses"]))
                pl, details = i["payload"], []
                if pl.get("processus"):
                    details.append(f"Processus : {pl['processus']}")
                if pl.get("objectif"):
                    details.append(f"Objectif : {pl['objectif']}")
                if pl.get("cas_usage"):
                    details.append("Cas d'usage servis : " + ", ".join(pl["cas_usage"]))
                if pl.get("mode"):
                    details.append("Mode : " + T.MODES.get(pl["mode"], pl["mode"]) + (
                        f" — {pl.get('existant_nom') or pl['existant']} ({pl['existant']})" if pl.get("existant") else ""))
                if pl.get("membres"):
                    details.append("Membres : " + ", ".join(pl["membres"]))
                if pl.get("outils"):
                    details.append("Outils : " + ", ".join(pl["outils"]))
                if pl.get("ordre"):
                    details.append(f"Ordre : {pl['ordre']}")
                if pl.get("valeur"):
                    details.append(f"Valeur : {pl['valeur']}")
                if pl.get("effort"):
                    details.append(f"Effort : {pl['effort']}")
                if details:
                    a.caption(" | ".join(details))
                if pl.get("gain_attendu"):
                    a.write("Gain attendu : " + pl["gain_attendu"])
                if pl.get("justification"):
                    a.write("Justification : " + pl["justification"])
                if pl.get("dependances"):
                    a.caption("Dépendances : " + " ; ".join(pl["dependances"]))
                if pl.get("prerequis"):
                    a.caption("Prérequis : " + " ; ".join(pl["prerequis"]))
                if pl.get("risques"):
                    a.caption("Risques : " + " ; ".join(pl["risques"]))
                if pl.get("realisation"):
                    a.caption("Réalisation liée : " + pl["realisation"].get("objet_nom", "")
                              + f" ({pl['realisation'].get('objet_id', '')})")
                if pl.get("limites"):
                    a.caption("Limites : " + " ; ".join(pl["limites"]))
                if i["status"] != "propose":
                    a.caption(f"Décision : {i.get('decided_by')} le {i.get('decided_at')}"
                              + (f" — {i['decision_note']}" if i.get("decision_note") else ""))
                if owner:
                    note = a.text_input("Note (facultative)", key=f"note_{i['item_id']}", label_visibility="collapsed",
                                        placeholder="Note de décision (facultative)")
                    if i["status"] == "propose":
                        if b.button("Valider", key=f"ok_{i['item_id']}", type="primary"):
                            act("Décision impossible", lambda i=i, note=note: svc.decide(plan_id, i["item_id"], me, "valide", note),
                                f"« {i['name']} » validé.")
                        if b.button("Rejeter", key=f"ko_{i['item_id']}"):
                            act("Décision impossible", lambda i=i, note=note: svc.decide(plan_id, i["item_id"], me, "rejete", note),
                                f"« {i['name']} » rejeté.")
                    elif b.button("Rouvrir", key=f"re_{i['item_id']}"):
                        act("Décision impossible", lambda i=i: svc.decide(plan_id, i["item_id"], me, "propose"),
                            f"« {i['name']} » remis en proposition.")


with t3:
    st.subheader("Domaines et objectifs (AS-IS)")
    st.caption("Existant : objectifs et domaines métier, justifiés par les tables découvertes. Les processus métier "
               "sont reportés ; ceux déjà enregistrés restent affichés.")
    kinds = ("objectif", "domaine") + (("processus",) if any(i["item_type"] == "processus" for i in items) else ())
    render_items(kinds, "Aucun élément proposé. Demandez à HakimAI de décrire l'existant après la découverte.")
def _lv(v):
    return v.capitalize() if v else "—"


with t4:
    st.subheader("AI Opportunities")
    st.caption("Opportunités d'IA et d'automatisation proposées par HakimAI ou par vous, à partir de la découverte. "
               "Rien n'est créé dans la plateforme à cette étape. " + T.PRIORITY_RULE)
    opps = T.opportunities(items)
    val_domains = [i["name"] for i in items if i["item_type"] == "domaine" and i["status"] == "valide"]
    disc_tables = [t["table"] for t in (plan["discovery"] or {}).get("tables", []) if "erreur" not in t]
    cat_keys = [""] + list(T.OPPORTUNITY_CATEGORIES)
    lv_keys = [""] + list(T.LEVELS)

    def _fmt_cat(k):
        return T.OPPORTUNITY_CATEGORIES.get(k, "— non précisée")

    if not opps:
        st.info("Aucune opportunité. Validez un domaine et un objectif dans Enterprise Discovery, puis demandez à HakimAI "
                "le diagnostic, ou ajoutez une opportunité ci-dessous.")
    else:
        live = [o for o in opps if o["statut"] != "rejete"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Opportunités (non rejetées)", len(live))
        m2.metric("Validées", sum(1 for o in live if o["statut"] == "valide"))
        m3.metric("En attente de décision", sum(1 for o in live if o["statut"] == "propose"))
        m4.metric("Priorité haute", sum(1 for o in live if o["priorite"] == "haute"))
        st.markdown("**Matrice de priorisation** (valeur métier × faisabilité, opportunités non rejetées)")
        grid = {(v, f): [] for v in T.LEVELS for f in T.LEVELS}
        unrated = []
        for o in live:
            if o["valeur"] and o["faisabilite"]:
                grid[(o["valeur"], o["faisabilite"])].append(o["nom"])
            else:
                unrated.append(o["nom"])
        st.dataframe(pd.DataFrame([{"Valeur \\ Faisabilité": _lv(v), **{_lv(f): ", ".join(grid[(v, f)]) for f in T.LEVELS}}
                                   for v in reversed(T.LEVELS)]), hide_index=True, use_container_width=True)
        if unrated:
            st.caption("Non positionnées (valeur ou faisabilité manquante) : " + ", ".join(unrated))

        f1, f2, f3 = st.columns(3)
        doms = sorted({o["domaine"] or "Sans domaine" for o in opps})
        fd = f1.multiselect("Domaine", doms, key=f"opp_dom_{plan_id}")
        fs = f2.multiselect("Statut", list(ITEM_STATUS.values()), key=f"opp_st_{plan_id}")
        prio_labels = [p.capitalize() for p in T.PRIORITIES] + ["Non évaluée"]
        fp = f3.multiselect("Priorité", prio_labels, key=f"opp_pr_{plan_id}")
        view = [o for o in opps
                if (not fd or (o["domaine"] or "Sans domaine") in fd) and (not fs or ITEM_STATUS[o["statut"]] in fs)
                and (not fp or (o["priorite"].capitalize() if o["priorite"] else "Non évaluée") in fp)]
        table = pd.DataFrame([{
            "Sélection": False, "Domaine": o["domaine"] or "—", "Opportunité": o["nom"],
            "Catégorie": T.OPPORTUNITY_CATEGORIES.get(o["categorie"], "—"),
            "Données sources": ", ".join(t.split(".")[-1] for t in o["tables"]), "Solution IA": o["solution_ia"] or "—",
            "Valeur métier": o["valeur_metier"] or "—", "Valeur": _lv(o["valeur"]), "Faisabilité": _lv(o["faisabilite"]),
            "Complexité": _lv(o["complexite"]),
            "Priorité": (_lv(o["priorite"]) + (f" ({o['priorite_source']})" if o["priorite_source"] else "")),
            "Statut": ITEM_STATUS[o["statut"]]} for o in view])
        if view:
            edited = st.data_editor(table, hide_index=True, use_container_width=True, key=f"opp_tab_{plan_id}",
                                    disabled=[c for c in table.columns if c != "Sélection"] if owner else True)
            chosen = [view[n]["item_id"] for n, v in enumerate(edited["Sélection"]) if v]
            if owner:
                b1, b2, b3 = st.columns(3)
                if b1.button(f"Accepter la sélection ({len(chosen)})", type="primary", disabled=not chosen):
                    act("Décision impossible", lambda: svc.decide_many(plan_id, me, chosen, "valide"),
                        f"{len(chosen)} opportunité(s) acceptée(s).")
                if b2.button(f"Rejeter la sélection ({len(chosen)})", disabled=not chosen):
                    act("Décision impossible", lambda: svc.decide_many(plan_id, me, chosen, "rejete"),
                        f"{len(chosen)} opportunité(s) rejetée(s).")
                if b3.button(f"Remettre en proposition ({len(chosen)})", disabled=not chosen):
                    act("Décision impossible", lambda: svc.decide_many(plan_id, me, chosen, "propose"),
                        f"{len(chosen)} opportunité(s) remise(s) en proposition.")
        else:
            st.caption("Aucune opportunité pour ces filtres.")

        st.markdown("**Détail et modification**")
        by_id = {o["item_id"]: o for o in opps}
        oid = st.selectbox("Opportunité", list(by_id), format_func=lambda i: f"{by_id[i]['nom']} — "
                           f"{ITEM_STATUS[by_id[i]['statut']]}", key=f"opp_sel_{plan_id}")
        o = by_id[oid]
        if o["limites"]:
            st.caption("Limites : " + " ; ".join(o["limites"]))
        if o["modifie_par"]:
            st.caption(f"Modifiée par {o['modifie_par']}.")
        with st.form(f"opp_edit_{oid}"):
            desc = st.text_area("Opportunité (description du besoin)", o["description"], disabled=not owner)
            dom_opts = [""] + val_domains
            dom = st.selectbox("Domaine métier (validé)", dom_opts, disabled=not owner,
                               index=dom_opts.index(o["domaine"]) if o["domaine"] in dom_opts else 0)
            cat = st.selectbox("Catégorie", cat_keys, format_func=_fmt_cat, disabled=not owner,
                               index=cat_keys.index(o["categorie"]) if o["categorie"] in cat_keys else 0)
            tabs_sel = st.multiselect("Données sources (tables découvertes)", disc_tables, disabled=not owner,
                                      default=[t for t in o["tables"] if t in disc_tables])
            sol = st.text_input("Solution IA", o["solution_ia"] or "", disabled=not owner)
            gain = st.text_area("Valeur métier (bénéfices attendus, sans chiffre inventé)", o["valeur_metier"],
                                disabled=not owner)
            c1, c2, c3, c4 = st.columns(4)
            pl = by_id[oid]
            val = c1.selectbox("Valeur", lv_keys, format_func=_lv, disabled=not owner,
                               index=lv_keys.index(pl["valeur"]) if pl["valeur"] in lv_keys else 0)
            fea = c2.selectbox("Faisabilité", lv_keys, format_func=_lv, disabled=not owner,
                               index=lv_keys.index(pl["faisabilite"]) if pl["faisabilite"] in lv_keys else 0)
            cpx = c3.selectbox("Complexité", lv_keys, format_func=_lv, disabled=not owner,
                               index=lv_keys.index(pl["complexite"]) if pl["complexite"] in lv_keys else 0)
            pr_keys = [""] + list(T.PRIORITIES)
            forced = pl["priorite"] if pl["priorite_source"] == "forcée" else ""
            pri = c4.selectbox("Priorité", pr_keys, disabled=not owner, index=pr_keys.index(forced),
                               format_func=lambda k: k.capitalize() if k else "Calculée")
            if st.form_submit_button("Enregistrer les modifications", disabled=not owner):
                act("Modification impossible", lambda: svc.update_opportunity(plan_id, me, oid, {
                    "description": desc, "domaine": dom, "categorie": cat, "tables": tabs_sel, "solution_ia": sol,
                    "gain_attendu": gain, "valeur": val, "faisabilite": fea, "complexite": cpx, "priorite": pri}),
                    f"« {o['nom']} » modifiée.")

    if owner:
        with st.expander("Ajouter une opportunité"):
            if not disc_tables:
                st.info("Lancez d'abord la découverte : une opportunité cite au moins une table découverte.")
            else:
                with st.form(f"opp_new_{plan_id}", clear_on_submit=True):
                    n_name = st.text_input("Nom de l'opportunité")
                    n_desc = st.text_area("Description du besoin")
                    n_dom = st.selectbox("Domaine métier (validé)", [""] + val_domains)
                    n_cat = st.selectbox("Catégorie", cat_keys, format_func=_fmt_cat)
                    n_tab = st.multiselect("Données sources", disc_tables)
                    n_sol = st.text_input("Solution IA")
                    n_gain = st.text_area("Valeur métier")
                    d1, d2, d3 = st.columns(3)
                    n_val = d1.selectbox("Valeur", lv_keys, format_func=_lv)
                    n_fea = d2.selectbox("Faisabilité", lv_keys, format_func=_lv)
                    n_cpx = d3.selectbox("Complexité", lv_keys, format_func=_lv)
                    if st.form_submit_button("Ajouter (statut Proposé)"):
                        act("Ajout impossible", lambda: svc.propose(plan_id, me, [{
                            "type": "cas_usage", "nom": n_name, "description": n_desc, "domaine": n_dom,
                            "categorie": n_cat, "tables": n_tab, "solution_ia": n_sol, "gain_attendu": n_gain,
                            "valeur": n_val, "faisabilite": n_fea, "complexite": n_cpx}], origin="utilisateur"),
                            "Opportunité ajoutée, en attente de votre décision.")
with t5:
    st.subheader("Cible (TO-BE)")
    chart = T.org_chart(items, plan["name"], catalog)
    if len(chart["nodes"]) > 1:
        st.markdown("**Organigramme de la cible**")
        st.caption("Équipes, agents, outils et flux prévus. Trait plein : validé ou existant ; pointillé : proposé, "
                   "en attente de votre décision. Les éléments rejetés ne figurent pas.")
        st.graphviz_chart(T.org_chart_dot(chart), use_container_width=True)
    render_items(T.TARGET_TYPES, "Aucun élément de la cible. Validez des cas d'usage (AI Opportunities), puis demandez à "
                                 "HakimAI de concevoir la cible. Rien n'est créé dans la plateforme à cette étape.")
with t_gap:
    st.subheader("Écarts AS-IS → TO-BE")
    st.caption("Pour chaque cas d'usage (AS-IS), les éléments de la cible qui le servent et le type de changement. "
               "Les éléments rejetés sont exclus. Rien n'est créé dans la plateforme depuis cet onglet.")
    gaps = svc.gaps(items, catalog)
    if not gaps:
        st.info("Aucun cas d'usage. Les écarts apparaissent après l'étape 4.")
    else:
        no_target = sorted({g["cas_usage"] for g in gaps if g["element"] is None})
        m1, m2, m3 = st.columns(3)
        m1.metric("Cas d'usage", len({g["cas_usage"] for g in gaps}))
        m2.metric("Éléments de cible", len({(g["type"], g["element"]) for g in gaps if g["element"]}))
        m3.metric("Cas sans cible", len(no_target))
        st.dataframe(pd.DataFrame([{
            "Cas d'usage": g["cas_usage"], "Statut du cas": ITEM_STATUS[g["statut_cas"]],
            "Données (AS-IS)": ", ".join(t.split(".")[-1] for t in g["tables"]),
            "Élément cible": g["element"] or "—", "Type": T.ITEM_LABELS.get(g["type"], "—") if g["type"] else "—",
            "Changement": g["changement"],
            "Statut de l'élément": ITEM_STATUS.get(g["statut_element"], "—") if g["statut_element"] else "—",
            "Objet réel": g["objet"] or "—", "Statut de l'objet": g["statut_objet"] or "—"} for g in gaps]),
            hide_index=True, use_container_width=True)
        if no_target:
            st.warning("Sans élément de cible : " + ", ".join(no_target) + ". Validez ces cas, puis demandez à HakimAI "
                       "de concevoir la cible.")
with t6:
    st.subheader("Feuille de route")
    render_items(("vague",), "Aucune vague. Validez des éléments de cible (Target EIA Architecture), puis demandez à HakimAI de "
                              "proposer la feuille de route.")
with t7:
    st.subheader("Suivi de la réalisation")
    st.caption("Suivi des objets réels liés au plan. Aucune publication automatique : créez ou modifiez les brouillons "
               "avec les outils HakimAI habituels, puis reliez-les au plan.")
    if not tracking:
        st.info("Aucun élément planifié en vague validée.")
    else:
        st.dataframe(pd.DataFrame([{"Vague": x["vague"], "Ordre": x["ordre"], "Type": T.ITEM_LABELS[x["type"]],
                                    "Élément": x["nom"], "Mode": T.MODES.get(x["mode"], x["mode"]),
                                    "Objet réel": x.get("objet_nom") or x.get("objet_id") or "—",
                                    "Statut": T.TRACK_LABELS[x["statut"]], "Action": x["prochaine_action"]}
                                   for x in tracking]), hide_index=True, use_container_width=True)
        for x in tracking:
            if x["statut"] == "introuvable":
                st.warning(f"{x['nom']} : l'objet lié n'est plus visible ({x.get('objet_id')}).")
