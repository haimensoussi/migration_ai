"""Outils generate_report et render_kpi (catalogue, tous les agents) : restitution en lecture seule.

- Les données viennent de requêtes SELECT contrôlées (checked_statement : lecture seule, tables autorisées de l'agent),
  exécutées avec les droits de l'utilisateur.
- Les chiffres (valeurs, écarts, tendances, tableaux, graphiques) sont calculés par l'application, jamais par le modèle.
- Le modèle reçoit un résumé ; le rendu complet (cartes d'indicateurs, rapport HTML/Markdown) est dans les clés
  « _ui_* », réservées à l'affichage.
"""
from __future__ import annotations

import datetime as dt

from backend.tool_registry import ToolContext, ToolError
from tools.chart_tools import CHART_KINDS, _clean, _num, build_chart, summary
from tools.hakim_report_tools import build_report
from tools.sql_tools import checked_statement

MAX_KPIS = 12
MAX_SECTIONS = 8
FORMATS = ("nombre", "decimal", "pourcentage")
SENS = ("hausse_favorable", "baisse_favorable", "neutre")
DELTA_COLOR = {"hausse_favorable": "normal", "baisse_favorable": "inverse", "neutre": "off"}


# --- Indicateurs ---------------------------------------------------------------------------------------------------

def _fr(x: float, decimals: int) -> str:
    """Format français : espace insécable fine pour les milliers, virgule décimale."""
    s = f"{x:,.{decimals}f}".replace(",", "\u202f").replace(".", ",")
    return s.replace("-", "\u2212")


def fmt_value(v: float | None, fmt: str, unite: str = "") -> str:
    if v is None:
        return "n/d"
    if fmt == "pourcentage":
        return f"{_fr(v, 1)} %"
    s = _fr(v, 0 if fmt == "nombre" and float(v).is_integer() else 2)
    return f"{s} {unite}".strip()


def compute_kpi(label: str, value, ref, fmt: str, sens: str, unite: str = "") -> dict:
    """Un indicateur : valeur, écart à la référence et tendance, calculés ici (pas par le modèle).

    Format « pourcentage » : les valeurs sont déjà en pourcentage (91.2 = 91,2 %) et l'écart est en points.
    """
    v, r = _num(value), _num(ref)
    k = {"libelle": label, "valeur": v, "valeur_affichee": fmt_value(v, fmt, unite), "reference": r,
         "ecart": None, "ecart_affiche": None, "ecart_relatif_pct": None, "tendance": None}
    if v is None or r is None:
        if v is None:
            k["tendance"] = "valeur manquante"
        return k
    d = round(v - r, 6)
    k["ecart"] = d
    if fmt == "pourcentage":
        k["ecart_affiche"] = ("+" if d > 0 else "") + f"{_fr(d, 1)} pt"
    else:
        k["ecart_affiche"] = ("+" if d > 0 else "") + fmt_value(d, fmt, unite)
        if r != 0:
            k["ecart_relatif_pct"] = round(d / abs(r) * 100, 2)
            k["ecart_affiche"] += f" ({'+' if d > 0 else ''}{_fr(k['ecart_relatif_pct'], 1)} %)"
    if d == 0:
        k["tendance"] = "stable"
    elif sens == "neutre":
        k["tendance"] = "hausse" if d > 0 else "baisse"
    else:
        good = (d > 0) == (sens == "hausse_favorable")
        k["tendance"] = ("hausse" if d > 0 else "baisse") + (" favorable" if good else " défavorable")
    return k


