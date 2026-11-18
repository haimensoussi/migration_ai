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
        ctx = svc.resolve(identity, sel)
    except AccessDenied as e:
        st.sidebar.error(str(e))
        return None, mine
    return _preview(svc, ctx), mine


NO_PREVIEW = "__reel__"


def _preview(svc, ctx):
    """Sélecteur « Aperçu en tant que » : rôles inférieurs au rôle réel. Le service applique le rôle à chaque contrôle."""
    S = st.session_state
    lower = [r.role_id for r in sorted(svc.roles().values(), key=lambda r: -r.rank) if r.rank < ctx.role.rank]
    if not lower:
        return ctx
    key = f"saas_preview_{ctx.tenant_id}"
    options = [NO_PREVIEW] + lower
    if S.get(key) not in options:
        S[key] = NO_PREVIEW
    choice = st.sidebar.selectbox("Aperçu en tant que", options, key=key,
                                  format_func=lambda r: "Mon rôle réel" if r == NO_PREVIEW else ROLE_LABELS.get(r, r),
                                  help="Voir l'application avec les droits d'un rôle inférieur. Ne donne jamais plus de "
                                       "droits ; vos droits Databricks restent les vôtres.")
    audited = S.get(f"{key}_audited", NO_PREVIEW)
    try:
        if choice == NO_PREVIEW:
            if audited != NO_PREVIEW:
                svc.stop_preview(svc.resolve(ctx.identity, ctx.tenant_id, preview_role=audited))
                S[f"{key}_audited"] = NO_PREVIEW
            return ctx
        if audited != choice:
            out = svc.start_preview(ctx, choice)          # tracé dans l'audit
            S[f"{key}_audited"] = choice
        else:
            out = svc.resolve(ctx.identity, ctx.tenant_id, preview_role=choice)
    except Exception as e:  # noqa: BLE001
        st.sidebar.error(f"Aperçu impossible : {e}")
        return ctx
    st.warning(f"Mode aperçu : vous voyez l'application en tant que **{ROLE_LABELS.get(choice, choice)}** "
               f"(rôle réel : {ROLE_LABELS.get(ctx.role.role_id, ctx.role.role_id)}). Fonctions plateforme masquées. "
               "Revenez à « Mon rôle réel » dans la barre latérale.", icon=":material/visibility:")
    return out


def in_preview(ctx) -> bool:
    return bool(ctx and ctx.preview)


def platform_admin(svc, identity, ctx) -> bool:
    """Administrateur plateforme, sauf en mode aperçu (on voit l'application comme un client)."""
    return svc.acts_as_platform_admin(identity, ctx)
