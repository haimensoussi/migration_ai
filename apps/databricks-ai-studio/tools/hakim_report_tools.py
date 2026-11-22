"""Outils de HakimAI, lot 3b : visuels et rapports, en lecture seule avec les droits de l'utilisateur.

- Les données viennent d'une requête SELECT contrôlée (checked_statement : lecture seule, tables autorisées).
- Le modèle choisit le type et les colonnes ; l'application dessine (Vega-Lite, carte pydeck) : aucun code généré exécuté.
- Le rapport est assemblé par l'application à partir des visuels réellement calculés ; tout texte est échappé.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math

from backend.tool_registry import ToolContext, ToolError
from tools.hakim_tools import _p
from tools.chart_tools import _clean, _num, _stats, build_chart, summary, vega_spec  # noqa: F401  (moteur partagé)

KINDS = ("barres", "barres_horizontales", "courbe", "aire", "camembert", "nuage", "tableau", "carte")


def creer_visuel(ctx: ToolContext, titre: str, requete: str, type: str, x: str = "", y: str = "", couleur: str = "",
                 infobulle: list | None = None, limite: int = 200) -> dict:
    p = _p(ctx)
    if type not in KINDS:
        raise ToolError(f"Type inconnu : {type}. Types possibles : {', '.join(KINDS)}.")
    vid = f"V{len(p.visuals) + 1}"
    if type == "carte":
        from tools.map_tools import render_map
        r = render_map(ctx, requete, title=titre, color_by=couleur or None, tooltip=infobulle or None)
        p.visuals[vid] = {"id": vid, "type": "carte", "titre": titre, "requete": requete, "carte": r,
                          "colonnes": [], "lignes": [], "cree_le": dt.datetime.now().isoformat(timespec="seconds")}
        return {"visuel_id": vid, "type": "carte", "points": r.get("nombre_points"), "ignores": r.get("ignores"),
                "tronque": r.get("tronque"), "message": r.get("message"), "affichage": "La carte s'affiche sous la réponse."}
    v = {"id": vid, **build_chart(ctx, titre, requete, type, x, y, couleur, limite)}
    p.visuals[vid] = v
    return {"visuel_id": vid, **summary(v)}


# --- Rapport ----------------------------------------------------------------------------------------------
def _table_html(cols: list[str], rows: list[dict], limit: int = 50) -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape('' if r.get(c) is None else str(r.get(c)))}</td>" for c in cols)
                   + "</tr>" for r in rows[:limit])
    more = f"<p class='note'>{len(rows) - limit} lignes supplémentaires non affichées.</p>" if len(rows) > limit else ""
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{more}"


def _table_md(cols: list[str], rows: list[dict], limit: int = 50) -> str:
    esc = lambda v: ("" if v is None else str(v)).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = ["| " + " | ".join(esc(c) for c in cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    lines += ["| " + " | ".join(esc(r.get(c)) for c in cols) + " |" for r in rows[:limit]]
    return "\n".join(lines)


def _json_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def build_report(titre: str, sections: list[dict], visuals: dict, user: str, introduction: str = "",
                 conclusion: str = "", auteur: str = "HakimAI") -> dict:
    now = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    e = html.escape
    parts_h, parts_m, used, charts = [], [f"# {titre}", f"_Généré par {auteur} pour {user} le {now}._"], [], []
    if introduction:
        parts_h.append(f"<p>{e(introduction)}</p>"); parts_m.append(introduction)
    for i, sec in enumerate(sections, 1):
        st_, txt, vid = str(sec.get("titre") or f"Section {i}"), str(sec.get("texte") or ""), sec.get("visuel_id")
        parts_h.append(f"<h2>{e(st_)}</h2>" + (f"<p>{e(txt)}</p>" if txt else "")); parts_m += [f"## {st_}", txt]
        v = visuals.get(vid) if vid else None
        if vid and not v:
            raise ToolError(f"Visuel « {vid} » introuvable : créez-le d'abord avec creer_visuel.")
        if v:
            used.append(vid)
            if v["type"] == "smartart":   # schéma rédigé : liste de ses éléments (pas de requête)
                lines = [f"{it['texte']}" + (f" — {it['detail']}" if it.get("detail") else "") for it in v["elements"]]
                parts_h.append(f"<p class='note'>Schéma : {e(v['titre'])}</p><ol>"
                               + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ol>")
                parts_m.append(f"_Schéma : {v['titre']}_\n\n" + "\n".join(f"{n}. {x}" for n, x in enumerate(lines, 1)))
            elif v["type"] == "carte":
                pts = v["carte"].get("_ui_points") or []
                cols = [c for c in (pts[0].keys() if pts else []) if not c.startswith("_")]
                rows = [{**{c: p.get(c) for c in cols}, "latitude": p.get("_lat"), "longitude": p.get("_lon")} for p in pts]
                parts_h.append(f"<p class='note'>Carte : {len(pts)} points (tableau ci-dessous).</p>"
                               + _table_html(cols + ["latitude", "longitude"], rows, 30))
                parts_m.append(_table_md(cols + ["latitude", "longitude"], rows, 30))
            elif v["type"] == "tableau":
                parts_h.append(_table_html(v["colonnes"], v["lignes"])); parts_m.append(_table_md(v["colonnes"], v["lignes"]))
            else:
                charts.append((f"chart{i}", vega_spec(v)))
                parts_h.append(f"<div class='chart' id='chart{i}'></div><details><summary>Données</summary>"
                               f"{_table_html(v['colonnes'], v['lignes'])}</details>")
                parts_m.append(_table_md(v["colonnes"], v["lignes"]))
    if conclusion:
        parts_h.append(f"<h2>Conclusion</h2><p>{e(conclusion)}</p>"); parts_m += ["## Conclusion", conclusion]
    annex_h = "".join(f"<h3>{e(vid)} · {e(visuals[vid]['titre'])}</h3><pre>{e(visuals[vid]['requete'])}</pre>"
                      f"<p class='note'>Calculé le {e(visuals[vid]['cree_le'])}"
                      + (" · résultat tronqué" if visuals[vid].get("tronque") else "") + "</p>" for vid in used
                      if visuals[vid].get("requete"))
    annex_m = "\n\n".join(f"### {vid} · {visuals[vid]['titre']}\n\n```sql\n{visuals[vid]['requete']}\n```" for vid in used
                          if visuals[vid].get("requete"))
    scripts = "".join(f"vegaEmbed('#{cid}', {_json_script(spec)}, {{actions: false}});" for cid, spec in charts)
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{e(titre)}</title>
<script src="https://cdn.jsdelivr.net/npm/vega@5"></script><script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
<style>body{{font-family:Arial,sans-serif;max-width:1000px;margin:32px auto;color:#222;padding:0 16px}}
h1{{color:#B0124F}}h2{{color:#4A1942;border-bottom:1px solid #ddd;padding-bottom:4px}}
table{{border-collapse:collapse;font-size:13px;margin:8px 0}}td,th{{border:1px solid #ddd;padding:4px 8px}}th{{background:#F6F6F8}}
.chart{{width:100%;margin:12px 0}}.note{{color:#666;font-size:12px}}pre{{background:#F6F6F8;padding:8px;white-space:pre-wrap}}</style>
</head><body><h1>{e(titre)}</h1><p class="note">Généré par {e(auteur)} (DISCOVERY · SNCF Réseau) pour {e(user)} le {now}.
Chiffres calculés à partir des requêtes en annexe, avec les droits de l'utilisateur.</p>
{''.join(parts_h)}<h2>Annexe : requêtes et traçabilité</h2>{annex_h}
<script>{scripts}</script></body></html>"""
    md = "\n\n".join(x for x in parts_m if x) + "\n\n## Annexe : requêtes et traçabilité\n\n" + annex_m
    return {"html": page, "markdown": md, "visuels": used}


def generer_rapport(ctx: ToolContext, titre: str, sections: list, introduction: str = "", conclusion: str = "") -> dict:
    p = _p(ctx)
    if not sections:
        raise ToolError("Le rapport doit contenir au moins une section.")
    r = build_report(titre, sections, p.visuals, p.user, introduction, conclusion)
    rid = f"R{len(p.reports) + 1}"
    p.reports[rid] = {"id": rid, "titre": titre, **r}
    return {"rapport_id": rid, "titre": titre, "sections": len(sections), "visuels": r["visuels"],
            "affichage": "Les boutons de téléchargement (HTML, Markdown) s'affichent sous la réponse."}
