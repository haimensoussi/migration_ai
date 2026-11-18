"""Tableau de bord SaaS DISCOVERY AI Studio : organisations de l'utilisateur et indicateurs réels (tables saas_*)."""
import streamlit as st

from backend.saas.models import SaasError
from ui import state
from ui.components import error_box, hero, kpi
from ui.saas_context import ROLE_LABELS, current_context, identity_or_stop, platform_admin

hero("DISCOVERY AI Studio", "Plateforme multi-entreprises de création et d'exécution d'agents IA")

identity = identity_or_stop()
svc = state.tenant_service()
try:
    ctx, mine = current_context(identity)
except Exception as e:  # noqa: BLE001
    error_box("Lecture des organisations impossible", e)
    st.stop()

c1, c2, c3, c4 = st.columns(4)
kpi(c1, "Mes organisations", len(mine), "adhésions actives")
kpi(c2, "Organisation courante", ctx.tenant.name if ctx else "—", ctx.tenant.slug if ctx else "aucune")
kpi(c3, "Mon rôle", ROLE_LABELS.get(ctx.role.role_id, ctx.role.role_id) if ctx else "—",
    f"{len(ctx.role.permissions)} permissions" if ctx else "")
members = None
if ctx and ctx.can("users.read"):
    try:
        members = [m for m in svc.list_members(ctx) if m.status == "actif"]
    except SaasError as e:
        st.warning(str(e))
kpi(c4, "Membres actifs", len(members) if members is not None else "—",
    "de l'organisation" if members is not None else "rôle sans lecture des membres")

if platform_admin(svc, identity, ctx):   # masqué en mode aperçu
    st.subheader("Plateforme")
    try:
        n = svc.platform_counts(identity)
        p1, p2, p3 = st.columns(3)
        kpi(p1, "Organisations", n.get("organisations", 0), "toutes")
        kpi(p2, "Actives", n.get("actives", 0), "non suspendues")
        kpi(p3, "Adhésions actives", n.get("membres", 0), "toutes organisations")
    except Exception as e:  # noqa: BLE001
        error_box("Indicateurs plateforme indisponibles", e)

st.subheader("Mes organisations")
if not mine:
    st.info("Vous n'êtes membre d'aucune organisation. Un administrateur de la plateforme doit vous y ajouter.")
for t, m in mine:
    with st.container(border=True):
        a, b = st.columns([3, 1])
        a.markdown(f"**{t.name}** · `{t.slug}` · offre {t.plan}")
        a.caption(f"Schéma de données : {t.data_schema} ({t.data_schema_status.replace('_', ' ')})")
        b.markdown(f"{ROLE_LABELS.get(m.role_id, m.role_id)}  \n{'Active' if t.status == 'actif' else 'Suspendue'}")

st.page_link("views/organisations.py", label="Gérer les organisations", icon=":material/domain:")
st.caption(f"Connecté : {identity.email} (identité vérifiée, source {identity.source})")
