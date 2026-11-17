"""Outil export_excel (catalogue) et exporter_excel (HakimAI) : classeur Excel (.xlsx) à partir de requêtes SELECT.

- Lecture seule : chaque feuille vient d'une requête contrôlée (checked_statement : lecture seule, tables autorisées
  de l'agent), exécutée avec les droits de l'utilisateur.
- Le fichier est construit par l'application (bibliothèque standard : zipfile + XML, aucune dépendance), jamais par
  le modèle. Le modèle reçoit un résumé (feuilles, lignes, colonnes) ; le fichier est dans « _ui_excel ».
- Feuille « Informations » : titre, date, utilisateur, et pour chaque feuille sa requête et son nombre de lignes
  (traçabilité résultat -> requête).
- Feuilles rédigées : une feuille peut aussi recevoir un tableau fourni directement (colonnes, lignes), par exemple
  une spécification ou un plan de test. Son contenu vient du modèle, pas des données : en-tête orange, origine
  « contenu rédigé, non issu des données » dans la feuille Informations et dans le résumé.
- Protection contre l'injection de formules : les textes commençant par = + - @ sont écrits en texte pur.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import math
import re
import zipfile
from xml.sax.saxutils import escape

from backend.tool_registry import ToolContext, ToolError
from tools.sql_tools import checked_statement

MAX_SHEETS = 10
MAX_ROWS = 20000          # lignes par feuille
DEFAULT_ROWS = 5000
MAX_DRAFT_ROWS = 500      # feuille rédigée : contenu écrit par le modèle, volume limité
MAX_DRAFT_COLS = 30
DRAFT_ORIGIN = "Contenu rédigé par l'assistant, non issu des données : à relire et valider"
MAX_CELL = 32000          # limite Excel : 32 767 caractères par cellule
_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_INT_T = {"BYTE", "SHORT", "INT", "INTEGER", "LONG", "BIGINT", "TINYINT", "SMALLINT"}
_NUM_T = {"FLOAT", "DOUBLE", "DECIMAL", "REAL"}
_EPOCH = dt.datetime(1899, 12, 30)


# --- Valeurs ----------------------------------------------------------------------------------------------------
def _base_type(t) -> str:
    return re.split(r"[(<\s]", str(t or "STRING").upper(), 1)[0]


def convert(v, sql_type) -> tuple:
    """(genre, valeur) : 'n' nombre, 'd' date/heure (numéro de série Excel), 'b' booléen, 's' texte, None vide.

    L'API SQL renvoie toutes les valeurs en texte : le type de colonne (manifest) décide de la conversion.
    """
    if v is None:
        return None, None
    t = _base_type(sql_type)
    s = str(v)
    try:
        if t in _INT_T:
            return "n", int(s)
        if t in _NUM_T:
            f = float(s)
            return ("n", f) if math.isfinite(f) else ("s", s)   # NaN / infini : texte (XML Excel invalide sinon)
        if t == "BOOLEAN":
            return "b", s.strip().lower() in ("true", "1")
        if t == "DATE":
            d = dt.date.fromisoformat(s[:10])
            return "d", (dt.datetime(d.year, d.month, d.day) - _EPOCH).days
        if t.startswith("TIMESTAMP"):
            x = dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1)).replace(tzinfo=None)
            return "t", (x - _EPOCH).total_seconds() / 86400
    except (TypeError, ValueError):
        pass
    return "s", s


def _text(s: str) -> str:
    s = _CTRL.sub("", str(s))[:MAX_CELL]
    return escape(s)


def _col(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def sheet_name(name: str, used: set) -> str:
    base = _BAD_SHEET.sub(" ", str(name or "Feuille")).strip().strip("'")[:31] or "Feuille"
    n, i = base, 2
    while n.lower() in used:
        suffix = f" ({i})"
        n, i = base[:31 - len(suffix)] + suffix, i + 1
    used.add(n.lower())
    return n


# --- Écriture du classeur (SpreadsheetML minimal) -----------------------------------------------------------
# Styles : 0 normal, 1 en-tête (gras, fond), 2 date, 3 date et heure, 4 texte en gras (feuille Informations),
# 5 en-tête de feuille rédigée (fond orange)
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/><numFmt numFmtId="165" formatCode="dd/mm/yyyy hh:mm:ss"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0B2A5B"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFC55A11"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>
</styleSheet>"""


