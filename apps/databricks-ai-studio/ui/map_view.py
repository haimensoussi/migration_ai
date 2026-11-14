"""Affichage des cartes render_map : préparation pure (testable) + rendu Streamlit/pydeck."""
from __future__ import annotations

import html
import json
import os

# Couleurs contrastées sur fond clair (framboise DISCOVERY puis palette Okabe-Ito, lisible par les daltoniens)
PALETTE = [[176, 18, 79], [0, 114, 178], [230, 159, 0], [0, 158, 115], [122, 62, 157], [213, 94, 0],
           [86, 180, 233], [204, 121, 167], [52, 73, 94], [128, 128, 0], [0, 0, 0], [153, 0, 0]]
OTHER = [150, 150, 160]
GRADIENT = ([0, 114, 178], [176, 18, 79])        # valeurs numériques : bleu (min) -> framboise (max)
CARTO_LIGHT = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
CARTO_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def colorize(points: list[dict], result: dict) -> list[dict]:
    """Ajoute _color à chaque point selon la légende (catégories ou dégradé numérique)."""
    leg, col = result.get("legende") or {}, result.get("couleur")
    out = []
    for p in points:
        c = PALETTE[0]
        if col and leg.get("type") == "categories":
            vals = leg.get("valeurs") or []
            v = str(p.get(col))
            c = PALETTE[vals.index(v) % len(PALETTE)] if v in vals else OTHER
        elif col and leg.get("type") == "numerique":
            lo, hi, x = leg.get("min"), leg.get("max"), _num(p.get(col))
            t = 0.0 if x is None or hi == lo else (x - lo) / (hi - lo)
            lo_c, hi_c = GRADIENT
            c = [int(lo_c[k] + (hi_c[k] - lo_c[k]) * t) for k in range(3)]
        out.append({**p, "_color": c + [230]})
    return out


def view_state(result: dict) -> dict:
    e = result.get("emprise") or {}
    if not e:
        return {"latitude": 46.6, "longitude": 2.4, "zoom": 4.6}
    lat, lon = (e["lat_min"] + e["lat_max"]) / 2, (e["lon_min"] + e["lon_max"]) / 2
    span = max(e["lat_max"] - e["lat_min"], (e["lon_max"] - e["lon_min"]) * 0.7, 0.01)
    zoom = 11 if span < 0.05 else 9 if span < 0.3 else 7.5 if span < 1.5 else 6 if span < 4 else 4.6
    return {"latitude": lat, "longitude": lon, "zoom": zoom}


def tooltip_rows(points: list[dict], fields: list[str]) -> tuple[list[dict], str]:
    """pydeck n'accepte que des noms simples dans l'infobulle : colonnes renommées f0, f1..."""
    keyed = []
    for p in points:
        d = {"_lat": p["_lat"], "_lon": p["_lon"], "_color": p.get("_color", PALETTE[0] + [200])}
        for i, f in enumerate(fields):
            d[f"f{i}"] = "" if p.get(f) is None else str(p.get(f))
        keyed.append(d)
    tip = "<br/>".join(f"<b>{html.escape(f)}</b> : {{f{i}}}" for i, f in enumerate(fields))
    return keyed, tip


def to_geojson(points: list[dict]) -> str:
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["_lon"], p["_lat"]]},
              "properties": {k: v for k, v in p.items() if not k.startswith("_")}} for p in points]
    return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, default=str)


def map_style() -> str:
    """Fond clair par défaut (cohérent avec DISCOVERY). AI_STUDIO_MAP_STYLE=dark : fond sombre ;
    none : carte sans fond (si les fonds de carte Internet sont bloqués)."""
    v = os.environ.get("AI_STUDIO_MAP_STYLE", "").strip().lower()
    if v in ("none", "aucun", "0"):
        return ""
    return CARTO_DARK if v in ("dark", "sombre") else CARTO_LIGHT


def render(ev: dict) -> None:
    import pandas as pd
    import streamlit as st

    res = ev.get("result") or {}
    points = res.get("_ui_points") or []
    st.markdown(f"**{html.escape(res.get('titre') or 'Carte')}**")
    if not points:
        st.info(res.get("message") or "Aucun point à afficher.")
        return
    pts = colorize(points, res)
    fields = res.get("infobulle") or []
    try:
        import pydeck as pdk
        data, tip = tooltip_rows(pts, fields)
        if res.get("couche") == "heatmap":
            layer = pdk.Layer("HeatmapLayer", data=data, get_position=["_lon", "_lat"], radius_pixels=40, opacity=0.8)
        else:
            layer = pdk.Layer("ScatterplotLayer", data=data, get_position=["_lon", "_lat"], get_fill_color="_color",
                              get_radius=300, radius_min_pixels=5, radius_max_pixels=14, pickable=True,
                              stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1.5)
        deck = pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(**view_state(res)), map_provider="carto",
                        map_style=map_style(),
                        tooltip={"html": tip, "style": {"fontSize": "12px", "backgroundColor": "#2B1B33",
                                                        "color": "#FFFFFF"}} if tip else True)
        st.pydeck_chart(deck, use_container_width=True)
    except Exception:  # noqa: BLE001 - repli : carte Streamlit simple
        st.map(pd.DataFrame({"lat": [p["_lat"] for p in pts], "lon": [p["_lon"] for p in pts]}))
    leg = res.get("legende") or {}
    notes = [f"{res.get('nombre_points', len(pts))} points"]
    if res.get("ignores"):
        notes.append(f"{res['ignores']} lignes sans coordonnées valides ignorées")
    if res.get("hors_metropole"):
        notes.append(f"{res['hors_metropole']} points hors France métropolitaine")
    if res.get("tronque"):
        notes.append(f"résultat limité à {res.get('limite')} points")
    st.caption(" · ".join(notes))
    if leg.get("type") == "categories":
        chips = "".join(
            f'<span style="display:inline-flex;align-items:center;margin-right:12px;font-size:12px">'
            f'<span style="width:10px;height:10px;border-radius:50%;margin-right:5px;background:rgb'
            f'{tuple(PALETTE[i % len(PALETTE)])}"></span>{html.escape(str(v))}</span>'
            for i, v in enumerate(leg.get("valeurs") or []))
        st.markdown(f"<div>{chips}</div>", unsafe_allow_html=True)
    elif leg.get("type") == "numerique":
        st.caption(f"Couleur « {res.get('couleur')} » : de {leg['min']:g} (clair) à {leg['max']:g} (foncé)")
    df = pd.DataFrame([{k: v for k, v in p.items() if not k.startswith("_")} | {"latitude": p["_lat"],
                       "longitude": p["_lon"]} for p in points])
    with st.expander(f"Données de la carte ({len(df)} lignes)"):
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.code(ev.get("arguments", {}).get("query", ""), language="sql")
        c1, c2 = st.columns(2)
        c1.download_button("Exporter en CSV", df.to_csv(index=False).encode("utf-8"), "carte.csv", "text/csv",
                           key=f"csv_{id(ev)}")
        c2.download_button("Exporter en GeoJSON", to_geojson(points).encode("utf-8"), "carte.geojson",
                           "application/geo+json", key=f"geo_{id(ev)}")
