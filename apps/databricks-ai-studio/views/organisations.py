"""Organisations : consultation et gestion de l'organisation courante ; création réservée à la plateforme.

Toutes les décisions de droits sont prises par TenantService (côté serveur) ; l'interface masque seulement les
actions inutiles, elle n'accorde rien.
"""
import streamlit as st

from backend.saas.models import PLANS, SaasError
from ui import state
from ui.components import error_box
from ui.saas_context import ROLE_LABELS, current_context, identity_or_stop, platform_admin

identity = identity_or_stop()
svc = state.tenant_service()

st.title("Organisations")
st.caption("Entreprises clientes de DISCOVERY AI Studio. Configuration dans les tables saas_* ; données métier "
           "dans un schéma dédié à chaque organisation.")


def run(label: str, fn, success: str | None = None):
    """Exécute une action du service ; affiche l'erreur métier telle quelle, l'erreur technique avec son contexte."""
    try:
        out = fn()
        if success:
            st.session_state["org_flash"] = success
            st.rerun()
        return out
    except SaasError as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        error_box(label, e)
    return None


if msg := st.session_state.pop("org_flash", None):
    st.success(msg)

try:
    ctx, mine = current_context(identity)
except Exception as e:  # noqa: BLE001
    error_box("Lecture des organisations impossible", e)
    st.stop()

is_platform = platform_admin(svc, identity, ctx)   # masqué en mode aperçu
tabs = st.tabs(["Mon organisation", "Plateforme"] if is_platform else ["Mon organisation"])

# -- Organisation courante ---------------------------------------------------------------------------------
with tabs[0]:
    if not ctx:
        st.info("Aucune organisation active. " + ("Créez-en une dans l'onglet Plateforme." if is_platform else
                "Demandez à un administrateur de la plateforme de vous ajouter."))
    else:
        t = run("Lecture de l'organisation", lambda: svc.get_tenant(ctx))
        if t:
            a, b, c = st.columns(3)
            a.metric("Organisation", t.name, t.slug, delta_color="off")
            b.metric("Offre", t.plan)
            c.metric("Mon rôle", ROLE_LABELS.get(ctx.role.role_id, ctx.role.role_id))
            st.caption(f"Identifiant {t.tenant_id} · créée le {t.created_at[:10]} par {t.created_by} · schéma "
                       f"{t.data_schema} ({t.data_schema_status.replace('_', ' ')})")

        if ctx.can("users.read"):
            st.subheader("Membres")
            members = run("Lecture des membres", lambda: svc.list_members(ctx)) or []
            st.dataframe([{"E-mail": m.user_email, "Rôle": ROLE_LABELS.get(m.role_id, m.role_id),
                           "Statut": m.status, "Ajouté par": m.added_by, "Depuis": m.created_at[:10]}
                          for m in members], hide_index=True, use_container_width=True)
            if ctx.can("users.manage"):
                allowed = [r for r, role in sorted(svc.roles().items(), key=lambda x: -x[1].rank)
                           if role.rank <= ctx.role.rank]
                with st.form("org_add_member", clear_on_submit=True):
                    st.markdown("**Ajouter ou modifier un membre**")
                    f1, f2 = st.columns([3, 1])
                    email = f1.text_input("E-mail (identité Databricks)")
                    role = f2.selectbox("Rôle", allowed, index=len(allowed) - 1 if allowed else 0,
                                        format_func=lambda r: ROLE_LABELS.get(r, r))
                    if st.form_submit_button("Enregistrer le membre", type="primary"):
                        run("Ajout du membre", lambda: svc.add_member(ctx, email, role), f"Membre {email} enregistré.")
                others = [m for m in members if m.user_email != identity.email]
                if others:
                    g1, g2, g3 = st.columns([3, 1, 1])
                    target = g1.selectbox("Membre", [m.user_email for m in others], key="org_target")
                    if g2.button("Désactiver", use_container_width=True):
                        run("Désactivation", lambda: svc.set_member_status(ctx, target, "desactive"),
                            f"{target} désactivé.")
                    if g3.button("Réactiver", use_container_width=True):
                        run("Réactivation", lambda: svc.set_member_status(ctx, target, "actif"), f"{target} réactivé.")

        if ctx.can("settings.read"):
            with st.expander("Paramètres de l'organisation"):
                settings = run("Lecture des paramètres", lambda: svc.get_settings(ctx)) or {}
                st.json(settings) if settings else st.caption("Aucun paramètre (le Setup Wizard les renseignera).")

        if ctx.can("audit.read"):
            with st.expander("Journal d'audit (100 dernières actions)"):
                log = run("Lecture de l'audit", lambda: svc.audit_log(ctx, 100)) or []
                st.dataframe(log, hide_index=True, use_container_width=True)

