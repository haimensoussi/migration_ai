import streamlit as st

NAVY, VIOLET, LIGHT = "#0B1F3A", "#6D28D9", "#F4F5FA"

CSS = f"""
<style>
[data-testid="stSidebar"] {{ background: {NAVY}; }}
[data-testid="stSidebar"] * {{ color: #E8ECF5 !important; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: rgba(109,40,217,.35); border-radius: 8px; }}
.block-container {{ padding-top: 2rem; max-width: 1250px; }}
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
