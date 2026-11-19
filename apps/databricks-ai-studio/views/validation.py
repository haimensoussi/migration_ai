"""Agentic Mesh phase 2 : validation des publications d'agents par le responsable du domaine."""
import pandas as pd
import streamlit as st

from backend import agent_contracts as ac
from backend import publication as pub
from ui import state
from ui.agent_sheet import open_sheet

st.title("Validation")
st.caption("Un agent n'est publié qu'après validation par le responsable de son domaine. Tant qu'aucun "
           "responsable n'est désigné pour un domaine, les administrateurs DISCOVERY valident.")
user = state.current_user()
svc = state.publication_service()

try:
    owners = svc.domain_owners()
    admins = pub.admins_of(state.settings())
    mine = svc.validable_domains(user.email)
except Exception as e:  # noqa: BLE001
    st.error(f"Tables de publication indisponibles : {e}")
    st.stop()

if st.session_state.get("_val_msg"):
    st.success(st.session_state.pop("_val_msg"))

# -- File à valider ---------------------------------------------------------
st.subheader("À valider")
if not mine:
    st.info("Vous n'êtes valideur d'aucun domaine.")
else:
    st.caption("Vos domaines : " + ", ".join(
        f"{d} ({'responsable désigné' if owners.get(d) else 'repli administrateur'})" for d in mine))
    pending = svc.pending_for(user.email)
    by_id = {a["agent_id"]: a for a in state.agents()}
    if not pending:
        st.caption("Aucune demande en attente.")
    for r in pending:
        a = by_id.get(r["agent_id"], {"agent_id": r["agent_id"], "name": r.get("agent_name") or r["agent_id"]})
        stale = str(r.get("agent_current_version")) != str(r.get("agent_version"))
        with st.container(border=True):
            c1, c2 = st.columns([3, 2])
            c1.markdown(f"**{a['name']}** · domaine **{r.get('domaine')}** · version {r.get('agent_version')}")
            c1.caption(f"Soumis par {r.get('requested_by')} le {str(r.get('requested_at'))[:16].replace('T', ' ')} · "
                       f"fiche contrat v{r.get('contract_version') or '—'} complète à "
                       f"{round(float(r.get('contract_completeness') or 0) * 100)} %")
            if stale:
                c1.warning("L'agent a changé depuis la soumission : la demande sera classée obsolète.")
            if (r.get("requested_by") or "").lower() == user.email.lower():
                c1.caption("Vous êtes le demandeur : une validation sera tracée comme auto-validation.")
            b1, b2 = c2.columns(2)
            if b1.button("Fiche", key=f"vf_{r['request_id']}", use_container_width=True):
                open_sheet(a)
            if b2.button("Tester", key=f"vt_{r['request_id']}", use_container_width=True):
                st.session_state["chat_agent_id"] = r["agent_id"]
                st.switch_page("views/chat.py")
            note = c2.text_input("Motif (obligatoire pour refuser)", key=f"vn_{r['request_id']}")
            d1, d2 = c2.columns(2)
            for col, approve, label in ((d1, True, "Valider"), (d2, False, "Refuser")):
                if col.button(label, key=f"v{int(approve)}_{r['request_id']}", type="primary" if approve else "secondary",
                              use_container_width=True):
                    try:
                        s = svc.decide(r["request_id"], user.email, approve, note)
                        state.refresh_data()
                        st.session_state["_val_msg"] = (f"« {a['name']} » : demande "
                                                        f"{pub.LABELS[s].lower()}"
                                                        + (", agent publié." if approve else ", agent repassé en brouillon."))
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(str(e))

# -- Historique (piste d'audit) ---------------------------------------------
st.subheader("Historique des publications")
hist = svc.requests(limit=200)
if hist:
    df = pd.DataFrame([{
        "Agent": h.get("agent_name") or h["agent_id"], "Version": h.get("agent_version"), "Domaine": h.get("domaine") or "—",
        "Statut": pub.LABELS.get(h["status"], h["status"]), "Origine": h.get("origin"),
        "Demandeur": h.get("requested_by"), "Demandé le": str(h.get("requested_at"))[:16].replace("T", " "),
        "Décideur": h.get("decided_by") or "—", "Motif": h.get("decision_note") or "",
        "Auto-validation": "oui" if str(h.get("self_validation")).lower() == "true" else ""} for h in hist])
    st.dataframe(df, hide_index=True, use_container_width=True)
else:
    st.caption("Aucune demande.")

# -- Responsables de domaine ------------------------------------------------
st.subheader("Responsables de domaine")
is_admin = user.email.lower() in admins
st.caption("Désignés par un administrateur DISCOVERY. Un domaine sans responsable est validé par les administrateurs : "
           + (", ".join(sorted(admins)) or "aucun administrateur configuré") + ".")
for d in ac.DOMAINES:
    cur = owners.get(d, [])
    if not is_admin:
        st.markdown(f"**{d}** — " + (", ".join(cur) or "à désigner (repli administrateurs)"))
        continue
    c1, c2 = st.columns([4, 1])
    val = c1.text_input(d, ", ".join(cur), key=f"do_{d}", placeholder="e-mails séparés par des virgules")
    c2.write("")
    if c2.button("Enregistrer", key=f"dos_{d}", use_container_width=True):
        try:
            svc.set_domain_owners(d, val.split(","), user.email)
            st.session_state["_val_msg"] = f"Responsables du domaine {d} enregistrés."
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