# -- Plateforme -----------------------------------------------------------------------------------------
if is_platform:
    with tabs[1]:
        st.subheader("Créer une organisation")
        with st.form("org_create", clear_on_submit=False):
            c1, c2 = st.columns(2)
            name = c1.text_input("Raison sociale")
            slug = c2.text_input("Code court", help="3 à 31 caractères : minuscule en tête, puis a-z, 0-9 ou _. "
                                                    "Sert au nom du schéma dédié ; non modifiable.")
            c3, c4 = st.columns(2)
            admin = c3.text_input("E-mail du propriétaire", help="Identité Databricks du premier administrateur.")
            plan = c4.selectbox("Offre", PLANS)
            if st.form_submit_button("Créer l'organisation", type="primary"):
                run("Création", lambda: svc.create_tenant(identity, name, slug, admin, plan),
                    f"Organisation « {name} » créée. Provisionnez son schéma de données ci-dessous.")

        st.subheader("Toutes les organisations")
        all_t = run("Liste des organisations", lambda: svc.list_all_tenants(identity)) or []
        st.dataframe([{"Nom": t.name, "Code": t.slug, "Statut": t.status, "Offre": t.plan, "Propriétaire": t.admin_email,
                       "Schéma": t.data_schema, "Provisionnement": t.data_schema_status, "Créée le": t.created_at[:10]}
                      for t in all_t], hide_index=True, use_container_width=True)
        if all_t:
            by_id = {t.tenant_id: t for t in all_t}
            tid = st.selectbox("Organisation à administrer", list(by_id), format_func=lambda i: f"{by_id[i].name} ({by_id[i].slug})")
            sel = by_id[tid]
            b1, b2, b3 = st.columns(3)
            if sel.status == "actif":
                if b1.button("Suspendre", use_container_width=True):
                    run("Suspension", lambda: svc.set_tenant_status(identity, tid, "suspendu"), f"{sel.name} suspendue.")
            elif b1.button("Réactiver", use_container_width=True, key="org_reactivate"):
                run("Réactivation", lambda: svc.set_tenant_status(identity, tid, "actif"), f"{sel.name} réactivée.")
            if b2.button("Rétablir le propriétaire", use_container_width=True,
                         help="Reprise si la création a été interrompue avant l'ajout du propriétaire."):
                run("Reprise", lambda: svc.ensure_owner(identity, tid), "Propriétaire vérifié.")
            if sel.data_schema_status != "provisionne" and b3.button("Marquer le schéma provisionné",
                                                                     use_container_width=True):
                run("Provisionnement", lambda: svc.mark_schema_provisioned(identity, tid), "Schéma marqué provisionné.")
            if sel.data_schema_status != "provisionne":
                st.markdown("**Script de provisionnement** (à exécuter par un administrateur Unity Catalog ; "
                            "l'App n'a pas le droit de créer des schémas)")
                sql = run("Script", lambda: svc.provisioning_sql(identity, tid))
                if sql:
                    st.code(sql, language="sql")
