"""Équipes d'agents : organigramme, création, gestion (publication réservée aux administrateurs)."""
import streamlit as st

from backend import personas, teams as T
from ui import state

user = state.current_user()
trepo = state.team_repository()
is_admin = trepo.is_admin(user.email)
agents = [a for a in state.agents() if a.get("status") != "archive"]
by_id = {a["agent_id"]: a for a in agents}
all_teams = state.teams()
STATUS = {"brouillon": "Brouillon", "publie": "Publiée", "archive": "Archivée"}

st.title("Équipes")
st.caption("Regroupez des agents autour d'une mission. @équipe envoie la question au chef d'équipe, qui consulte "
           "les membres et rend une synthèse. " + ("Vous êtes administrateur des équipes : vous pouvez publier."
                                                    if is_admin else "La publication est faite par un administrateur."))


def label(aid: str) -> str:
    a = by_id.get(aid)
    if not a:
        return f"(agent {aid[:8]} introuvable)"
    return f"@{a.get('handle') or '?'} · {personas.display(a)}" + ("" if a.get("status") == "publie" else " (brouillon)")


def team_form(prefix: str, team: dict | None) -> tuple[dict, str]:
    t = T.normalize(team or {})
    c1, c2, c3 = st.columns([3, 2, 2])
    name = c1.text_input("Nom de l'équipe", t["name"], max_chars=T.MAX_NAME, key=f"{prefix}_name",
                         help="Ex. Qualité des données")
    handle = c2.text_input("Nom d'appel (@)", t["handle"] if team else T.normalize({"name": name})["handle"],
                           max_chars=20, key=f"{prefix}_handle_{name if not team else ''}")
    filiere = c3.selectbox("Filière", T.FILIERES, index=T.FILIERES.index(t["filiere"]), key=f"{prefix}_fil")
    mission = st.text_input("Mission (une phrase, affichée dans la liste @)", t["mission"], max_chars=T.MAX_MISSION,
                            key=f"{prefix}_mission")
    d1, d2 = st.columns([3, 2])
    owner_h = d1.text_input("Responsable humain (Data Owner / Data Steward)", t["human_owner"],
                            placeholder="prenom.nom@sncf.fr — vide = à désigner", key=f"{prefix}_owner")
    icon = d2.selectbox("Icône", T.ICONS, index=T.ICONS.index(t["icon"]), key=f"{prefix}_icon",
                        format_func=lambda x: x.replace("_", " "))
    eligible = [a["agent_id"] for a in agents if not T.is_coordinator(a)]
    members = st.multiselect("Membres", eligible, default=[m for m in t["members"] if m in eligible],
                             format_func=label, key=f"{prefix}_members", max_selections=T.MAX_MEMBERS)
    primary = st.multiselect("Équipe principale de ces membres", members,
                             default=[m for m in (t["primary"] if team else members) if m in members],
                             format_func=label, key=f"{prefix}_primary",
                             help="L'équipe est affichée sur la fiche de ces agents.")
    coords = [a["agent_id"] for a in agents if T.is_coordinator(a)]
    choices = ["aucun", "existant", "nouveau"]
    cur = "existant" if t["lead_agent_id"] else "aucun"
    mode = st.radio("Chef d'équipe", choices, index=choices.index(cur), horizontal=True, key=f"{prefix}_mode",
                    format_func={"aucun": "Aucun (un seul membre)", "existant": "Agent coordinateur existant",
                                 "nouveau": "Créer un chef (brouillon à relire)"}.get)
    lead = None
    if mode == "existant":
        if coords:
            lead = st.selectbox("Coordinateur", coords, format_func=label, key=f"{prefix}_lead",
                                index=coords.index(t["lead_agent_id"]) if t["lead_agent_id"] in coords else 0)
        else:
            st.info("Aucun agent coordinateur : choisissez « Créer un chef ».")
    data = {"team_id": (team or {}).get("team_id"), "name": name, "handle": handle, "filiere": filiere,
            "mission": mission, "human_owner": owner_h, "icon": icon, "members": members, "primary": primary,
            "lead_agent_id": lead}
    n = T.normalize(data)
    shown = f"@{n['handle']} · Équipe {n['name'] or '…'} · {len(n['members'])} agent(s)"
    st.caption(f"Aperçu dans la liste @ : {shown} — {n['mission'] or 'mission à préciser'}")
    if mode == "nouveau" and len(members) < 2:
        st.caption("Un chef n'est utile qu'à partir de deux membres.")
    return data, mode


