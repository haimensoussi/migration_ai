"""Missions EIA : recommandations à traiter, missions, tâches et affectations, cycles et bilan.

Toutes les décisions passent par backend.eia.console / engine (mêmes contrôles que les outils HAKIM),
avec confirmation explicite et identité de l'utilisateur connecté. Aucune décision n'est prise par un agent.
"""
import pandas as pd
import streamlit as st

from backend.eia import console as cs
from backend.eia import engine
from backend.eia.adapters import SqlKpiSource
from ui import eia_ui as ui

L = cs.LABELS
st.title("Missions")
st.caption("Les agents EIA proposent ; vous décidez. Sélectionner une recommandation, valider une mission, "
           "confirmer une affectation et clôturer sont des décisions distinctes, enregistrées à votre nom.")
cfg, repo, sql, user = ui.context()
ui.flash()

tab_reco, tab_mis, tab_runs = st.tabs(["Recommandations", "Missions", "Cycles"])

# ---------------- recommandations ----------------
with tab_reco:
    try:
        recos = cs.open_recommendations(repo, cfg.team_id)
    except Exception as e:  # noqa: BLE001
        st.error(f"Lecture impossible : {e}")
        recos = []
    if not recos:
        st.info("Aucune recommandation en attente. Lancez un cycle (onglet Cycles) ou demandez un aperçu à HakimAI.")
    for r in recos:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**P{r.get('priority')} · {r['title']}** · {L['recommendation'].get(r['status'], r['status'])}")
            c1.caption(f"{len(r.get('based_on') or [])} alerte(s) à l'origine · cycle {r.get('run_id')} · "
                       + " · ".join(r.get("assumptions") or []))
            with c1.expander("Justification"):
                st.write(r.get("rationale") or "")
                if r.get("risks"):
                    st.caption("Risques : " + " ; ".join(r["risks"]))
            if r.get("mission_id"):
                c2.caption(f"Mission {r['mission_id']} ({L['mission'].get(r['mission_status'], r['mission_status'])})")
            else:
                def _prepare(rid=r["reco_id"]):
                    out = engine.prepare_mission(cfg, repo, rid, user, source=SqlKpiSource(sql))
                    return (f"Mission {out['mission_id']} préparée en brouillon ({len(out['taches'])} tâches) ; "
                            "à valider dans l'onglet Missions.")
                ui.confirm_button("Préparer la mission", f"prep_{r['reco_id']}", _prepare, primary=True, container=c2,
                                  help="Sélectionne la recommandation et crée un brouillon avec affectations proposées")

