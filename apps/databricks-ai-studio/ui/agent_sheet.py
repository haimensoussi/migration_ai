"""Fiche produit d'un agent (Agentic Mesh phase 1) : contrat versionné + indicateurs de qualité sur 30 jours."""
import streamlit as st

from backend import agent_contracts as ac
from ui import state

DAYS = 30


def _fmt_ms(v):
    return "—" if v is None else (f"{v / 1000:.1f} s" if v >= 1000 else f"{int(v)} ms")


def render_sheet(agent: dict) -> None:
    try:
        c = state.contracts().get(agent["agent_id"])
    except Exception as e:  # noqa: BLE001
        st.error(f"Fiche contrat indisponible : {e}")
        c = None
    st.markdown(f"### {agent['name']}")
    st.caption(f"Propriétaire : {agent.get('owner')} · version agent v{agent.get('current_version')}")
    if not c:
        st.info("Aucune fiche contrat. Le propriétaire peut la remplir dans Agent Builder, étape « Fiche contrat ».")
    else:
        pct = round(ac.completeness(c) * 100)
        k1, k2, k3 = st.columns(3)
        k1.metric("Domaine", c.get("domaine") or "—")
        k2.metric("Fiche complète", f"{pct} %")
        k3.metric("Validation", ac.STATUTS.get(c.get("statut_validation"), "—"))
        st.markdown(f"**Périmètre** — {c.get('perimetre') or '—'}")
        st.markdown("**Données lues**")
        st.code(c.get("donnees") or "—", language=None)
        st.markdown(f"**Limites** — {c.get('limites') or '—'}")
        acts = c.get("actions") or []
        ecr = [x["id"] for x in acts if x.get("ecriture")]
        st.markdown(f"**Actions** — {len(acts)} outil(s) ou agent(s)"
                    + (f", dont en écriture : {', '.join(ecr)}" if ecr else ", lecture seule"))
        rev = c.get("date_revue")
        st.caption(f"Responsable métier : {c.get('responsable_metier') or 'à désigner'} · revue : "
                   f"{rev.strftime('%d/%m/%Y') if rev else '—'} · fiche v{c.get('version')} du "
                   f"{str(c.get('created_at'))[:10]} par {c.get('created_by')}")
        if ac.review_overdue(c):
            st.warning("Date de revue dépassée.")
        miss = ac.missing(c)
        if miss:
            st.caption("À compléter : " + ", ".join(miss))
    st.markdown(f"**Indicateurs ({DAYS} derniers jours)**")
    try:
        k = state.agent_kpis(DAYS).get(agent["agent_id"])
    except Exception as e:  # noqa: BLE001
        st.error(f"Indicateurs indisponibles : {e}")
        return
    if not k:
        st.caption("Aucune utilisation sur la période.")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Conversations", k["conversations"])
    m2.metric("Questions", k["questions"])
    m3.metric("Succès des outils", "—" if k["taux_succes_outils"] is None else f"{round(k['taux_succes_outils'] * 100)} %")
    m4.metric("Temps de réponse moyen", _fmt_ms(k["latence_moy_ms"]))
    st.caption(f"{k['appels_outils']} appel(s) d'outils : {k['appels_succes']} succès, {k['appels_erreur']} erreur(s), "
               f"{k['appels_refuse']} refus · {k['jours_actifs']} jour(s) actif(s). Seuils de qualité à valider "
               "(phase 0) : aucun objectif n'est appliqué.")


def open_sheet(agent: dict) -> None:
    """Affiche la fiche dans une fenêtre (st.dialog), sinon dans la page."""
    dlg = getattr(st, "dialog", None)
    if dlg:
        dlg("Fiche produit", width="large")(render_sheet)(agent)
    else:
        with st.container(border=True):
            render_sheet(agent)
