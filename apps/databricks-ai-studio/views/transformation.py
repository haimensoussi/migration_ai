"""Transformation : plan guidé par HakimAI (étapes 1 à 7). L'utilisateur décide ici."""
import pandas as pd
import streamlit as st

from backend import transformation as T
from ui import state
from ui.components import error_box

ST_LABEL = {"fait": "Fait", "en_cours": "En cours", "a_faire": "À faire", "lot_b2": "Lot B2"}
ITEM_STATUS = {"propose": "Proposé", "valide": "Validé", "rejete": "Rejeté"}

st.title("Transformation")
st.caption("HakimAI vous guide vers une organisation augmentée par l'IA : il propose, vous décidez ici. "
           "La découverte lit la structure des tables data_ et des statistiques agrégées, avec vos droits, sans lire "
           "de lignes.")

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
for col, s in zip(st.columns(len(steps)), steps):
    col.metric(f"{s['etape']}. {s['libelle']}", ST_LABEL[s["statut"]])
for warning in svc.coherence(items):
    st.warning(warning)
if st.button("Continuer avec HakimAI", type="primary"):
    st.switch_page("views/hakim.py")

t1, t2, t3, t4, t5, t6, t7 = st.tabs(["1. Cadrage", "2. Découverte des données", "3. Cartographie",
                                      "4. Diagnostic et opportunités", "5. Conception de la cible",
                                      "6. Feuille de route", "7. Génération et suivi"])

with t1:
    ctx = plan["context"]
    with st.form("transfo_ctx"):
        values = {k: st.text_area(label, ctx.get(k, ""), height=80, disabled=not owner)
                  for k, label in T.CONTEXT_FIELDS.items()}
        if st.form_submit_button("Enregistrer le cadrage", disabled=not owner):
            act("Enregistrement impossible", lambda: svc.set_context(plan_id, me, values), "Cadrage enregistré.")

with t2:
    d = plan["discovery"]
    if owner and st.button("Relancer la découverte" if d else "Lancer la découverte"):
        s = state.settings()
        with st.spinner("Lecture de la structure et calcul des statistiques..."):
            act("Découverte impossible", lambda: svc.set_discovery(plan_id, me, T.discover(
                lambda c, sc: list(w.tables.list(catalog_name=c, schema_name=sc)), sql, s.catalog, s.schema)),
                "Découverte enregistrée.")
    if not d:
        st.info("Pas encore de découverte.")
    else:
        st.caption(f"{d['perimetre']} — {d['date']}. {d['avertissement']}")
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

def render_items(kinds, empty: str) -> None:
    """Éléments d'une étape, avec leurs preuves, rattachements et décisions."""
    if not any(i["item_type"] in kinds for i in items):
        st.info(empty)
    for kind in kinds:
        group = [i for i in items if i["item_type"] == kind]
        if not group:
            continue
        st.subheader(T.ITEM_PLURALS[kind] if len(group) > 1 else T.ITEM_LABELS[kind])
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
    render_items(T.ITEM_TYPES_LOT_A, "Aucun élément proposé. Demandez à HakimAI de proposer la cartographie après la "
                                     "découverte.")
with t4:
    render_items(("cas_usage",), "Aucun cas d'usage. Validez des processus (onglet 3), puis demandez à HakimAI le "
                                 "diagnostic.")
with t5:
    render_items(T.TARGET_TYPES, "Aucun élément de la cible. Validez des cas d'usage (onglet 4), puis demandez à "
                                 "HakimAI de concevoir la cible. Rien n'est créé dans la plateforme à cette étape.")
with t6:
    render_items(("vague",), "Aucune vague. Validez des éléments de cible (onglet 5), puis demandez à HakimAI de "
                              "proposer la feuille de route.")
with t7:
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
