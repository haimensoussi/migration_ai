"""Identité graphique DISCOVERY — SNCF Réseau (palette validée à partir de la maquette)."""
from string import Template

import streamlit as st

# Palette (codes estimés depuis la maquette ; à remplacer par les codes officiels de la charte s'ils sont fournis)
PRIMARY = "#B0124F"   # framboise : élément actif, bouton principal, icônes
PLUM = "#4A1942"      # prune foncé : titres, bandeau, signature
ACCENT = "#7A3E9D"    # violet : graphiques, dégradés
BG = "#F6F6F8"
CARD = "#FFFFFF"
BORDER = "#E6E3EA"
TEXT = "#2B1B33"
MUTED = "#6B6475"
NAVY, VIOLET, LIGHT = PLUM, ACCENT, BG   # compatibilité avec les anciens noms

APP_NAME, APP_TAGLINE = "Discovery", "SNCF Réseau"
APP_SUBTITLE = "Plateforme d'Intelligence Artificielle & Agents Métier"
SIGNATURE_ROLE, SIGNATURE_NAME = "Solution Architecte", "Haimen SOUSSI"
SIGNATURE = f"{SIGNATURE_ROLE} — {SIGNATURE_NAME}"

_CSS = Template("""
<style>
/* --- Masquage visuel des éléments natifs Streamlit (le fonctionnement interne est conservé) --- */
[data-testid="stToolbar"], [data-testid="stStatusWidget"], [data-testid="stDecoration"],
[data-testid="stAppDeployButton"], .stDeployButton, #MainMenu { display: none !important; }
footer, [data-testid="stFooter"] { display: none !important; }
[data-testid="stHeader"] { background: transparent !important; height: 0 !important; visibility: hidden; }
[data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] { visibility: visible !important; }
.block-container, [data-testid="stMainBlockContainer"] { padding-top: 1rem !important; max-width: 1320px; }

/* --- Menu latéral clair, élément actif framboise --- */
[data-testid="stSidebar"] { background: $CARD; border-right: 1px solid $BORDER; }
[data-testid="stSidebarHeader"] { height: .5rem; }
[data-testid="stSidebarNav"] a { border-radius: 10px; margin: 2px 6px; }
[data-testid="stSidebarNav"] a span { color: $TEXT; font-weight: 500; }
[data-testid="stSidebarNav"] a:hover { background: #F4E7EE; }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: $PRIMARY; }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: #FFFFFF !important; }
[data-testid="stSidebarNav"]::before {
    content: "SNCF\\ARÉSEAU"; white-space: pre; display: block; text-align: center; padding: 4px 0 14px 0;
    margin: 0 12px 10px 12px; border-bottom: 1px solid $BORDER; color: $PRIMARY; font-weight: 900;
    font-size: 1.15rem; letter-spacing: .12em; line-height: 1.25; }

/* --- En-tête commun --- */
.dsc-top { display: flex; align-items: center; justify-content: space-between; background: $CARD;
           border: 1px solid $BORDER; border-radius: 14px; padding: 10px 18px; margin-bottom: 14px; }
.dsc-top-title { color: $PLUM; font-size: 1.6rem; font-weight: 800; line-height: 1.1; }
.dsc-top-sub { color: $PRIMARY; font-size: .9rem; font-weight: 500; }
.dsc-user { display: flex; align-items: center; gap: 10px; color: $TEXT; font-weight: 600; font-size: .9rem; }
.dsc-avatar { width: 34px; height: 34px; border-radius: 50%; background: $PLUM; color: #fff; display: flex;
              align-items: center; justify-content: center; font-size: .8rem; font-weight: 700; }

/* --- Bandeau --- */
.ais-hero { background: linear-gradient(110deg, $PLUM 0%, #6B2366 45%, $ACCENT 100%); color: #fff;
            border-radius: 16px; padding: 26px 30px; margin-bottom: 16px; }
.ais-hero h2 { color: #fff; margin: 0 0 6px 0; font-size: 2.1rem; font-weight: 800; }
.ais-hero div { font-size: 1.02rem; max-width: 620px; }

/* --- Cartes et indicateurs --- */
.ais-card { background: $CARD; border: 1px solid $BORDER; border-radius: 14px; padding: 14px 16px;
            box-shadow: 0 1px 3px rgba(43,27,51,.06); height: 100%; }
.dsc-kpi { display: flex; gap: 12px; align-items: center; }
.dsc-ico { font-family: 'Material Symbols Rounded'; font-size: 30px; color: $PRIMARY; line-height: 1;
           font-variation-settings: 'FILL' 0, 'wght' 400; }
.ais-kpi-label { color: $TEXT; font-size: .88rem; font-weight: 600; }
.ais-kpi-value { color: $TEXT; font-size: 1.7rem; font-weight: 800; line-height: 1.15; }
.dsc-trend { display: inline-block; margin-left: 8px; padding: 1px 8px; border-radius: 999px; font-size: .72rem;
             font-weight: 700; background: #E6F4EA; color: #2E8B57; vertical-align: middle; }
.ais-title { color: $PLUM; font-weight: 700; font-size: 1.02rem; margin-bottom: 4px; }
.ais-muted { color: $MUTED; font-size: .86rem; }
.dsc-section { color: $PLUM; font-weight: 800; font-size: 1.02rem; margin: 2px 0 8px 0; }

/* --- Badges de statut --- */
.ais-badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .74rem; font-weight: 600; }
.ais-publie { background: #E6F4EA; color: #2E8B57; }
.ais-brouillon { background: #FFF1DD; color: #C26A00; }
.ais-planifie, .ais-indisponible, .ais-archive { background: #EEF0F5; color: $MUTED; }

/* --- Tableau des agents récents --- */
.dsc-table { width: 100%; border-collapse: collapse; font-size: .86rem; }
.dsc-table th { text-align: left; color: $MUTED; font-weight: 600; padding: 6px 6px; border-bottom: 1px solid $BORDER; }
.dsc-table td { padding: 7px 6px; border-bottom: 1px solid #F1EEF3; color: $TEXT; }
.dsc-table td:first-child { font-weight: 700; }

/* --- Liens de page présentés en cartes (raccourcis, parcours) --- */
[data-testid="stPageLink"] a, [data-testid="stPageLink-NavLink"] {
    background: $CARD; border: 1px solid $BORDER; border-radius: 12px; padding: 10px 12px;
    justify-content: center; box-shadow: 0 1px 2px rgba(43,27,51,.05); }
[data-testid="stPageLink"] a:hover, [data-testid="stPageLink-NavLink"]:hover { border-color: $PRIMARY; }
[data-testid="stPageLink"] p, [data-testid="stPageLink-NavLink"] p { color: $TEXT; font-weight: 600; }
.stButton > button { border-radius: 12px; font-weight: 600; min-height: 44px; }

/* --- Carte de signature --- */
.dsc-sign { background: linear-gradient(120deg, $PLUM 0%, #6B2366 100%); color: #fff; border-radius: 14px;
            padding: 18px 16px; text-align: center; height: 100%; display: flex; flex-direction: column;
            justify-content: center; }
.dsc-sign small { opacity: .85; font-size: .8rem; }
.dsc-sign b { font-size: 1.05rem; letter-spacing: .02em; }
</style>
""")

CSS = _CSS.substitute(PRIMARY=PRIMARY, PLUM=PLUM, ACCENT=ACCENT, CARD=CARD, BORDER=BORDER, TEXT=TEXT, MUTED=MUTED)


def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)