# ---------------- missions ----------------
with tab_mis:
    try:
        missions = repo.missions(cfg.team_id)
    except Exception as e:  # noqa: BLE001
        st.error(f"Lecture impossible : {e}")
        missions = []
    if not missions:
        st.info("Aucune mission. Préparez-en une depuis l'onglet Recommandations.")
    else:
        by_id = {m["mission_id"]: m for m in missions}
        mid = st.selectbox("Mission", list(by_id), key="eia_mission", format_func=lambda i: (
            f"{by_id[i]['title']} · {L['mission'].get(by_id[i]['status'], by_id[i]['status'])} · {i}"))
        d = cs.mission_detail(repo, cfg.team_id, mid)
        m, tasks = d["mission"], d["tasks"]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Statut", L["mission"].get(m["status"], m["status"]))
        k2.metric("Tâches faites", f"{d['done']} / {len(tasks)}")
        k3.metric("Charge estimée", f"{d['hours']} h")
        k4.metric("Échéance", str(m.get("due_date") or "—"))
        st.markdown(f"**Objectif** : {m.get('objective') or ''}")
        st.caption(f"Responsable : {m.get('owner') or '—'} · créée par {m.get('created_by')} le {ui.ts(m.get('created_at'))}"
                   + (f" · validée par {m.get('validated_by')} le {ui.ts(m.get('validated_at'))}" if m.get("validated_by") else "")
                   + f" · recommandation « {d['recommendation'].get('title', m.get('reco_id'))} »")
        if m.get("success_kpis"):
            st.caption("KPI de réussite : " + ", ".join(str(k.get("metric") if isinstance(k, dict) else k)
                                                      for k in m["success_kpis"]))

        acts = d["actions"]
        if acts:
            cols = st.columns(len(acts))
            for col, a in zip(cols, acts):
                ui.confirm_button(a["label"], f"m_{mid}_{a['target']}", container=col, disabled=not a["allowed"],
                                  help=a["reason"] or None, primary=a["target"] in ("validee", "en_cours", "terminee"),
                                  action=lambda t=a["target"]: (cs.decide(repo, cfg.team_id, user, mid, "mission", t),
                                                                f"Mission : {L['mission'][t].lower()}.")[1])
        if m["status"] == "brouillon":
            st.info("Brouillon : validez la mission pour pouvoir confirmer les affectations et faire avancer les tâches.")

        people = {p["person_id"]: p for p in repo.people(cfg.team_id, active_only=False)}
        st.subheader("Tâches")
        for t in tasks:
            with st.container(border=True):
                c1, c2 = st.columns([3, 2])
                c1.markdown(f"**{t['title']}** · {L['task'].get(t['status'], t['status'])}")
                c1.caption(f"{t.get('estimated_hours') or 0} h · échéance {t.get('due_date') or '—'} · responsable "
                           f"{t.get('owner') or '—'}" + (f" · après : {', '.join(t['depends_on_titles'])}"
                                                          if t["depends_on_titles"] else ""))
                if t.get("required_skills"):
                    c1.caption("Compétences : " + ", ".join(f"{s.get('skill')} ≥ {s.get('level')}" if isinstance(s, dict)
                                                            else str(s) for s in t["required_skills"]))
                if t["actions"]:
                    tc_cols = c2.columns(len(t["actions"]))
                    for col, a in zip(tc_cols, t["actions"]):
                        ui.confirm_button(a["label"], f"t_{t['task_id']}_{a['target']}", container=col,
                                          disabled=not a["allowed"], help=a["reason"] or None,
                                          action=lambda tid=t["task_id"], tg=a["target"]: (
                                              cs.decide(repo, cfg.team_id, user, mid, "tache", tg, task_id=tid),
                                              f"Tâche : {L['task'][tg].lower()}.")[1])
                shown = [a for a in t["assignments"] if a["status"] != "annulee"]
                if shown:
                    c1.markdown("**Affectations**")
                for a in shown:
                    p = people.get(a["person_id"], {})
                    r1, r2 = c1.columns([3, 2])
                    r1.markdown(f"{a.get('rank')}. **{p.get('full_name', a['person_id'])}** ({a['person_id']}, "
                                f"{p.get('job_title') or '—'}) · score {a.get('score')} · "
                                f"{L['assignment'].get(a['status'], a['status'])}")
                    r1.caption(a.get("rationale") or "")
                    for a2 in a["actions"]:
                        ui.confirm_button(a2["label"], f"a_{a['assignment_id']}_{a2['target']}", container=r2,
                                          disabled=not a2["allowed"], help=a2["reason"] or None,
                                          primary=a2["target"] == "confirmee",
                                          action=lambda aid=a["assignment_id"], tg=a2["target"], nm=p.get("full_name"): (
                                              cs.decide(repo, cfg.team_id, user, mid, "affectation", tg, assignment_id=aid),
                                              f"Affectation de {nm or aid} : {L['assignment'][tg].lower()}.")[1])

        st.subheader("Bilan (LEARN)")
        st.caption("Compare les KPI de réussite à la référence figée à la création. Lecture seule ; une évolution "
                   "favorable ne prouve pas que la mission en est la cause.")
        if st.button("Calculer le bilan", key=f"learn_{mid}", disabled=m["status"] != "terminee",
                     help=None if m["status"] == "terminee" else "Disponible après clôture de la mission"):
            try:
                b = engine.learn_mission(cfg, repo, SqlKpiSource(sql), mid)
                if b.get("motif"):
                    st.info(b["motif"])
                if b.get("comparaisons"):
                    st.dataframe(pd.DataFrame(b["comparaisons"]), hide_index=True, use_container_width=True)
                if b.get("erreurs"):
                    st.warning(" ; ".join(map(str, b["erreurs"])))
            except Exception as e:  # noqa: BLE001
                st.error(str(e))

        with st.expander("Historique de la mission"):
            ev = repo.events(mid) + [e for t in tasks for e in repo.events(t["task_id"])]
            if ev:
                st.dataframe(pd.DataFrame([{"Date": ui.ts(e.get("created_at")), "Objet": e.get("object_type"),
                                            "Événement": e.get("event_type"), "Par": e.get("actor")}
                                           for e in sorted(ev, key=lambda x: str(x.get("created_at")))]),
                             hide_index=True, use_container_width=True)

# ---------------- cycles ----------------
with tab_runs:
    st.caption("Un cycle enregistré exécute PERCEIVE → PLAN (constats, prévisions, alertes, recommandations). Il ne crée "
               "ni mission ni affectation et n'envoie aucune notification. Durée indicative : 2 à 3 minutes.")

    def _cycle():
        engine._human(user)
        out = engine.run_cycle(cfg, SqlKpiSource(sql), repo, actor=user)
        return f"Cycle {out['run_id']} : {out['statut']}. {out['synthese']}"
    ui.confirm_button("Lancer un cycle enregistré", "run_cycle", _cycle, primary=True)
    try:
        rows = cs.runs(repo, cfg.team_id)
    except Exception as e:  # noqa: BLE001
        st.error(f"Lecture impossible : {e}")
        rows = []
    if rows:
        st.dataframe(pd.DataFrame([{"Cycle": r["run_id"], "Statut": r.get("status"), "Déclencheur": r.get("trigger"),
                                    "Demandé par": r.get("requested_by"), "Début": ui.ts(r.get("started_at")),
                                    "Fin": ui.ts(r.get("ended_at")), "Synthèse": r.get("summary") or r.get("error") or ""}
                                   for r in rows]), hide_index=True, use_container_width=True)
    else:
        st.caption("Aucun cycle enregistré.")
