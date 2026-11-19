"""Transformation : plan guidé par HakimAI (lot A : cadrage, découverte, cartographie). L'utilisateur décide ici."""
import pandas as pd
import streamlit as st

from backend import transformation as T
from ui import state
from ui.components import error_box

ST_LABEL = {"fait": "Fait", "en_cours": "En cours", "a_faire": "À faire", "lot_b": "Lot B"}
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

steps = svc.progress(plan, items)
for col, s in zip(st.columns(len(steps)), steps):
    col.metric(f"{s['etape']}. {s['libelle']}", ST_LABEL[s["statut"]])
if st.button("Continuer avec HakimAI", type="primary"):
    st.switch_page("views/hakim.py")

t1, t2, t3 = st.tabs(["1. Cadrage", "2. Découverte des données", "3. Cartographie"])

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

with t3:
    if not items:
        st.info("Aucun élément proposé. Demandez à HakimAI de proposer la cartographie après la découverte.")
    for kind in T.ITEM_TYPES_LOT_A:
        group = [i for i in items if i["item_type"] == kind]
        if not group:
            continue
        st.subheader(T.ITEM_LABELS[kind] + ("s" if len(group) > 1 else ""))
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
