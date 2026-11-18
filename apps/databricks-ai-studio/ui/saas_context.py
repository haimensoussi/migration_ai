"""Organisation courante : choisie parmi les adhésions de l'utilisateur, revérifiée par le service à chaque exécution."""
from __future__ import annotations

import streamlit as st

from backend.saas.models import AccessDenied
from ui import state

ROLE_LABELS = {"owner": "Propriétaire", "admin": "Administrateur", "builder": "Concepteur", "user": "Utilisateur",
               "viewer": "Lecteur"}


def identity_or_stop():
    try:
        return state.saas_identity()
    except Exception as e:  # noqa: BLE001
        st.error(f"Identité non vérifiable, accès au SaaS refusé : {e}")
        st.stop()


def current_context(identity):
    """(contexte ou None, liste (organisation, adhésion)). La sélection n'accorde aucun droit : resolve() décide."""
    svc = state.tenant_service()
    mine = svc.my_tenants(identity)
    active = [(t, m) for t, m in mine if t.status == "actif"]
    if not active:
        return None, mine
    ids = [t.tenant_id for t, _ in active]
    labels = {t.tenant_id: f"{t.name} · {ROLE_LABELS.get(m.role_id, m.role_id)}" for t, m in active}
    sel = st.session_state.get("saas_tenant_id")
    sel = sel if sel in ids else ids[0]
    sel = st.sidebar.selectbox("Organisation", ids, index=ids.index(sel), format_func=lambda i: labels[i])
    st.session_state["saas_tenant_id"] = sel
    try:
        return svc.resolve(identity, sel), mine
    except AccessDenied as e:
        st.sidebar.error(str(e))
        return None, mine
