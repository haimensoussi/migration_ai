"""Agent Mesh : domaines -> équipes -> agents, carte du mesh et recherche par capacité (lecture seule)."""
import pandas as pd
import streamlit as st

from backend import mesh_org as M
from ui import state

repo = state.repository()
agents = state.agents()
contracts = state.contracts()
mesh = M.build_mesh(agents, state.teams(), contracts, M.domain_names(repo.sql, repo.s.table("domains")))

st.title("Agent Mesh")
st.caption("Un domaine regroupe plusieurs équipes, une équipe plusieurs agents. HakimAI choisit le domaine puis "
           "l'équipe la plus adaptée et transmet la question à son chef, qui consulte ses agents. Seules les équipes "
           "publiées sont joignables. Le domaine d'une équipe est sa filière ; celui d'un agent, sa fiche contrat.")

cols = st.columns(len(mesh["domaines"]) or 1)
for col, d, row in zip(cols, mesh["domaines"], M.summary(mesh)):
    with col.container(border=True):
        st.markdown(f"**{d['domaine']}**")
        c1, c2 = st.columns(2)
        c1.metric("Équipes", row["equipes"])
        c2.metric("Agents publiés", row["agents_publies"])
        if d["equipes"]:
            for t in d["equipes"]:
                st.caption(f"{t['equipe']} · {1 + len(t['membres']) if t['chef'] else len(t['membres'])} agents"
                           + ("" if t["joignable"] else " · non joignable"))
        else:
            st.caption(":orange[Aucune équipe publiée : domaine non interrogeable par HakimAI]")
        if d["equipes_en_preparation"]:
            st.caption("En préparation : " + ", ".join(d["equipes_en_preparation"]))

alerts = []
if mesh["sans_domaine"]:
    alerts.append("Agents publiés sans domaine (fiche contrat à compléter) : " + ", ".join(mesh["sans_domaine"]))
if mesh["hors_equipe"]:
    alerts.append("Agents publiés hors équipe (non joignables par HakimAI, utilisables dans Chat & Test) : "
                  + ", ".join(mesh["hors_equipe"]))
if mesh["equipes_hors_domaine"]:
    alerts.append("Équipes publiées dont la filière n'est pas un domaine : " + ", ".join(mesh["equipes_hors_domaine"]))
for x in mesh["incoherences"]:
    alerts.append(f"{x['agent']} (domaine {x['domaine_agent']}) est membre de l'équipe {x['equipe']} "
                  f"(domaine {x['domaine_equipe']}).")
for a in alerts:
    st.warning(a)

t_dom, t_map, t_search = st.tabs(["Domaines et équipes", "Carte du mesh", "Rechercher une capacité"])

with t_dom:
    for d in mesh["domaines"]:
        with st.expander(f"{d['domaine']} · {len(d['equipes'])} équipe(s) publiée(s)", expanded=bool(d["equipes"])):
            if not d["equipes"]:
                st.caption("Aucune équipe publiée dans ce domaine.")
            for t in d["equipes"]:
                st.markdown(f"**{t['equipe']}** `{t['appel']}`" + ("" if t["joignable"] else " · :orange[chef non publié]"))
                st.caption(t["mission"] or "Mission à préciser")
                rows = ([{"Rôle": "Chef", "Agent": t["chef"]["nom"]}] if t["chef"] else []) + [
                    {"Rôle": "Membre", "Agent": m["nom"] + ("" if m["statut"] == M.PUBLISHED else f" ({m['statut']})")}
                    for m in t["membres"]]
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            if d["agents_publies"]:
                st.caption("Agents publiés du domaine : " + ", ".join(d["agents_publies"]))

with t_map:
    st.graphviz_chart(M.mesh_dot(mesh), use_container_width=True)
    st.caption("Pointillés : domaine sans équipe publiée, ou agent membre non publié.")

with t_search:
    c1, c2 = st.columns([3, 1])
    q = c1.text_input("Capacité recherchée", placeholder="ex. anomalies de complétude, régularité des TER")
    dom = c2.selectbox("Domaine", ["Tous"] + [d["domaine"] for d in mesh["domaines"]])
    if q.strip():
        r = M.search(mesh, agents, contracts, q, "" if dom == "Tous" else dom)
        st.caption("Mots recherchés : " + (", ".join(r["mots_recherches"]) or "aucun mot utile"))
        if r["equipe_recommandee"]:
            st.success(f"Équipe recommandée : {r['equipe_recommandee']}")
        elif r["a_departager"]:
            st.info("Équipes à départager : " + ", ".join(r["a_departager"]))
        if r["equipes"]:
            st.dataframe(pd.DataFrame([{"Équipe": t["equipe"], "Domaine": t["domaine"], "Score": t["score"],
                                        "Motif": ", ".join(t["motif"]), "Joignable": "oui" if t["joignable"] else "non"}
                                       for t in r["equipes"]]), hide_index=True, use_container_width=True)
        else:
            st.caption("Aucune équipe publiée ne correspond.")
        if r["agents"]:
            st.dataframe(pd.DataFrame([{"Agent": a["agent"], "Domaine": a["domaine"], "Score": a["score"],
                                        "Motif": ", ".join(a["motif"]),
                                        "Équipes": ", ".join(a["equipes"]) or "hors équipe"} for a in r["agents"]]),
                         hide_index=True, use_container_width=True)
        else:
            st.caption("Aucun agent publié ne correspond.")
    else:
        st.caption("Saisissez une capacité : la recherche porte sur la mission des équipes et les fiches contrat des agents.")
