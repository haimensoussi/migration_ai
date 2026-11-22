"""Transformation : plan guidé par HakimAI (étapes 1 à 7). L'utilisateur décide ici."""
import pandas as pd
import streamlit as st

from backend import transformation as T
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
phases = T.phases(steps)
for col, (n, ph) in zip(st.columns(len(phases)), enumerate(phases, 1)):
    col.metric(f"{n}. {ph['libelle']}", ST_LABEL[ph["statut"]])
pending = sum(1 for i in items if i["status"] == "propose")
st.info("**Prochaine action** : " + T.next_action(steps)
        + (f" — {pending} élément(s) en attente de votre décision." if pending else ""))
for warning in svc.coherence(items):
    st.warning(warning)
if st.button("Continuer avec HakimAI", type="primary"):
    st.switch_page("views/hakim.py")

t_disc, t_opp, t_arch, t_dep = st.tabs([f"{n}. {ph['libelle']}" for n, ph in enumerate(phases, 1)])
t1 = t2 = t3 = t_disc
t4 = t_opp
t5 = t_gap = t_arch
t6 = t7 = t_dep

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
with t4:
    st.subheader("Opportunités : cas d'usage")
    render_items(("cas_usage",), "Aucun cas d'usage. Validez un objectif et un domaine dans Enterprise Discovery, puis demandez à "
                                 "HakimAI le diagnostic.")
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