def _cell(ref: str, kind, value, style: int = 0) -> str:
    if kind is None:
        return ""
    if kind == "n":
        return f'<c r="{ref}"><v>{value!r}</v></c>' if isinstance(value, float) else f'<c r="{ref}"><v>{value}</v></c>'
    if kind in ("d", "t"):
        return f'<c r="{ref}" s="{2 if kind == "d" else 3}"><v>{value}</v></c>'
    if kind == "b":
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    st = f' s="{style}"' if style else ""
    # t="inlineStr" : jamais interprété comme formule (=, +, -, @ restent du texte)
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{_text(value)}</t></is></c>'


def _sheet_xml(columns: list[str], rows: list[list[tuple]], widths: list[int] | None = None,
               header_style: int = 1, filters: bool = True) -> str:
    ncol = max(1, len(columns))
    widths = widths or [10] * ncol
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
           'state="frozen"/></sheetView></sheetViews><cols>']
    out += [f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)]
    out.append("</cols><sheetData>")
    out.append('<row r="1">' + "".join(_cell(f"{_col(i)}1", "s", c, header_style) for i, c in enumerate(columns))
               + "</row>")
    for r, row in enumerate(rows, 2):
        out.append(f'<row r="{r}">' + "".join(_cell(f"{_col(i)}{r}", k, v) for i, (k, v) in enumerate(row)) + "</row>")
    out.append("</sheetData>")
    if filters and columns:
        out.append(f'<autoFilter ref="A1:{_col(ncol - 1)}{max(1, len(rows) + 1)}"/>')
    out.append("</worksheet>")
    return "".join(out)


def _widths(columns: list[str], rows: list[list[tuple]]) -> list[int]:
    w = [len(str(c)) for c in columns]
    for row in rows[:500]:
        for i, (k, v) in enumerate(row):
            n = 11 if k in ("d",) else 19 if k == "t" else len(str(v)) if v is not None else 0
            w[i] = max(w[i], n)
    return [min(max(8, x + 2), 60) for x in w]


def build_workbook(sheets: list[dict], info: list[list[str]]) -> bytes:
    """sheets : [{nom, colonnes, lignes (listes de (genre, valeur))}] ; info : lignes texte de la feuille Informations."""
    names = [s["nom"] for s in sheets] + ["Informations"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(names) + 1))
                   + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                   "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                   "</Relationships>")
        now = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                   'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                   f"<dc:creator>DISCOVERY</dc:creator>"
                   f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, n in enumerate(names, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(names) + 1))
                   + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       _sheet_xml(s["colonnes"], s["lignes"], _widths(s["colonnes"], s["lignes"]),
                                  header_style=5 if s.get("redigee") else 1))
        info_rows = [[("s", a), ("s", b)] for a, b in info]
        z.writestr(f"xl/worksheets/sheet{len(names)}.xml",
                   _sheet_xml(["Information", "Valeur"], info_rows, [28, 100], filters=False))
    return buf.getvalue()


def file_name(title: str) -> str:
    base = re.sub(r"[^A-Za-z0-9À-ÿ_-]+", "_", str(title or "export")).strip("_")[:60] or "export"
    return f"{base}_{dt.date.today().isoformat()}.xlsx"


# --- Feuilles rédigées ----------------------------------------------------------------------------------------
def _draft_value(v) -> tuple:
    """Valeur fournie par le modèle : nombres JSON en nombres, textes tels quels (jamais convertis), objets en JSON."""
    if v is None or v == "":
        return None, None
    if isinstance(v, bool):
        return "b", v
    if isinstance(v, (int, float)):
        return ("n", v) if math.isfinite(v) else ("s", str(v))
    if isinstance(v, (dict, list)):
        return "s", json.dumps(v, ensure_ascii=False)
    return "s", str(v)


def draft_sheet(i: int, name: str, colonnes, lignes) -> tuple[list[str], list[list[tuple]]]:
    if not isinstance(lignes, list) or not lignes:
        raise ToolError(f"Feuille {i} « {name} » : lignes vides (liste d'objets ou de listes attendue).")
    if len(lignes) > MAX_DRAFT_ROWS:
        raise ToolError(f"Feuille {i} « {name} » : {MAX_DRAFT_ROWS} lignes rédigées au plus. Pour des données, "
                        "utiliser une requête.")
    cols = [str(c) for c in (colonnes or [])]
    if not cols:   # ordre d'apparition des clés
        for row in lignes:
            if not isinstance(row, dict):
                raise ToolError(f"Feuille {i} « {name} » : sans colonnes, chaque ligne doit être un objet.")
            cols += [str(k) for k in row if str(k) not in cols]
    if not cols or len(cols) > MAX_DRAFT_COLS:
        raise ToolError(f"Feuille {i} « {name} » : entre 1 et {MAX_DRAFT_COLS} colonnes.")
    data = []
    for j, row in enumerate(lignes, 1):
        if isinstance(row, dict):
            unknown = [k for k in row if str(k) not in cols]
            if unknown:
                raise ToolError(f"Feuille {i} « {name} », ligne {j} : colonnes inconnues {unknown}.")
            data.append([_draft_value(row.get(c)) for c in cols])
        elif isinstance(row, list):
            if len(row) > len(cols):
                raise ToolError(f"Feuille {i} « {name} », ligne {j} : {len(row)} valeurs pour {len(cols)} colonnes.")
            data.append([_draft_value(row[k] if k < len(row) else None) for k in range(len(cols))])
        else:
            raise ToolError(f"Feuille {i} « {name} », ligne {j} : objet ou liste attendu.")
    return cols, data