def render_kpi(ctx: ToolContext, query: str, valeur: str, titre: str = "", libelle: str = "", reference: str = "",
               format: str = "nombre", unite: str = "", sens: str = "neutre", libelle_reference: str = "") -> dict:
    if format not in FORMATS:
        raise ToolError(f"Format inconnu : {format}. Formats possibles : {', '.join(FORMATS)}.")
    if sens not in SENS:
        raise ToolError(f"Sens inconnu : {sens}. Valeurs possibles : {', '.join(SENS)}.")
    r = ctx.sql.query(checked_statement(ctx, query), row_limit=MAX_KPIS + 1)
    rows = r.get("rows") or []
    if not rows:
        raise ToolError("La requête ne renvoie aucune ligne : aucun indicateur à afficher.")
    if len(rows) > MAX_KPIS:
        raise ToolError(f"Plus de {MAX_KPIS} lignes : une ligne = un indicateur. Agréger ou filtrer en SQL.")
    cols = list(rows[0].keys())
    for role, c in (("valeur", valeur), ("libelle", libelle), ("reference", reference)):
        if c and c not in cols:
            raise ToolError(f"Colonne {role} « {c} » absente du résultat (colonnes : {', '.join(cols)}).")
    if all(_num(x.get(valeur)) is None for x in rows):
        raise ToolError(f"La colonne valeur « {valeur} » ne contient pas de nombres.")
    kpis = [compute_kpi(str(_clean(x.get(libelle))) if libelle else (titre or valeur), x.get(valeur),
                        x.get(reference) if reference else None, format, sens, unite) for x in rows]
    k = {"titre": titre or "Indicateurs", "indicateurs": kpis, "format": format, "unite": unite, "sens": sens,
         "libelle_reference": libelle_reference or ("référence" if reference else ""), "requete": query,
         "delta_color": DELTA_COLOR[sens], "cree_le": dt.datetime.now().isoformat(timespec="seconds")}
    out = {"titre": k["titre"], "indicateurs": kpis, "libelle_reference": k["libelle_reference"],
           "affichage": "Les cartes d'indicateurs s'affichent sous la réponse.",
           "note": "Valeurs, écarts et tendances calculés par l'application : les reprendre tels quels.",
           "_ui_kpi": k}
    if format == "pourcentage":
        out["note_format"] = "Valeurs en pourcentage, écarts en points."
    return out


# --- Rapport --------------------------------------------------------------------------------------------------------

def _compact(v: dict) -> dict:
    s = summary(v)
    s["apercu"] = s["apercu"][:10]
    s["apercu_complet"] = s["apercu_complet"] and len(v["lignes"]) <= 10
    s.pop("affichage", None)
    return s


def generate_report(ctx: ToolContext, titre: str, sections: list, introduction: str = "", conclusion: str = "") -> dict:
    if not str(titre or "").strip():
        raise ToolError("Titre du rapport manquant.")
    if not sections:
        raise ToolError("Le rapport doit contenir au moins une section.")
    if len(sections) > MAX_SECTIONS:
        raise ToolError(f"{MAX_SECTIONS} sections au plus.")
    visuals, secs, resume = {}, [], []
    for i, sec in enumerate(sections, 1):
        if not isinstance(sec, dict):
            raise ToolError(f"Section {i} invalide : objet attendu (titre, texte, requete...).")
        s = {"titre": sec.get("titre") or f"Section {i}", "texte": sec.get("texte") or ""}
        q = str(sec.get("requete") or "").strip()
        if q:
            kind = sec.get("type") or "tableau"
            if kind not in CHART_KINDS:
                raise ToolError(f"Section {i} : type inconnu « {kind} » ({', '.join(CHART_KINDS)}). "
                                "Les cartes ne sont pas prises en charge dans le rapport.")
            try:
                v = build_chart(ctx, s["titre"], q, kind, sec.get("x") or "", sec.get("y") or "",
                                sec.get("couleur") or "", sec.get("limite") or 200)
            except ToolError as e:
                raise ToolError(f"Section {i} « {s['titre']} » : {e}") from e
            vid = f"S{i}"
            visuals[vid], s["visuel_id"] = v, vid
            resume.append({"section": s["titre"], **_compact(v)})
        else:
            resume.append({"section": s["titre"], "visuel": None})
        secs.append(s)
    r = build_report(titre, secs, visuals, ctx.user_email or "utilisateur", introduction, conclusion, auteur="DISCOVERY")
    return {"titre": titre, "sections": resume,
            "affichage": "Les boutons de téléchargement (HTML, Markdown) s'affichent sous la réponse.",
            "note": ("Les tableaux et graphiques du rapport sont calculés par l'application ; si un texte de section "
                     "contredit ces résultats, le signaler à l'utilisateur."),
            "_ui_report": {"titre": titre, "html": r["html"], "markdown": r["markdown"]}}
