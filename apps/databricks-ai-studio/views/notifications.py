"""Notifications EIA : alertes métier et techniques, suivi humain, état du canal d'envoi.

Les erreurs techniques ne sont jamais mélangées aux anomalies métier. Aucun envoi n'est déclenché depuis
cette page : l'envoi externe (Power Automate) n'a lieu que si le canal de l'équipe est validé dans sa configuration.
"""
import datetime as dt

import pandas as pd
import streamlit as st

from backend.eia import alerting as al
from backend.eia import console as cs
from ui import eia_ui as ui

L = cs.LABELS["alert"]
st.title("Notifications")
st.caption("Alertes produites par les règles de l'équipe. Les seuils marqués « à valider » sont provisoires.")
cfg, repo, _sql, user = ui.context()
ui.flash()

try:
    alerts = repo.alerts(cfg.team_id, limit=1000)
except Exception as e:  # noqa: BLE001
    st.error(f"Lecture impossible : {e}")
    st.stop()

s = cs.alert_summary(alerts)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Anomalies métier ouvertes", s["ouvertes_metier"])
k2.metric("dont critiques", s["critiques_metier"])
k3.metric("Erreurs techniques ouvertes", s["ouvertes_techniques"])
k4.metric("Acquittées / résolues", f"{s['acquittees']} / {s['resolues']}")

# ---------------- canal d'envoi ----------------
n = cs.notification_status(cfg, alerts, dt.date.today())
with st.container(border=True):
    st.markdown("**Canal d'envoi**")
    if n["envoi_actif"]:
        st.success(f"Envoi actif via {n['canal'] or 'canal configuré'} à partir de la gravité « {n['gravite_min']} » "
                   f"vers : {', '.join(n['destinataires']) or 'aucun destinataire'}.")
    else:
        st.warning(f"Envoi désactivé : {n['motif']}. Les alertes restent visibles ici ; aucun message n'est envoyé.")
    st.caption(f"{n['eligibles']} nouvelle(s) alerte(s) métier atteignent la gravité « {n['gravite_min']} ». "
               "L'envoi est fait par le cycle d'alerting, jamais depuis cette page.")
    if n["apercu_sujet"]:
        with st.expander("Aperçu du message récapitulatif (non envoyé)"):
            st.markdown(f"**{n['apercu_sujet']}**")
            st.text(n["apercu_corps"])

# ---------------- liste ----------------
f1, f2, f3 = st.columns(3)
kind = f1.radio("Nature", ["metier", "technique"], horizontal=True,
                format_func=lambda k: "Anomalies métier" if k == "metier" else "Erreurs techniques")
sev = f2.multiselect("Gravité", list(al.SEV_RANK), default=list(al.SEV_RANK))
statuses = f3.multiselect("Statut", list(L), default=["nouvelle", "vue"], format_func=L.get)
rows = sorted((a for a in alerts if a["kind"] == kind and a["severity"] in sev and a["status"] in statuses),
              key=lambda a: (-al.SEV_RANK.get(a["severity"], 0), a["rule_id"], a.get("scope") or ""))
if not rows:
    st.info("Aucune alerte pour ces filtres.")
    st.stop()
st.dataframe(pd.DataFrame([{
    "Gravité": a["severity"], "Règle": a["rule_id"], "Seuil": "à valider" if a.get("rule_status") == "a_valider" else "validé",
    "Alerte": a["title"], "Observé": a.get("observed"), "Seuil règle": a.get("threshold"), "Période": a.get("period"),
    "Statut": L.get(a["status"], a["status"]), "Occurrences": a.get("occurrences"),
    "Dernière détection": ui.ts(a.get("last_seen_at")), "Décidé par": a.get("decided_by") or ""} for a in rows]),
    hide_index=True, use_container_width=True)

# ---------------- détail et suivi ----------------
st.subheader("Suivi d'une alerte")
by_id = {a["alert_id"]: a for a in rows}
aid = st.selectbox("Alerte", list(by_id), format_func=lambda i: f"[{by_id[i]['severity']}] {by_id[i]['title']}")
a = by_id[aid]
st.write(a.get("message") or "")
ev = a.get("evidence") or {}
if ev:
    with st.expander("Preuve (requête et source)"):
        st.caption(f"Outil : {ev.get('tool')} · source : {ev.get('source')}")
        if ev.get("query"):
            st.code(ev["query"], language="sql")
acts = cs.alert_actions(a)
if acts:
    cols = st.columns(len(acts))
    for col, x in zip(cols, acts):
        ui.confirm_button(x["label"], f"al_{aid}_{x['target']}", container=col, primary=x["target"] == "acquittee",
                          action=lambda t=x["target"]: (cs.decide_alert(repo, cfg.team_id, user, aid, t),
                                                        f"Alerte : {L[t].lower()}.")[1])
else:
    st.caption("Alerte résolue : aucune action restante.")
