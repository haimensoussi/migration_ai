"""Catalogue d'agents EIA (EIA Factory, étape 2) : catégories AG01-AG11, modèles et modèles d'équipe. Lecture seule."""
import pandas as pd
import streamlit as st

from backend.eia import agent_catalog as ac

STATUS = {"disponible": "Disponible", "partiel": "Partiel", "squelette": "Squelette", "fusionne": "Fusionné"}
STATE = {"operationnel": "Opérationnel", "en_attente_de_modeles": "En attente de modèles", "incoherent": "Incohérent"}

st.title("Catalogue d'agents")
st.caption("Les onze catégories officielles et leurs modèles réutilisables, dérivés du code (Framework). Un modèle "
           "s'adapte à un nouveau métier par sa fiche de paramètres, sans développement.")

s = ac.summary()
cols = st.columns(4)
cols[0].metric("Catégories", s["categories"])
for col, k in zip(cols[1:], ("disponible", "partiel", "squelette")):
    col.metric(STATUS[k], s["par_statut"].get(k, 0))

t_cards, t_teams, t_rules = st.tabs(["Fiches", "Modèles d'équipe", "Garde-fous communs"])

with t_cards:
    rows = [{"Code": c["code"], "Nom": c["nom"], "Statut": STATUS.get(c["statut"], c["statut"]),
             "Version": (c.get("modele") or {}).get("version", ""), "Capacités": ", ".join(c.get("capacites") or []),
             "Équipes types": ", ".join(c["modeles_equipe"])} for c in ac.cards()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    code = st.selectbox("Fiche détaillée", [r["Code"] for r in rows],
                        format_func=lambda x: f"{x} - {ac.card(x)['nom']}", key="cat_code")
    c = ac.card(code)
    st.markdown(f"**{c['code']} {c['nom']}** · {STATUS.get(c['statut'], c['statut'])}")
    st.write(c["fonctions_officielles"])
    if c.get("fusionne_dans"):
        st.info(f"Fusionné dans {c['fusionne_dans']} : ses fonctions sont portées par ce modèle.")
    else:
        m = c["modele"]
        st.caption(f"Version {m['version']} · {m['conditions_usage']}")
        a, b = st.columns(2)
        a.markdown("**Reçoit**")
        a.write({k: (", ".join(v) or "extérieur") for k, v in c["recoit_de"].items()} or "—")
        b.markdown("**Transmet**")
        b.write({k: (", ".join(v) or "humain / restitution") for k, v in c["transmet_a"].items()} or "—")
        if m["parametres"]:
            st.markdown("**Fiche de paramètres**")
            st.dataframe(pd.DataFrame(m["parametres"]), hide_index=True, use_container_width=True)
        st.markdown("**Points d'entrée dans le code** : " + (", ".join(f"`{p}`" for p in m["points_entree"]) or "aucun"))
        st.markdown("**Garde-fous propres**")
        for g in m["garde_fous"][len(s["garde_fous_communs"]):]:
            st.write(f"* {g}")
        if m["reste_a_faire"]:
            st.warning(f"Reste à faire : {m['reste_a_faire']}")

with t_teams:
    for t in ac.templates():
        with st.container(border=True):
            st.markdown(f"**{t['nom']}** · {STATE.get(t['etat'], t['etat'])} · {' + '.join(t['modeles'])}")
            st.write(t["description"])
            st.caption("Prérequis : " + " ; ".join(t["prerequis"]))
            for p in t["problemes"]:
                st.error(p)
            for m in t["modeles_a_completer"]:
                st.caption(f"{m['code']} ({STATUS.get(m['statut'])}) : {m['reste_a_faire']}")
    if st.button("Concevoir une équipe avec le Team Builder", type="primary"):
        st.switch_page("views/team_builder.py")

with t_rules:
    for g in s["garde_fous_communs"]:
        st.write(f"* {g}")