def do_save(data: dict, mode: str, publish: bool, publish_lead: bool) -> None:
    try:
        if mode == "nouveau":
            check = T.normalize({**data, "lead_agent_id": "en-creation"})
            errs = [e for e in T.validate(check, agents, all_teams) if "Chef d'équipe introuvable" not in e]
            if errs:
                raise ValueError(" ".join(errs))
            data = {**data, "lead_agent_id": trepo.create_lead(data, user.email)}
            state.refresh_data()
            if publish_lead and is_admin:
                state.repository().set_status(data["lead_agent_id"], "publie")
        tid = trepo.save(data, user.email)
        msg = "Équipe enregistrée en brouillon."
        if publish:
            trepo.set_status(tid, "publie", user.email)
            msg = "Équipe enregistrée et publiée."
        state.refresh_data()
        st.session_state["team_flash"] = msg + (" Chef créé en brouillon : relisez-le dans Agent Builder."
                                                if mode == "nouveau" and not publish_lead else "")
        st.rerun()
    except (ValueError, PermissionError) as e:
        st.error(str(e))


if st.session_state.get("team_flash"):
    st.success(st.session_state.pop("team_flash"))

tab_org, tab_new, tab_mine = st.tabs(["Organigramme", "Créer une équipe", "Mes équipes"])

with tab_org:
    visible = [t for t in all_teams if t["status"] == "publie" or t.get("owner") == user.email or is_admin]
    if not visible:
        st.info("Aucune équipe pour l'instant. Créez la première dans l'onglet « Créer une équipe ».")
    for fil in T.FILIERES:
        group = [t for t in visible if (t.get("filiere") or "Transverse") == fil]
        if not group:
            continue
        st.subheader(fil)
        for t in group:
            n = T.normalize(t)
            with st.container(border=True):
                h1, h2 = st.columns([4, 1])
                h1.markdown(f":material/{n['icon']}: **Équipe {n['name']}** · `@{n['handle']}`")
                h2.caption(STATUS.get(t["status"], t["status"]))
                st.write(n["mission"] or "_Mission à préciser._")
                st.caption("Responsable humain : " + (n["human_owner"] or "à désigner"))
                if n["lead_agent_id"]:
                    st.markdown(f"Chef d'équipe : {label(n['lead_agent_id'])}")
                for m in n["members"]:
                    a = by_id.get(m, {})
                    st.markdown(f"- {label(m)}" + (f" — {a.get('tagline')}" if a.get("tagline") else ""))
                try:
                    act = trepo.activity(([n["lead_agent_id"]] if n["lead_agent_id"] else []) + n["members"])
                    rate = f"{100 * act['succes'] / act['appels']:.0f} %" if act["appels"] else "—"
                    st.caption(f"30 derniers jours : {act['conversations']} conversation(s), {act['appels']} appel(s) "
                               f"d'outils, succès {rate}")
                except Exception:  # noqa: BLE001
                    st.caption("Activité indisponible.")

with tab_new:
    data, mode = team_form("new", None)
    c1, c2, c3 = st.columns([2, 2, 3])
    if c1.button("Enregistrer en brouillon", type="primary", key="new_save"):
        do_save(data, mode, False, False)
    if is_admin:
        pl = c3.checkbox("Publier aussi le chef créé", value=False, key="new_pl") if mode == "nouveau" else False
        if c2.button("Enregistrer et publier", key="new_pub"):
            do_save(data, mode, True, pl)

with tab_mine:
    mine = [t for t in all_teams if t.get("owner") == user.email or is_admin]
    if not mine:
        st.info("Vous n'avez pas encore d'équipe.")
    else:
        tid = st.selectbox("Équipe", [t["team_id"] for t in mine], key="mine_sel",
                           format_func=lambda x: next(f"Équipe {t['name']} (@{t['handle']}) — {STATUS[t['status']]}"
                                                      for t in mine if t["team_id"] == x))
        team = next(t for t in mine if t["team_id"] == tid)
        data, mode = team_form(f"edit_{tid}", team)
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Enregistrer", type="primary", key=f"es_{tid}"):
            do_save(data, mode, False, False)
        if is_admin and team["status"] != "publie" and b2.button("Publier", key=f"ep_{tid}"):
            try:
                trepo.set_status(tid, "publie", user.email)
                state.refresh_data()
                st.session_state["team_flash"] = "Équipe publiée."
                st.rerun()
            except (ValueError, PermissionError) as e:
                st.error(str(e))
        if team["status"] == "publie" and b3.button("Retirer (brouillon)", key=f"er_{tid}"):
            trepo.set_status(tid, "brouillon", user.email)
            state.refresh_data()
            st.rerun()
        if b4.button("Archiver", key=f"ea_{tid}"):
            trepo.set_status(tid, "archive", user.email)
            state.refresh_data()
            st.session_state["team_flash"] = "Équipe archivée : ses agents sont conservés."
            st.rerun()
        if team["status"] == "publie" and not is_admin:
            st.caption("Toute modification repasse l'équipe en brouillon jusqu'à sa republication par un administrateur.")
        with st.expander("Historique des modifications"):
            st.dataframe(trepo.history(tid), use_container_width=True, hide_index=True)
