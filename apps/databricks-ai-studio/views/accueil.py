"""Accueil DISCOVERY (tableau de bord), selon la maquette validée."""
import altair as alt
import pandas as pd
import streamlit as st

from ui import dashboard_data, state
from ui.components import STATUS_LABELS, badge, esc, hero
from ui.theme import ACCENT, PRIMARY, SIGNATURE_NAME, SIGNATURE_ROLE

ICON_BY_NAME = {"verified": "verified", "terminal": "terminal", "support_agent": "support_agent",
                "savings": "savings", "description": "description", "policy": "policy",
                "query_stats": "query_stats", "smart_toy": "smart_toy"}


def ico(name: str) -> str:
    return f'<span class="dsc-ico">{esc(name)}</span>'


def kpi_card(col, icon: str, label: str, value, trend: str = ""):
    t = f'<span class="dsc-trend">{esc(trend)}</span>' if trend else ""
    col.markdown(f'<div class="ais-card dsc-kpi">{ico(icon)}<div><div class="ais-kpi-label">{esc(label)}</div>'
                 f'<div class="ais-kpi-value">{esc(value)}{t}</div></div></div>', unsafe_allow_html=True)


hero("Discovery", "Créez, testez et déployez des agents IA au service des métiers de SNCF Réseau")

# -- Indicateurs -------------------------------------------------------------
try:
    stats = state.repository().dashboard_stats()
except Exception as e:  # noqa: BLE001
    st.error(f"Impossible de lire les tables de configuration : {e}")
    st.stop()
try:
    tr = dashboard_data.trends()
except Exception:  # noqa: BLE001 - tendance facultative
    tr = {"agents_mois": 0, "conversations": ""}
c = st.columns(5)
kpi_card(c[0], "smart_toy", "Agents", stats["agents"], f"+{tr['agents_mois']} ce mois" if tr["agents_mois"] else "")
kpi_card(c[1], "rocket_launch", "Publiés", stats["publies"])
kpi_card(c[2], "code", "En développement", stats["brouillons"])
kpi_card(c[3], "stacks", "Outils disponibles", stats["outils"])
kpi_card(c[4], "forum", "Conversations", stats["conversations"], tr["conversations"])

# -- Raccourcis ----------------------------------------------------------------
st.write("")
r = st.columns(5)
if r[0].button("Créer un agent", type="primary", use_container_width=True, key="home_create"):
    st.session_state.pop("builder", None)
    st.switch_page("views/agent_builder.py")
r[1].page_link("views/mes_agents.py", label="Mes agents", icon=":material/work:", use_container_width=True)
r[2].page_link("views/tool_catalog.py", label="Catalogue d'outils", icon=":material/grid_view:", use_container_width=True)
r[3].page_link("views/marketplace.py", label="Marketplace", icon=":material/storefront:", use_container_width=True)
r[4].page_link("views/monitoring.py", label="Monitoring", icon=":material/bar_chart:", use_container_width=True)
st.write("")

# -- Agents récents et activité ----------------------------------------------
left, right = st.columns([1.15, 1])
with left.container(border=True):
    h1, h2 = st.columns([3, 1])
    h1.markdown('<div class="dsc-section">Mes agents récents</div>', unsafe_allow_html=True)
    h2.page_link("views/mes_agents.py", label="Voir tout")
    agents = state.agents()[:5]
    if agents:
        rows = "".join(
            f"<tr><td>{ico(ICON_BY_NAME.get(a.get('icon'), 'smart_toy'))} {esc(a['name'])}</td>"
            f"<td>{badge(a['status'])}</td><td>{esc(a.get('category') or '')}</td>"
            f"<td>{esc(str(a.get('updated_at') or '')[:16].replace('T', ' '))}</td></tr>" for a in agents)
        st.markdown('<table class="dsc-table"><tr><th>Agent</th><th>Statut</th><th>Catégorie</th>'
                    f'<th>Dernière mise à jour</th></tr>{rows}</table>', unsafe_allow_html=True)
    else:
        st.info("Aucun agent pour l'instant.")

with right.container(border=True):
    st.markdown('<div class="dsc-section">Activité des 7 derniers jours</div>', unsafe_allow_html=True)
    try:
        df = pd.DataFrame(dashboard_data.activity_7_days())
        df["jour"] = pd.to_datetime(df["jour"])
        base = alt.Chart(df).encode(x=alt.X("jour:T", title=None, axis=alt.Axis(format="%d %b", tickCount=7)),
                                    y=alt.Y("conversations:Q", title="Conversations"))
        chart = (base.mark_area(color=ACCENT, opacity=0.15)
                 + base.mark_line(color=ACCENT, strokeWidth=2.5)
                 + base.mark_point(color=PRIMARY, filled=True, size=45))
        st.altair_chart(chart.properties(height=210), use_container_width=True)
    except Exception as e:  # noqa: BLE001
        st.warning(f"Activité indisponible : {e}")

# -- Parcours guidés, accès rapides, signature -------------------------------
st.write("")
g, q, s = st.columns([1.2, 1.2, 0.7])
with g.container(border=True):
    st.markdown('<div class="dsc-section">Parcours guidés</div>', unsafe_allow_html=True)
    p = st.columns(3)
    p[0].page_link("views/agent_builder.py", label="Créer un agent étape par étape", icon=":material/play_circle:",
                   use_container_width=True)
    p[1].page_link("views/knowledge_studio.py", label="Connecter une source de données", icon=":material/database:",
                   use_container_width=True)
    p[2].page_link("views/marketplace.py", label="Publier dans la Marketplace", icon=":material/storefront:",
                   use_container_width=True)
with q.container(border=True):
    st.markdown('<div class="dsc-section">Accès rapides métier</div>', unsafe_allow_html=True)
    qa = st.columns(3)
    QUICK = [("Qualité de données", {"category": "Qualité des données"}),
             ("Incidents & REX", {"query": "incident"}),
             ("Gestion d'actifs", {"query": "actif"})]
    for col, (label, flt) in zip(qa, QUICK):
        if col.button(label, key=f"quick_{label}", use_container_width=True):
            st.session_state["marketplace_filter"] = flt
            st.switch_page("views/marketplace.py")
with s:
    st.markdown(f'<div class="dsc-sign"><small>{esc(SIGNATURE_ROLE)}</small><b>{esc(SIGNATURE_NAME)}</b></div>',
                unsafe_allow_html=True)
