import streamlit as st

# Palette DISCOVERY (à aligner sur la charte officielle SNCF Réseau si des codes couleur sont fournis)
NAVY, VIOLET, LIGHT = "#0B1F3A", "#6D28D9", "#F4F5FA"
APP_NAME, APP_TAGLINE = "DISCOVERY", "SNCF Réseau"
SIGNATURE = "Solution Architecte — Haimen SOUSSI"

CSS = f"""
<style>
[data-testid="stSidebar"] {{ background: {NAVY}; }}
[data-testid="stSidebar"] * {{ color: #E8ECF5 !important; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: rgba(109,40,217,.35); border-radius: 8px; }}
/* --- Masquage visuel des éléments natifs Streamlit (le fonctionnement interne est conservé) --- */
[data-testid="stToolbar"], [data-testid="stStatusWidget"], [data-testid="stDecoration"],
[data-testid="stAppDeployButton"], .stDeployButton, #MainMenu {{ display: none !important; }}
footer, [data-testid="stFooter"] {{ display: none !important; }}
/* En-tête invisible mais le bouton de réouverture du menu latéral reste accessible */
[data-testid="stHeader"] {{ background: transparent !important; height: 0 !important; visibility: hidden; }}
[data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {{ visibility: visible !important; }}
/* Marges réduites en haut de page */
.block-container, [data-testid="stMainBlockContainer"] {{ padding-top: 1.2rem !important; max-width: 1250px; }}
[data-testid="stSidebarHeader"] {{ height: 1rem; }}
/* Marque DISCOVERY en tête du menu latéral */
[data-testid="stSidebarNav"]::before {{
    content: "{APP_NAME}\\A{APP_TAGLINE}"; white-space: pre; display: block; padding: 6px 16px 14px 16px;
    margin-bottom: 8px; border-bottom: 1px solid rgba(232,236,245,.18); color: #FFFFFF;
    font-weight: 800; font-size: 1.35rem; letter-spacing: .08em; line-height: 1.35; }}
.ais-signature {{ position: fixed; right: 18px; bottom: 10px; z-index: 999; font-size: .78rem; color: #5B6478;
                 background: rgba(255,255,255,.85); padding: 2px 10px; border-radius: 999px; }}
.ais-card {{ background: #fff; border: 1px solid #E3E6EF; border-radius: 14px; padding: 18px 20px;
            box-shadow: 0 1px 3px rgba(11,31,58,.06); height: 100%; }}
.ais-kpi-label {{ color: #5B6478; font-size: .85rem; }}
.ais-kpi-value {{ color: {NAVY}; font-size: 1.9rem; font-weight: 700; }}
.ais-title {{ color: {NAVY}; font-weight: 700; font-size: 1.05rem; margin-bottom: 4px; }}
.ais-muted {{ color: #5B6478; font-size: .88rem; }}
.ais-badge {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .75rem; font-weight: 600; }}
.ais-publie {{ background: #E7F6EC; color: #1B7F3B; }}
.ais-brouillon {{ background: #FFF4E0; color: #9A5B00; }}
.ais-planifie, .ais-indisponible {{ background: #EEF0F5; color: #5B6478; }}
.ais-hero {{ background: linear-gradient(120deg, {NAVY} 0%, {VIOLET} 100%); color: #fff; border-radius: 16px;
            padding: 26px 28px; margin-bottom: 18px; }}
.ais-hero h2 {{ color: #fff; margin: 0 0 6px 0; }}
</style>
"""


def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)