# --- Outil ------------------------------------------------------------------------------------------------------
def export_excel(ctx: ToolContext, titre: str, feuilles: list, limite: int = DEFAULT_ROWS) -> dict:
    if not str(titre or "").strip():
        raise ToolError("Titre du fichier manquant.")
    if not feuilles:
        raise ToolError("Au moins une feuille est requise : nom et requete (données), ou nom et lignes (tableau "
                        "rédigé).")
    if len(feuilles) > MAX_SHEETS:
        raise ToolError(f"{MAX_SHEETS} feuilles au plus.")
    n = max(1, min(int(limite or DEFAULT_ROWS), MAX_ROWS))
    used, sheets, resume = {"informations"}, [], []
    info = [["Titre", str(titre)], ["Généré le", dt.datetime.now().strftime("%d/%m/%Y %H:%M")],
            ["Par", ctx.user_email or "utilisateur"], ["Application", "DISCOVERY (données lues avec vos droits)"],
            ["Limite de lignes par feuille", str(n)]]
    for i, f in enumerate(feuilles, 1):
        if not isinstance(f, dict):
            raise ToolError(f"Feuille {i} invalide : objet attendu (nom, et requete ou lignes).")
        has_q, has_rows = bool(str(f.get("requete") or "").strip()), f.get("lignes") is not None
        if has_q == has_rows:
            raise ToolError(f"Feuille {i} : indiquer soit requete (données), soit lignes (tableau rédigé), "
                            "pas les deux ni aucun.")
        name = sheet_name(f.get("nom") or f"Feuille {i}", used)
        if has_rows:
            cols, data = draft_sheet(i, name, f.get("colonnes"), f["lignes"])
            sheets.append({"nom": name, "colonnes": cols, "lignes": data, "redigee": True})
            resume.append({"feuille": name, "lignes": len(data), "colonnes": cols, "tronque": False,
                           "origine": "rédigée"})
            info.append([f"Feuille « {name} »", f"{len(data)} ligne(s)"])
            info.append([f"Origine « {name} »", DRAFT_ORIGIN])
            continue
        stmt = checked_statement(ctx, f["requete"])
        try:
            r = ctx.sql.query(stmt, row_limit=n)
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Feuille {i} « {name} » : {str(e)[:400]}") from e
        rows = r.get("rows") or []
        cols = list(r.get("columns") or (list(rows[0].keys()) if rows else []))
        types = r.get("types") or {}
        data = [[convert(row.get(c), types.get(c)) for c in cols] for row in rows]
        trunc = bool(r.get("truncated")) or len(rows) >= n
        sheets.append({"nom": name, "colonnes": cols, "lignes": data})
        resume.append({"feuille": name, "lignes": len(rows), "colonnes": cols, "tronque": trunc,
                       "origine": "données"})
        info.append([f"Feuille « {name} »", f"{len(rows)} ligne(s)" + (" (tronquée à la limite)" if trunc else "")])
        info.append([f"Requête « {name} »", stmt])
    content = build_workbook(sheets, info)
    fname = file_name(titre)
    drafted = [s["feuille"] for s in resume if s["origine"] == "rédigée"]
    note = "Nombres de lignes calculés par l'application : les reprendre tels quels. Signaler toute feuille tronquée."
    if drafted:
        note += (" Feuilles rédigées (" + ", ".join(drafted) + ") : leur contenu vient de toi, pas des données ; "
                 "le dire à l'utilisateur et lui demander de le relire et de le valider.")
    return {"titre": titre, "fichier": fname, "taille_ko": round(len(content) / 1024, 1), "feuilles": resume,
            "affichage": "Le bouton de téléchargement Excel s'affiche sous la réponse.",
            "note": note,
            "_ui_excel": {"titre": titre, "nom_fichier": fname,
                          "contenu_b64": base64.b64encode(content).decode("ascii")}}


exporter_excel = export_excel   # nom français pour HakimAI
