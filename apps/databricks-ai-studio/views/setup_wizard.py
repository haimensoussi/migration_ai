"""Setup Wizard : configuration initiale de l'organisation courante en 6 étapes (Streamlit 1.38).

Chaque étape est validée et enregistrée côté serveur (SetupWizard -> TenantService -> saas_settings).
Les contrôles de l'étape Validation s'exécutent avec le jeton de l'utilisateur.
"""
import streamlit as st

from backend.saas.models import SaasError
from backend.saas.setup_checks import DatabricksChecker
from backend.saas.setup_wizard import DATA_STEPS, LANGUAGES, MODULES, STEPS, SetupWizard
from ui import state
from ui.components import error_box
from ui.saas_context import ROLE_LABELS, current_context, identity_or_stop

S = st.session_state
identity = identity_or_stop()
svc = state.tenant_service()
wiz = SetupWizard(svc)
LABELS = dict(STEPS)
STATUS_ICON = {"ok": "✅", "echec": "❌", "erreur": "⚠️", "avertissement": "ℹ️"}
STATUS_LABEL = {"ok": "Conforme", "echec": "Échec", "erreur": "Erreur technique", "avertissement": "Avertissement"}

st.title("Setup Wizard")
try:
    ctx, _ = current_context(identity)
except Exception as e:  # noqa: BLE001
    error_box("Lecture des organisations impossible", e)
    st.stop()
if not ctx:
    st.info("Aucune organisation active : le Setup Wizard s'applique à l'organisation sélectionnée.")
    st.stop()
if not ctx.can("settings.read"):
    st.warning("Votre rôle ne permet pas de consulter la configuration de l'organisation.")
    st.stop()

try:
    wst = wiz.state(ctx)
except SaasError as e:
    st.error(str(e))
    st.stop()
can_edit = ctx.can("settings.manage")
st.caption(f"Organisation {ctx.tenant.name} · configuration enregistrée à chaque étape"
           + ("" if can_edit else " · lecture seule (rôle sans gestion des paramètres)"))

if msg := S.pop("wiz_flash", None):
    st.success(msg)
if wst["active"]:
    st.success(f"Organisation activée le {wst['activated_at'][:16].replace('T', ' ')} par {wst['activated_by']}.")
    if wst["changed_since_activation"]:
        st.warning("Modifié depuis l'activation : " + ", ".join(LABELS[k] for k in wst["changed_since_activation"])
                   + ". Relancez les contrôles de l'étape Validation.")

done = set(wst["done"])
st.progress(len(done) / len(DATA_STEPS), text=f"{len(done)} étape(s) sur {len(DATA_STEPS)} enregistrée(s)"
            + (" · activée" if wst["active"] else ""))

ids = [k for k, _ in STEPS]
reachable = [k for i, k in enumerate(ids) if k in done or k == wst["next"] or (i and ids[i - 1] in done)]
if "wiz_goto" in S:   # étape suivante demandée après un enregistrement (avant création du widget)
    S["wiz_step"] = S.pop("wiz_goto")
S.setdefault("wiz_step", wst["next"])
if S["wiz_step"] not in reachable:
    S["wiz_step"] = wst["next"]
step = st.radio("Étape", reachable, horizontal=True, key="wiz_step",
                format_func=lambda k: f"{ids.index(k) + 1}. {LABELS[k]}" + (" ✓" if k in done else ""))
saved = wst["steps"].get(step) or {}


def save(data: dict):
    try:
        wiz.save_step(ctx, step, data)
    except SaasError as e:
        st.error(str(e))
        return
    except Exception as e:  # noqa: BLE001
        error_box("Enregistrement impossible", e)
        return
    nxt = ids[ids.index(step) + 1]
    S["wiz_flash"] = f"Étape « {LABELS[step]} » enregistrée."
    S["wiz_goto"] = nxt
    st.rerun()


