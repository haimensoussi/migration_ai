"""Affichage des indicateurs (render_kpi) et des rapports (generate_report) dans le chat : API Streamlit 1.38."""
import streamlit as st

PER_ROW = 4


def render_kpis(k: dict | None, caption: str = "") -> None:
    if not k:
        return
    st.markdown(f"**{caption + ' · ' if caption else ''}{k['titre']}**")
    items = k.get("indicateurs") or []
    ref = k.get("libelle_reference")
    for start in range(0, len(items), PER_ROW):
        cols = st.columns(min(PER_ROW, len(items) - start))
        for col, it in zip(cols, items[start:start + PER_ROW]):
            delta = it.get("ecart_affiche")
            col.metric(it["libelle"], it["valeur_affichee"],
                       delta=(f"{delta} vs {ref}" if delta and ref else delta), delta_color=k.get("delta_color", "off"))
    with st.expander("Requête et calcul des indicateurs"):
        st.code(k["requete"], language="sql")
        if k.get("format") == "pourcentage":
            st.caption("Valeurs en pourcentage, écarts en points.")
        st.dataframe([{x: it.get(x) for x in ("libelle", "valeur", "reference", "ecart", "ecart_relatif_pct", "tendance")}
                      for it in items], use_container_width=True, hide_index=True)


def render_report(r: dict | None, key: str, caption: str = "") -> None:
    if not r:
        return
    st.markdown(f"**{caption + ' · ' if caption else ''}Rapport : {r['titre']}**")
    name = "".join(ch if ch.isalnum() else "_" for ch in r["titre"])[:60] or "rapport"
    c1, c2 = st.columns(2)
    c1.download_button("Télécharger en HTML", r["html"], file_name=f"{name}.html", mime="text/html",
                       key=f"rh_{key}", use_container_width=True)
    c2.download_button("Télécharger en Markdown", r["markdown"], file_name=f"{name}.md", mime="text/markdown",
                       key=f"rm_{key}", use_container_width=True)
    with st.expander("Aperçu du rapport"):
        st.markdown(r["markdown"])