if step != "validation":
    with st.form(f"wiz_{step}"):
        if step == "organisation":
            d = {"display_name": st.text_input("Nom affiché", saved.get("display_name", ctx.tenant.name)),
                 "contact_email": st.text_input("E-mail de contact de l'administrateur",
                                                saved.get("contact_email", ctx.tenant.admin_email)),
                 "language": st.selectbox("Langue", LANGUAGES, LANGUAGES.index(saved.get("language", "fr")),
                                          format_func={"fr": "Français", "en": "English"}.get),
                 "timezone": st.text_input("Fuseau horaire (IANA)", saved.get("timezone", "Europe/Paris"))}
        elif step == "infrastructure":
            st.caption(f"Schéma de données dédié : {ctx.tenant.data_schema} "
                       f"({ctx.tenant.data_schema_status.replace('_', ' ')}) — géré par la plateforme.")
            d = {"warehouse_id": st.text_input("Identifiant de l'entrepôt SQL",
                                               saved.get("warehouse_id", state.settings().warehouse_id)),
                 "max_rows": st.number_input("Lignes maximum par requête d'agent", 10, 5000,
                                             int(saved.get("max_rows", state.settings().max_rows))),
                 "sql_timeout_s": st.number_input("Délai maximum d'une requête (s)", 10, 600,
                                                  int(saved.get("sql_timeout_s", state.settings().sql_timeout_s)))}
        elif step == "ia":
            try:
                options = state.chat_endpoints()
            except Exception as e:  # noqa: BLE001
                options = []
                st.warning(f"Liste des endpoints indisponible ({e}) : saisissez le nom.")
            default = saved.get("default_endpoint", state.settings().default_model)
            if options:
                opts = options if default in options else [default] + options
                d_ep = st.selectbox("Modèle par défaut (endpoint Model Serving)", opts, opts.index(default))
                allowed = st.multiselect("Autres modèles autorisés", options,
                                         [e for e in saved.get("allowed_endpoints", []) if e in options and e != default])
            else:
                d_ep = st.text_input("Modèle par défaut (endpoint Model Serving)", default)
                allowed = st.text_input("Autres modèles autorisés (séparés par des virgules)",
                                        ", ".join(e for e in saved.get("allowed_endpoints", []) if e != default))
            d = {"default_endpoint": d_ep, "allowed_endpoints": allowed,
                 "temperature": st.slider("Température", 0.0, 1.0, float(saved.get("temperature", 0.2)), 0.05),
                 "max_tokens": st.number_input("Jetons de sortie maximum", 256, 32000, int(saved.get("max_tokens", 4096)))}
        elif step == "securite":
            roles = [r for r, ro in sorted(svc.roles().items(), key=lambda x: -x[1].rank) if r != "owner"]
            st.dataframe([{"Rôle": ROLE_LABELS.get(r, r), "Permissions": ", ".join(sorted(ro.permissions))}
                          for r, ro in sorted(svc.roles().items(), key=lambda x: -x[1].rank)],
                         hide_index=True, use_container_width=True)
            cur = saved.get("default_member_role", "user")
            d = {"default_member_role": st.selectbox("Rôle par défaut des nouveaux membres", roles,
                                                     roles.index(cur) if cur in roles else 0,
                                                     format_func=lambda r: ROLE_LABELS.get(r, r)),
                 "allowed_domains": st.text_input("Domaines e-mail autorisés (séparés par des virgules)",
                                                  ", ".join(saved.get("allowed_domains", [ctx.tenant.admin_email.split("@")[-1]])),
                                                  help="Appliqué côté serveur à chaque ajout de membre."),
                 "write_approval": st.checkbox("Validation humaine obligatoire avant toute écriture par un agent",
                                               saved.get("write_approval", True))}
        else:  # modules
            d = {}
            for m, (label, prereq) in MODULES.items():
                d[m] = st.checkbox(label, saved.get(m, m in ("agent_studio", "agent_marketplace", "tool_marketplace")),
                                   help=prereq or None)
        if st.form_submit_button("Enregistrer et continuer", type="primary", disabled=not can_edit):
            save(d)
    if saved.get("_saved_at"):
        st.caption(f"Dernière modification le {saved['_saved_at'][:16].replace('T', ' ')} par {saved.get('_saved_by')}")
else:
    st.markdown("Les contrôles vérifient les étapes, l'entrepôt, les modèles et le schéma avec **vos** droits Databricks. "
                "Seuls les contrôles bloquants empêchent l'activation.")

    def checker():
        w, sql, _ = state.user_session()
        return DatabricksChecker(w, sql)

    c1, c2 = st.columns(2)
    run_checks = c1.button("Lancer les contrôles", use_container_width=True)
    activate = c2.button("Activer l'organisation", type="primary", use_container_width=True, disabled=not can_edit)
    try:
        if activate:
            S["wiz_checks"] = wiz.activate(ctx, checker())
            S["wiz_flash"] = "Organisation activée."
            st.rerun()
        if run_checks:
            S["wiz_checks"] = wiz.checks(ctx, checker())
    except SaasError as e:
        st.error(str(e))
        try:
            S["wiz_checks"] = wiz.checks(ctx, checker())
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        error_box("Contrôles impossibles", e)
    if S.get("wiz_checks"):
        st.dataframe([{"": STATUS_ICON[c.status], "Contrôle": c.label, "Résultat": STATUS_LABEL[c.status],
                       "Bloquant": "oui" if c.blocking else "non", "Détail": c.detail} for c in S["wiz_checks"]],
                      hide_index=True, use_container_width=True)
