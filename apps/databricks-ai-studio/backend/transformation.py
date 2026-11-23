"""HakimAI Transformation : lot A (étapes 1 à 3 : cadrage, découverte, cartographie), lot B1 (étapes 4 et 5 :
diagnostic et opportunités, conception de la cible) et lot B2 (étapes 6 et 7 : feuille de route, génération et suivi).

Gouvernance :
- HakimAI PROPOSE (statut « propose »). Seul le propriétaire du plan valide ou rejette, depuis la page Transformation.
- Découverte : structure lue dans Unity Catalog et statistiques agrégées calculées en SQL, avec les droits de
  l'utilisateur. Aucune ligne de donnée n'est lue ni stockée ; pas de min/max sur les colonnes texte.
- Périmètre : zone de données de la plateforme (tables préfixées data_ du schéma de l'application).
- Un plan est visible par son propriétaire et par les administrateurs ; seul le propriétaire le modifie.
- Les constats de la découverte sont statistiques ; ils ne sont pas des exigences métier.
- Traçabilité : un cas d'usage s'appuie sur un processus VALIDÉ ; un élément de la cible (agent, outil, flux,
  équipe) sert au moins un cas d'usage VALIDÉ et dit s'il réutilise, adapte ou crée un objet de la plateforme.
- Feuille de route : des vagues ordonnées regroupent des éléments de la cible VALIDÉS (un élément, une vague) ;
  une vague ne dépend que de vagues antérieures. Valeur et effort restent qualitatifs, avec justification.
- Génération : les brouillons sont créés ou modifiés par les outils HakimAI habituels, puis reliés à l'élément du
  plan ; le suivi lit le statut réel des objets. Rien n'est publié depuis la transformation.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

STEPS = [(1, "cadrage", "Cadrage"), (2, "decouverte", "Découverte des données"), (3, "cartographie", "Existant (AS-IS)"),
         (4, "diagnostic", "Diagnostic et opportunités"), (5, "cible", "Cible (TO-BE)"),
         (6, "feuille_de_route", "Feuille de route"), (7, "generation", "Génération et suivi")]
LOT_A_LAST_STEP = 3
AVAILABLE_LAST_STEP = 7
ITEM_TYPES_LOT_A = ("objectif", "domaine", "processus")
TARGET_TYPES = ("agent", "outil", "flux", "equipe")
ITEM_STEP = {"objectif": 3, "domaine": 3, "processus": 3, "cas_usage": 4, **{k: 5 for k in TARGET_TYPES}, "vague": 6}
ITEM_TYPES = tuple(ITEM_STEP)
ITEM_TYPES_AVAILABLE = tuple(k for k, s in ITEM_STEP.items() if s <= AVAILABLE_LAST_STEP)
# EIA (21/11/2026) : processus métier reportés. HakimAI ne les propose plus ; les processus déjà enregistrés restent
# lisibles et décidables, et un cas d'usage peut encore en citer un (facultatif).
PROPOSABLE_TYPES = tuple(k for k in ITEM_TYPES_AVAILABLE if k != "processus")
CHANGE_LABELS = {"reutiliser": "Réutilisation", "adapter": "Adaptation", "creer": "Création"}
# EIA Transformation Center (22/11/2026) : 4 onglets regroupant les 7 étapes.
PHASES = [("discovery", "Enterprise Discovery", (1, 2, 3)), ("opportunities", "AI Opportunities", (4,)),
          ("architecture", "Target EIA Architecture", (5,)), ("deployment", "Validation & Deployment", (6, 7))]
NEXT_ACTION = {
    1: "Décrivez l'activité et les objectifs (Enterprise Discovery), seul ou avec HakimAI.",
    2: "Choisissez le périmètre de données et lancez la découverte (Enterprise Discovery).",
    3: "Validez au moins un objectif et un domaine (Enterprise Discovery).",
    4: "Validez au moins un cas d'usage (AI Opportunities).",
    5: "Demandez à HakimAI la cible, puis validez-la : chaque cas d'usage validé doit être servi "
       "(Target EIA Architecture).",
    6: "Demandez à HakimAI la feuille de route, puis validez les vagues (Validation & Deployment).",
    7: "Créez ou reliez les objets prévus, puis soumettez-les à publication (Validation & Deployment).",
}
ITEM_LABELS = {"objectif": "Objectif", "domaine": "Domaine métier", "processus": "Processus",
               "cas_usage": "Cas d'usage", "agent": "Agent", "equipe": "Équipe", "flux": "Flux", "outil": "Outil",
               "vague": "Vague"}
ITEM_PLURALS = {"objectif": "Objectifs", "domaine": "Domaines métier", "processus": "Processus",
                "cas_usage": "Cas d'usage", "agent": "Agents", "equipe": "Équipes", "flux": "Flux", "outil": "Outils",
                "vague": "Vagues"}
MODES = {"reutiliser": "Réutiliser l'existant", "adapter": "Adapter l'existant", "creer": "Créer"}
LEVELS = ("faible", "moyen", "fort")
TRACK_LABELS = {"a_faire": "À faire", "brouillon": "Brouillon", "publie": "Publié", "introuvable": "Introuvable"}
STATUSES = ("propose", "valide", "rejete")
CONTEXT_FIELDS = {
    "secteur": "Activité et organisation concernées",
    "objectifs": "Objectifs de la transformation",
    "irritants": "Difficultés et irritants actuels",
    "contraintes": "Contraintes (sécurité, réglementaire, budget, délais)",
    "perimetre": "Périmètre retenu (directions, métiers, données)",
}
DATA_PREFIX = "data_"
MAX_TABLES = 30           # tables analysées par découverte (coût borné : 1 à 3 requêtes d'agrégats par table)
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,255}$")
# Données potentiellement sensibles détectées par le nom de colonne : indices à confirmer, jamais une qualification.
SENSITIVE_TOKENS = {
    "Identité d'une personne": {"prenom", "patronyme", "firstname", "lastname", "surname", "nomfamille"},
    "Coordonnées": {"email", "mail", "courriel", "telephone", "tel", "phone", "mobile", "adresse", "address"},
    "Identifiant personnel": {"matricule", "nir", "securitesociale", "secu", "passeport", "login", "username",
                              "ip", "ipaddress"},
    "Date de naissance": {"naissance", "birth", "birthdate", "dob"},
    "Donnée financière personnelle": {"iban", "bic", "rib", "salaire", "salary", "remuneration"},
    "Santé": {"sante", "maladie", "handicap", "medical"},
}
ARCH_TYPES = ("cas_usage", "agent", "outil", "flux", "equipe")   # éléments couverts par la validation d'architecture
# AI Opportunities (incrément 2) : nature de l'opportunité, priorité et champs modifiables par le propriétaire.
OPPORTUNITY_CATEGORIES = {
    "cas_usage_ia": "Cas d'usage IA", "processus_automatisable": "Processus automatisable",
    "assistant": "Assistant intelligent", "multi_agents": "Collaboration multi-agents",
    "ai_builder": "Scénario AI Builder", "workflow": "Workflow d'automatisation",
    "outil_mcp": "Outil ou connecteur MCP", "application": "Application intelligente",
}
PRIORITIES = ("haute", "moyenne", "basse")
OPPORTUNITY_FIELDS = ("description", "domaine", "categorie", "tables", "solution_ia", "gain_attendu", "valeur",
                      "faisabilite", "complexite", "priorite", "limites")
PRIORITY_RULE = ("Priorité calculée : basse si la valeur ou la faisabilité est faible ; haute si la valeur est forte et "
                 "la complexité n'est pas forte ; moyenne sinon. Vous pouvez la forcer.")
MAX_COLUMNS = 40          # colonnes profilées par table (au-delà : signalées, non profilées)
MAX_ITEMS_PER_CALL = 15
KEY_PRECHECK = 0.9        # pré-sélection sur le comptage approximatif (erreur de quelques %), confirmée en exact
_NOT_KEY = ("float", "double", "real", "boolean")   # mesures et indicateurs : jamais clés
_ORDERED = ("tinyint", "smallint", "int", "bigint", "float", "double", "decimal", "date", "timestamp", "long",
            "short", "byte", "integer")


class TransformationError(ValueError):
    """Erreur de règle (droits, statut, preuve) : message destiné à l'utilisateur."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:12]


def _text(v: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _norm(name: str) -> str:
    """Nom de colonne comparé sans casse, accents simples ni séparateurs (Code UIC = code_uic)."""
    t = name.lower()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("â", "a"), ("ô", "o"), ("î", "i"), ("û", "u"),
                 ("ç", "c")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", t)


# --- Découverte -----------------------------------------------------------------------------------------
def _quote(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _ordered(type_text: str) -> bool:
    return (type_text or "").lower().split("(")[0] in _ORDERED


def profile_query(full_name: str, columns: list[dict]) -> str:
    """Une seule requête d'agrégats par table : jamais de colonne brute dans le SELECT."""
    parts = ["count(*) AS `n__`"]
    for i, c in enumerate(columns[:MAX_COLUMNS]):
        q = _quote(c["name"])
        parts += [f"count({q}) AS `nn_{i}`", f"approx_count_distinct({q}) AS `d_{i}`"]
        if _ordered(c.get("type", "")):
            parts += [f"CAST(min({q}) AS STRING) AS `mn_{i}`", f"CAST(max({q}) AS STRING) AS `mx_{i}`"]
    return f"SELECT {', '.join(parts)} FROM {_fq(full_name)}"


def table_profile(info: dict, row: dict) -> dict:
    n = int(row.get("n__") or 0)
    cols = []
    for i, c in enumerate(info["columns"][:MAX_COLUMNS]):
        nn = int(row.get(f"nn_{i}") or 0)
        d = int(row.get(f"d_{i}") or 0)
        base = (c.get("type") or "").lower().split("(")[0]
        col = {"nom": c["name"], "type": c.get("type", ""), "commentaire": c.get("comment") or "",
               "remplissage_pct": round(100.0 * nn / n, 1) if n else None, "valeurs_distinctes": d,
               "distinct_exact": False,   # approx_count_distinct ; exact pour les clés vérifiées
               "cle_candidate": bool(n and nn == n and base not in _NOT_KEY and d >= KEY_PRECHECK * nn)}
        if _ordered(c.get("type", "")):
            col.update(min=row.get(f"mn_{i}"), max=row.get(f"mx_{i}"))
        cols.append(col)
    return {"table": info["full_name"], "commentaire": info.get("comment") or "", "lignes": n, "colonnes": cols,
            "colonnes_non_profilees": max(0, len(info["columns"]) - MAX_COLUMNS),
            "mise_a_jour": info.get("updated_at")}


def infer_links(tables: list[dict]) -> list[dict]:
    """Liens probables : même nom de colonne (normalisé) dans deux tables, clé candidate d'un côté.

    Hypothèses à vérifier : le nom commun ne prouve pas que les valeurs correspondent.
    """
    links = []
    for a in tables:
        for b in tables:
            if a is b or "colonnes" not in a or "colonnes" not in b:
                continue
            bcols = {_norm(c["nom"]): c for c in b["colonnes"]}
            for ca in a["colonnes"]:
                cb = bcols.get(_norm(ca["nom"]))
                if not cb or not cb["cle_candidate"] or len(_norm(ca["nom"])) < 3:
                    continue
                if ca["cle_candidate"] and a["table"] > b["table"]:   # 1-1 : un seul sens
                    continue
                links.append({"de": f"{a['table']}.{ca['nom']}", "vers": f"{b['table']}.{cb['nom']}",
                              "cardinalite": "1-1" if ca["cle_candidate"] else "n-1",
                              "base": "nom de colonne commun, clé candidate côté cible (à vérifier)",
                              "_src": (a["table"], ca["nom"]), "_dst": (b["table"], cb["nom"])})
    return links


def exact_distinct_query(full_name: str, names: list[str]) -> str:
    parts = [f"count(DISTINCT {_quote(c)}) AS `x_{i}`" for i, c in enumerate(names)]
    return f"SELECT {', '.join(parts)} FROM {_fq(full_name)}"


def coverage_query(src: tuple, dst: tuple) -> str:
    """Part des valeurs source retrouvées dans la cible : deux agrégats, aucune valeur renvoyée."""
    s, d = _quote(src[1]), _quote(dst[1])
    return (f"SELECT count(*) AS `n`, count(b.k) AS `found` FROM (SELECT {s} AS k FROM {_fq(src[0])} WHERE {s} IS NOT "
            f"NULL) a LEFT JOIN (SELECT DISTINCT {d} AS k FROM {_fq(dst[0])}) b ON a.k = b.k")


def _fq(full_name: str) -> str:
    return ".".join(_quote(p) for p in full_name.split("."))


def findings(tables: list[dict]) -> list[str]:
    """Constats statistiques (pas des exigences métier)."""
    out = []
    for t in tables:
        if "erreur" in t:
            out.append(f"{t['table']} : profil impossible ({t['erreur']}).")
            continue
        if not t["commentaire"]:
            out.append(f"{t['table']} : table sans description.")
        if t["lignes"] == 0:
            out.append(f"{t['table']} : table vide.")
        undocumented = sum(1 for c in t["colonnes"] if not c["commentaire"])
        if undocumented:
            out.append(f"{t['table']} : {undocumented} colonne(s) sur {len(t['colonnes'])} sans description.")
        for c in t["colonnes"]:
            if c["remplissage_pct"] is not None and c["remplissage_pct"] < 100:
                out.append(f"{t['table']}.{c['nom']} : rempli à {c['remplissage_pct']} %.")
        if t["colonnes_non_profilees"]:
            out.append(f"{t['table']} : {t['colonnes_non_profilees']} colonne(s) au-delà de {MAX_COLUMNS} non profilées.")
    return out


def _column(c: Any) -> dict:
    if isinstance(c, dict):
        return {"name": c["name"], "type": c.get("type", ""), "comment": c.get("comment")}
    return {"name": c.name, "type": getattr(c, "type_text", "") or "", "comment": getattr(c, "comment", None)}


def _table_info(t: Any) -> dict:
    if isinstance(t, dict):
        return {**t, "columns": [_column(c) for c in t.get("columns") or []]}
    upd = getattr(t, "updated_at", None)
    return {"name": t.name, "full_name": t.full_name, "comment": getattr(t, "comment", None),
            "columns": [_column(c) for c in (t.columns or [])],
            "updated_at": datetime.fromtimestamp(upd / 1000, timezone.utc).isoformat(timespec="seconds") if upd else None}


def _tokens(name: str) -> list[str]:
    t = name.lower()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("â", "a"), ("ô", "o"), ("î", "i"), ("û", "u"),
                 ("ç", "c")):
        t = t.replace(a, b)
    return [x for x in re.split(r"[^a-z0-9]+", t) if x]


def column_tags_query(catalog: str) -> str:
    """Étiquettes Unity Catalog des colonnes d'un schéma (paramètre :schema) : métadonnées, aucune valeur."""
    return (f"SELECT table_name, column_name, tag_name, tag_value FROM {_quote(catalog)}.information_schema.column_tags "
            "WHERE schema_name = :schema")


def sensitive_columns(tables: list[dict], tag_rows: list[dict] | None = None) -> list[dict]:
    """Colonnes potentiellement sensibles : étiquettes Unity Catalog, puis indices tirés du nom. Toujours à confirmer."""
    out, seen = [], set()
    by_short = {t["table"].split(".")[-1]: t["table"] for t in tables}
    for r in tag_rows or []:
        full = by_short.get(str(r.get("table_name") or ""))
        if not full:
            continue
        tag = str(r.get("tag_name") or "") + (f" = {r['tag_value']}" if r.get("tag_value") else "")
        out.append({"table": full, "colonne": r.get("column_name"), "categorie": f"Étiquette {tag}",
                    "source": "étiquette Unity Catalog", "statut": "à confirmer"})
        seen.add((full, r.get("column_name")))
    for t in tables:
        for c in t.get("colonnes", []):
            if (t["table"], c["nom"]) in seen:
                continue
            toks = _tokens(c["nom"])
            joined = "".join(toks)
            for cat, words in SENSITIVE_TOKENS.items():
                if any(x in words for x in toks) or joined in words:
                    out.append({"table": t["table"], "colonne": c["nom"], "categorie": cat,
                                "source": "nom de colonne", "statut": "à confirmer"})
                    break
    return out


def perimeter_args(context: dict | None, default_catalog: str, default_schema: str) -> dict:
    """Périmètre enregistré dans le plan ; à défaut, zone de données de la plateforme et tables data_*."""
    per = (context or {}).get("_perimetre") or {}
    if per.get("catalogue") and per.get("schema"):
        tables = list(per.get("tables") or [])
        return {"catalog": per["catalogue"], "schema": per["schema"], "tables": tables,
                "prefix": None if tables else per.get("prefixe", DATA_PREFIX)}
    return {"catalog": default_catalog, "schema": default_schema, "tables": [], "prefix": DATA_PREFIX}


def discover(list_tables: Callable[[str, str], list], sql: Any, catalog: str, schema: str,
             prefix: str | None = DATA_PREFIX, now: Callable[[], str] = _now, tables: list[str] | None = None,
             tags: Callable[[str, str], list] | None = None, max_tables: int = MAX_TABLES) -> dict:
    """Découverte du périmètre choisi avec les droits de l'utilisateur (list_tables, sql et tags sont les siens).

    tables : sélection explicite (prioritaire) ; sinon préfixe (None = toutes les tables du schéma).
    """
    infos = sorted((_table_info(t) for t in list_tables(catalog, schema)), key=lambda i: i["name"])
    if tables:
        wanted = set(tables)
        infos = [i for i in infos if i["name"] in wanted]
    elif prefix:
        infos = [i for i in infos if i["name"].startswith(prefix)]
    if len(infos) > max_tables:
        raise TransformationError(f"{len(infos)} tables dans le périmètre : {max_tables} au maximum par découverte. "
                                  "Réduisez la sélection.")
    explicit = bool(tables)
    selection = {"catalogue": catalog, "schema": schema, "tables": [i["name"] for i in infos],
                 "prefixe": None if explicit else prefix}
    tables = []
    for info in infos:
        try:
            res = sql.query(profile_query(info["full_name"], info["columns"]))
            row = res["rows"][0] if res.get("rows") else {}   # SqlClient : lignes en dictionnaires
            tables.append(table_profile(info, row))
        except Exception as e:  # noqa: BLE001  erreur technique, distincte d'un constat métier
            tables.append({"table": info["full_name"], "erreur": _text(e, 300)})
    for t in tables:   # clés : confirmation par comptage exact (l'approximation peut dépasser le nombre de lignes)
        cand = [c for c in t.get("colonnes", []) if c["cle_candidate"]]
        if not cand:
            continue
        try:
            row = sql.query(exact_distinct_query(t["table"], [c["nom"] for c in cand]))["rows"][0]
            for i, c in enumerate(cand):
                c["valeurs_distinctes"], c["distinct_exact"] = int(row[f"x_{i}"]), True
                c["cle_candidate"] = c["valeurs_distinctes"] == t["lignes"]
        except Exception as e:  # noqa: BLE001
            for c in cand:
                c["cle_candidate"] = False
            t["avertissement"] = f"Vérification exacte des clés impossible : {_text(e, 200)}"
    links = infer_links(tables)
    for link in links:
        try:
            row = sql.query(coverage_query(link["_src"], link["_dst"]))["rows"][0]
            n, found = int(row["n"] or 0), int(row["found"] or 0)
            link["couverture_pct"] = round(100.0 * found / n, 1) if n else None
            link["valeurs_sans_correspondance"] = n - found
        except Exception as e:  # noqa: BLE001
            link["couverture_pct"], link["erreur"] = None, _text(e, 200)
        del link["_src"], link["_dst"]
    found_issues = findings(tables) + [
        f"Lien {l['de']} -> {l['vers']} : {l['valeurs_sans_correspondance']} valeur(s) sans correspondance "
        f"({l['couverture_pct']} % retrouvées)." for l in links if l.get("couverture_pct") not in (None, 100.0)]
    tag_rows, tag_warning = [], None
    if tags is not None:
        try:
            tag_rows = list(tags(catalog, schema) or [])
        except Exception as e:  # noqa: BLE001  droits ou catalogue sans information_schema : non bloquant
            tag_warning = f"Étiquettes Unity Catalog illisibles : {_text(e, 200)}"
    if explicit:
        scope = f"{len(selection['tables'])} table(s) sélectionnée(s)"
    elif prefix:
        scope = f"tables {prefix}*"
    else:
        scope = "toutes les tables"
    out = {"perimetre": f"{catalog}.{schema}, {scope}", "date": now(), "tables": tables,
           "liens_probables": links, "constats": found_issues, "selection": selection,
           "donnees_sensibles": sensitive_columns([t for t in tables if "erreur" not in t], tag_rows),
           "avertissement": "Constats statistiques, sans lecture de lignes ; ce ne sont pas des exigences métier."}
    if tag_warning:
        out["avertissement_etiquettes"] = tag_warning
    return out


def asis_summary(d: dict | None, items: list[dict] | None = None) -> dict | None:
    """Synthèse chiffrée de l'existant (AS-IS) : comptages issus de la découverte et des décisions du plan."""
    if not d:
        return None
    ok = [t for t in d["tables"] if "erreur" not in t]
    cols = [c for t in ok for c in t["colonnes"]]
    links = d.get("liens_probables") or []
    items = items or []

    def count(kind: str, status: str) -> int:
        return sum(1 for i in items if i["item_type"] == kind and i["status"] == status)

    return {"tables": len(ok), "tables_en_erreur": len(d["tables"]) - len(ok),
            "lignes": sum(int(t["lignes"] or 0) for t in ok), "colonnes": len(cols),
            "tables_sans_description": sum(1 for t in ok if not t["commentaire"]),
            "colonnes_sans_description": sum(1 for c in cols if not c["commentaire"]),
            "tables_avec_cle": sum(1 for t in ok if any(c["cle_candidate"] for c in t["colonnes"])),
            "liens": len(links),
            "liens_incomplets": sum(1 for l in links if l.get("couverture_pct") not in (None, 100.0)),
            "colonnes_sensibles": len(d.get("donnees_sensibles") or []),
            "domaines_valides": count("domaine", "valide"), "domaines_proposes": count("domaine", "propose"),
            "objectifs_valides": count("objectif", "valide"), "objectifs_proposes": count("objectif", "propose")}


def heritage_dot(d: dict) -> str:
    """Cartographie du patrimoine : tables découvertes et liens probables (pourcentage de correspondance)."""
    def q(s: str) -> str:
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    sensitive = {s["table"] for s in d.get("donnees_sensibles") or []}
    lines = ["digraph G {", "rankdir=LR;", 'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
             'edge [fontname="Helvetica", fontsize=9, color="#6B6B6B"];']
    for t in d["tables"]:
        short = t["table"].split(".")[-1]
        if "erreur" in t:
            lines.append(f'{q(t["table"])} [label={q(short + chr(10) + "profil impossible")}, fillcolor="#F8D7DA"];')
            continue
        label = f"{short}\n{t['lignes']:,} lignes".replace(",", " ")
        color = "#FDECC8" if t["table"] in sensitive else "#F3E8F0"
        lines.append(f'{q(t["table"])} [label={q(label)}, fillcolor="{color}", color="#4A1942"];')
    for l in d.get("liens_probables") or []:
        src, dst = l["de"].rsplit(".", 1)[0], l["vers"].rsplit(".", 1)[0]
        pct = l.get("couverture_pct")
        label = l["de"].rsplit(".", 1)[1] + (f" ({pct} %)" if pct is not None else "")
        style = "solid" if pct == 100.0 else "dashed"
        lines.append(f"{q(src)} -> {q(dst)} [label={q(label)}, style={style}];")
    lines.append("}")
    return "\n".join(lines)


def architecture_fingerprint(items: list[dict]) -> str:
    """Empreinte de l'architecture (cas d'usage et cible non rejetés) ; le lien vers un objet réel n'en fait pas partie."""
    import hashlib
    rows = sorted((i["item_type"], i["name"], i["status"],
                   json.dumps({k: v for k, v in (i.get("payload") or {}).items() if k != "realisation"},
                              sort_keys=True, ensure_ascii=False, default=str))
                  for i in items if i["item_type"] in ARCH_TYPES and i["status"] != "rejete")
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:16]


def _choice(name: str, field: str, value: Any, allowed) -> str | None:
    v = _text(value, 60).lower() or None
    if v is not None and v not in allowed:
        raise TransformationError(f"« {name} » : {field} attendu parmi {', '.join(allowed)}.")
    return v


def opportunity_fields(name: str, e: dict) -> dict:
    """Champs AI Opportunities d'un cas d'usage (facultatifs ; valeurs fermées contrôlées)."""
    out = {"categorie": _choice(name, "categorie", e.get("categorie"), OPPORTUNITY_CATEGORIES),
           "solution_ia": _text(e.get("solution_ia"), 600) or None,
           "valeur": _choice(name, "valeur", e.get("valeur"), LEVELS),
           "faisabilite": _choice(name, "faisabilite", e.get("faisabilite"), LEVELS),
           "complexite": _choice(name, "complexite", e.get("complexite"), LEVELS),
           "priorite": _choice(name, "priorite", e.get("priorite"), PRIORITIES)}
    return out


def opportunity_priority(valeur: str | None, faisabilite: str | None, complexite: str | None) -> str | None:
    """Règle explicite (PRIORITY_RULE) ; None si un des trois critères manque : pas de priorité devinée."""
    if not (valeur and faisabilite and complexite):
        return None
    if valeur == "faible" or faisabilite == "faible":
        return "basse"
    if valeur == "fort" and complexite != "fort":
        return "haute"
    return "moyenne"


def opportunities(items: list[dict]) -> list[dict]:
    """Vue AI Opportunities : un cas d'usage par ligne, priorité forcée sinon calculée."""
    out = []
    for i in items:
        if i["item_type"] != "cas_usage":
            continue
        pl = i.get("payload") or {}
        computed = opportunity_priority(pl.get("valeur"), pl.get("faisabilite"), pl.get("complexite"))
        out.append({"item_id": i["item_id"], "nom": i["name"], "statut": i["status"], "origine": i.get("origin"),
                    "domaine": pl.get("domaine"), "categorie": pl.get("categorie"),
                    "description": pl.get("description") or "",
                    "tables": (i.get("evidence") or {}).get("tables", []), "solution_ia": pl.get("solution_ia"),
                    "valeur_metier": pl.get("gain_attendu") or "", "valeur": pl.get("valeur"),
                    "faisabilite": pl.get("faisabilite"), "complexite": pl.get("complexite"),
                    "priorite": pl.get("priorite") or computed,
                    "priorite_source": "forcée" if pl.get("priorite") else ("calculée" if computed else None),
                    "limites": pl.get("limites") or [], "modifie_par": pl.get("modifie_par")})
    order = {p: n for n, p in enumerate(PRIORITIES)}
    return sorted(out, key=lambda o: (o["domaine"] or "~", order.get(o["priorite"], 9), o["nom"].lower()))


def validation_state(plan: dict, items: list[dict]) -> dict:
    """Validation d'architecture : non_validee | validee | obsolete (architecture modifiée depuis la validation)."""
    v = (plan.get("context") or {}).get("_validation")
    if not v:
        return {"statut": "non_validee"}
    return {**v, "statut": "validee" if v.get("empreinte") == architecture_fingerprint(items) else "obsolete"}


def discovery_summary(d: dict | None) -> dict | None:
    """Version compacte pour le modèle et l'affichage."""
    if not d:
        return None
    tables = []
    for t in d["tables"]:
        if "erreur" in t:
            tables.append({"table": t["table"], "erreur": t["erreur"]})
            continue
        tables.append({"table": t["table"], "description": t["commentaire"], "lignes": t["lignes"],
                       "colonnes": [c["nom"] for c in t["colonnes"]],
                       "colonnes_sans_description": sum(1 for c in t["colonnes"] if not c["commentaire"]),
                       "cles_candidates": [c["nom"] for c in t["colonnes"] if c["cle_candidate"]],
                       "periodes": {c["nom"]: [c.get("min"), c.get("max")] for c in t["colonnes"]
                                    if c["type"].lower().startswith(("date", "timestamp"))}})
    return {"perimetre": d["perimetre"], "date": d["date"], "tables": tables,
            "liens_probables": d["liens_probables"], "constats": d["constats"],
            "donnees_sensibles": d.get("donnees_sensibles") or [], "avertissement": d["avertissement"]}


# --- Stockage -------------------------------------------------------------------------------------------
class MemoryTransformationStore:
    """Stockage en mémoire (tests)."""

    def __init__(self):
        self.plans: dict[str, dict] = {}
        self.items: dict[tuple, dict] = {}

    def list_plans(self) -> list[dict]:
        return sorted((dict(p) for p in self.plans.values() if p["status"] != "archive"),
                      key=lambda p: p["updated_at"], reverse=True)

    def get_plan(self, plan_id: str) -> dict | None:
        p = self.plans.get(plan_id)
        return dict(p) if p else None

    def insert_plan(self, row: dict) -> None:
        self.plans[row["plan_id"]] = dict(row)

    def update_plan(self, plan_id: str, fields: dict) -> None:
        self.plans[plan_id].update(fields)

    def list_items(self, plan_id: str) -> list[dict]:
        return sorted((dict(i) for (p, _), i in self.items.items() if p == plan_id), key=lambda i: i["created_at"])

    def insert_items(self, rows: list[dict]) -> None:
        for r in rows:
            self.items[(r["plan_id"], r["item_id"])] = dict(r)

    def update_item(self, plan_id: str, item_id: str, fields: dict) -> None:
        self.items[(plan_id, item_id)].update(fields)

    def update_payload(self, plan_id: str, item_id: str, payload: str) -> None:
        self.items[(plan_id, item_id)]["payload"] = payload

    def update_evidence(self, plan_id: str, item_id: str, evidence: str) -> None:
        self.items[(plan_id, item_id)]["evidence"] = evidence


class SqlTransformationStore:
    """Tables transformation_plans / transformation_items (compte de l'application ; règles dans le service)."""

    PLAN_COLS = ("plan_id", "name", "owner", "status", "context", "discovery", "created_at", "updated_at")
    ITEM_COLS = ("plan_id", "item_id", "item_type", "name", "payload", "evidence", "status", "origin", "created_by",
                 "created_at", "decided_by", "decided_at", "decision_note")

    def __init__(self, sql: Any, table: Callable[[str], str]):
        self.sql, self.plans_t, self.items_t = sql, table("transformation_plans"), table("transformation_items")

    def _rows(self, statement: str, params: dict | None = None) -> list[dict]:
        return [dict(r) for r in self.sql.query(statement, params).get("rows") or []]

    def list_plans(self) -> list[dict]:
        return self._rows(f"SELECT {', '.join(self.PLAN_COLS[:4])}, CAST(created_at AS STRING) AS created_at, "
                          f"CAST(updated_at AS STRING) AS updated_at FROM {self.plans_t} "
                          "WHERE status <> 'archive' ORDER BY updated_at DESC")

    def get_plan(self, plan_id: str) -> dict | None:
        rows = self._rows(f"SELECT plan_id, name, owner, status, context, discovery, CAST(created_at AS STRING) AS "
                          f"created_at, CAST(updated_at AS STRING) AS updated_at FROM {self.plans_t} WHERE plan_id = :id",
                          {"id": plan_id})
        return rows[0] if rows else None

    def insert_plan(self, row: dict) -> None:
        self.sql.execute(f"INSERT INTO {self.plans_t} (plan_id, name, owner, status, context, discovery, created_at, "
                         "updated_at) VALUES (:id, :n, :o, :s, CAST(:c AS STRING), CAST(:d AS STRING), "
                         "current_timestamp(), current_timestamp())",
                         {"id": row["plan_id"], "n": row["name"], "o": row["owner"], "s": row["status"],
                          "c": row.get("context"), "d": row.get("discovery")})

    def update_plan(self, plan_id: str, fields: dict) -> None:
        allowed = [k for k in ("name", "status", "context", "discovery") if k in fields]
        sets = ", ".join(f"{k} = CAST(:{k} AS STRING)" for k in allowed)
        self.sql.execute(f"UPDATE {self.plans_t} SET {sets + ', ' if sets else ''}updated_at = current_timestamp() "
                         "WHERE plan_id = :id", {**{k: fields[k] for k in allowed}, "id": plan_id})

    def list_items(self, plan_id: str) -> list[dict]:
        return self._rows(f"SELECT plan_id, item_id, item_type, name, payload, evidence, status, origin, created_by, "
                          "CAST(created_at AS STRING) AS created_at, decided_by, CAST(decided_at AS STRING) AS decided_at, "
                          f"decision_note FROM {self.items_t} WHERE plan_id = :id ORDER BY created_at, item_id",
                          {"id": plan_id})

    def insert_items(self, rows: list[dict]) -> None:
        if not rows:
            return
        values, params = [], {}
        for i, r in enumerate(rows):
            values.append(f"(:p{i}, :i{i}, :t{i}, :n{i}, CAST(:pl{i} AS STRING), CAST(:e{i} AS STRING), :s{i}, :o{i}, "
                          f":c{i}, current_timestamp(), NULL, NULL, NULL)")
            params.update({f"p{i}": r["plan_id"], f"i{i}": r["item_id"], f"t{i}": r["item_type"], f"n{i}": r["name"],
                           f"pl{i}": r.get("payload"), f"e{i}": r.get("evidence"), f"s{i}": r["status"],
                           f"o{i}": r["origin"], f"c{i}": r["created_by"]})
        self.sql.execute(f"INSERT INTO {self.items_t} ({', '.join(self.ITEM_COLS)}) VALUES {', '.join(values)}", params)

    def update_item(self, plan_id: str, item_id: str, fields: dict) -> None:
        self.sql.execute(f"UPDATE {self.items_t} SET status = :s, decided_by = CAST(:b AS STRING), "
                         "decided_at = CASE WHEN CAST(:b AS STRING) IS NULL THEN NULL ELSE current_timestamp() END, "
                         "decision_note = CAST(:n AS STRING) WHERE plan_id = :p AND item_id = :i",
                         {"s": fields["status"], "b": fields.get("decided_by"), "n": fields.get("decision_note"),
                          "p": plan_id, "i": item_id})

    def update_payload(self, plan_id: str, item_id: str, payload: str) -> None:
        self.sql.execute(f"UPDATE {self.items_t} SET payload = CAST(:pl AS STRING) WHERE plan_id = :p AND item_id = :i",
                         {"pl": payload, "p": plan_id, "i": item_id})

    def update_evidence(self, plan_id: str, item_id: str, evidence: str) -> None:
        self.sql.execute(f"UPDATE {self.items_t} SET evidence = CAST(:ev AS STRING) WHERE plan_id = :p AND item_id = :i",
                         {"ev": evidence, "p": plan_id, "i": item_id})


# --- Règles ---------------------------------------------------------------------------------------------
def _load(v: Any) -> Any:
    if v in (None, ""):
        return None
    return json.loads(v) if isinstance(v, str) else v


class TransformationService:
    def __init__(self, store: Any, now: Callable[[], str] = _now):
        self.store, self.now = store, now

    # Plans
    def list_plans(self, user: str, is_admin: bool) -> list[dict]:
        return [p for p in self.store.list_plans() if is_admin or p["owner"] == user]

    def get(self, plan_id: str, user: str, is_admin: bool) -> dict:
        p = self.store.get_plan(plan_id or "")
        if not p or p["status"] == "archive" or not (is_admin or p["owner"] == user):
            raise TransformationError(f"Plan « {plan_id} » introuvable ou non accessible.")
        p["context"], p["discovery"] = _load(p.get("context")) or {}, _load(p.get("discovery"))
        return p

    def _owned(self, plan_id: str, user: str) -> dict:
        p = self.get(plan_id, user, is_admin=True)
        if p["owner"] != user:
            raise TransformationError("Seul le propriétaire du plan peut le modifier ou décider de ses éléments.")
        return p

    def create(self, name: str, user: str) -> dict:
        name = _text(name, 120)
        if not name:
            raise TransformationError("Donnez un nom au plan.")
        row = {"plan_id": _new_id("tp_"), "name": name, "owner": user, "status": "en_cours", "context": None,
               "discovery": None, "created_at": self.now(), "updated_at": self.now()}
        self.store.insert_plan(row)
        return row

    def set_context(self, plan_id: str, user: str, fields: dict) -> dict:
        p = self._owned(plan_id, user)
        unknown = sorted(set(fields) - set(CONTEXT_FIELDS))
        if unknown:
            raise TransformationError(f"Champs de cadrage inconnus : {', '.join(unknown)}.")
        ctx = dict(p["context"])
        for k, v in fields.items():
            if v is not None and _text(v, 2000):
                ctx[k] = _text(v, 2000)
        self.store.update_plan(plan_id, {"context": json.dumps(ctx, ensure_ascii=False), "updated_at": self.now()})
        return ctx

    def set_discovery(self, plan_id: str, user: str, discovery: dict) -> None:
        self._owned(plan_id, user)
        self.store.update_plan(plan_id, {"discovery": json.dumps(discovery, ensure_ascii=False, default=str),
                                         "updated_at": self.now()})

    def _set_internal(self, plan_id: str, user: str, key: str, value: Any) -> dict:
        """Données de session du plan (clés préfixées par _ dans le cadrage JSON), propriétaire seulement."""
        p = self._owned(plan_id, user)
        ctx = dict(p["context"])
        if value is None:
            ctx.pop(key, None)
        else:
            ctx[key] = value
        self.store.update_plan(plan_id, {"context": json.dumps(ctx, ensure_ascii=False, default=str),
                                         "updated_at": self.now()})
        return ctx

    def set_perimeter(self, plan_id: str, user: str, catalog: str, schema: str, tables: list[str] | None = None,
                      prefix: str | None = None) -> dict:
        if not _NAME_RE.match(catalog or "") or not _NAME_RE.match(schema or ""):
            raise TransformationError("Catalogue ou schéma invalide.")
        tables = [t for t in dict.fromkeys(tables or []) if t]
        if any(not _NAME_RE.match(t) for t in tables):
            raise TransformationError("Nom de table invalide dans la sélection.")
        if len(tables) > MAX_TABLES:
            raise TransformationError(f"{len(tables)} tables sélectionnées : {MAX_TABLES} au maximum.")
        if not tables and not prefix:
            raise TransformationError("Sélectionnez au moins une table.")
        per = {"catalogue": catalog, "schema": schema, "tables": tables, "prefixe": None if tables else prefix}
        return self._set_internal(plan_id, user, "_perimetre", per)["_perimetre"]

    def set_business_notes(self, plan_id: str, user: str, notes: dict) -> dict:
        """Informations métier saisies par l'utilisateur, par table (complètent les descriptions Unity Catalog)."""
        clean = {str(k): _text(v, 1000) for k, v in (notes or {}).items() if _text(v, 1000)}
        return self._set_internal(plan_id, user, "_notes_metier", clean or None).get("_notes_metier", {})

    def validate_architecture(self, plan_id: str, user: str) -> dict:
        """Validation explicite de l'architecture cible ; elle devient obsolète dès que l'architecture change."""
        self._owned(plan_id, user)
        items = self.items(plan_id, user, is_admin=True)
        if not any(i["item_type"] in TARGET_TYPES and i["status"] == "valide" for i in items):
            raise TransformationError("Aucun élément de cible validé : rien à valider.")
        problems = self.coherence(items)
        if problems:
            raise TransformationError("Architecture incohérente : " + " ".join(problems))
        v = {"empreinte": architecture_fingerprint(items), "par": user, "le": self.now()}
        self._set_internal(plan_id, user, "_validation", v)
        return v

    def update_opportunity(self, plan_id: str, user: str, item_id: str, fields: dict) -> dict:
        """Modification d'un cas d'usage par le propriétaire (le nom, clé des rattachements, ne change pas).

        Le statut est conservé ; la modification est tracée et rend obsolète une validation d'architecture."""
        p = self._owned(plan_id, user)
        unknown = sorted(set(fields) - set(OPPORTUNITY_FIELDS))
        if unknown:
            raise TransformationError(f"Champs non modifiables : {', '.join(unknown)}.")
        current = self.store.list_items(plan_id)
        it = next((i for i in current if i["item_id"] == item_id), None)
        if not it or it["item_type"] != "cas_usage":
            raise TransformationError("Opportunité introuvable dans ce plan.")
        name, payload, evidence = it["name"], _load(it.get("payload")) or {}, _load(it.get("evidence")) or {}
        domains = {i["name"].lower(): i["name"] for i in current if i["item_type"] == "domaine" and i["status"] == "valide"}
        for k, v in fields.items():
            if k == "tables":
                known = {t["table"] for t in (p["discovery"] or {}).get("tables", []) if "erreur" not in t}
                short = {x.split(".")[-1]: x for x in known}
                tables = []
                for t in v or []:
                    full = t if t in known else short.get(str(t))
                    if not full:
                        raise TransformationError(f"Table « {t} » absente de la découverte.")
                    tables.append(full)
                if not tables:
                    raise TransformationError(f"« {name} » : au moins une table découverte (preuve).")
                evidence["tables"] = list(dict.fromkeys(tables))
            elif k == "domaine":
                dom = _text(v, 120)
                if dom and dom.lower() not in domains:
                    raise TransformationError(f"Domaine « {dom} » non validé (validés : "
                                              f"{', '.join(domains.values()) or 'aucun'}).")
                payload["domaine"] = domains.get(dom.lower()) if dom else None
            elif k == "limites":
                payload["limites"] = [_text(x, 300) for x in (v or []) if _text(x, 300)][:10]
            elif k in ("description",):
                payload[k] = _text(v, 2000)
            elif k == "gain_attendu":
                payload[k] = _text(v, 600)
            else:   # champs fermés et solution IA
                payload.update({k: opportunity_fields(name, {k: v})[k]})
        payload["modifie_par"], payload["modifie_le"] = user, self.now()
        self.store.update_payload(plan_id, item_id, json.dumps(payload, ensure_ascii=False))
        if "tables" in fields:
            self.store.update_evidence(plan_id, item_id, json.dumps(evidence, ensure_ascii=False))
        self.store.update_plan(plan_id, {"updated_at": self.now()})
        return payload

    # Éléments
    def items(self, plan_id: str, user: str, is_admin: bool) -> list[dict]:
        self.get(plan_id, user, is_admin)
        out = []
        for i in self.store.list_items(plan_id):
            i["payload"], i["evidence"] = _load(i.get("payload")) or {}, _load(i.get("evidence")) or {}
            out.append(i)
        return out

    def propose(self, plan_id: str, user: str, elements: list[dict], origin: str = "hakim",
                existing: dict | None = None) -> dict:
        """Ajoute des éléments d'UNE étape au statut « propose ».

        existing : objets de la plateforme visibles par l'utilisateur ({"agent": {id: nom}, "outil": ..., "flux": ...,
        "equipe": ...}) ; obligatoire pour l'étape 5 (réutilisation vérifiée).
        """
        p = self._owned(plan_id, user)
        if not isinstance(elements, list) or not elements:
            raise TransformationError("Aucun élément à proposer.")
        if len(elements) > MAX_ITEMS_PER_CALL:
            raise TransformationError(f"{MAX_ITEMS_PER_CALL} éléments au plus par proposition.")
        step = proposal_step(elements)
        if step == 5 and existing is None:
            raise TransformationError("Catalogue de la plateforme indisponible : réutilisation non vérifiable.")
        known = {t["table"] for t in (p["discovery"] or {}).get("tables", []) if "erreur" not in t}
        short = {k.split(".")[-1]: k for k in known}
        current = self.store.list_items(plan_id)
        dupes = {(i["item_type"], i["name"].lower()) for i in current if i["status"] != "rejete"}
        validated = {k: {i["name"].lower(): i["name"] for i in current if i["item_type"] == k and i["status"] == "valide"}
                     for k in ITEM_TYPES}
        in_plan = {k: {i["name"].lower(): i["name"] for i in current if i["item_type"] == k and i["status"] != "rejete"}
                   for k in TARGET_TYPES}
        for e in elements:   # éléments proposés ensemble : un agent peut citer un outil du même envoi
            if e.get("type") in TARGET_TYPES and _text(e.get("nom"), 120):
                in_plan[e["type"]][_text(e["nom"], 120).lower()] = _text(e["nom"], 120)
        roadmap = self._roadmap_state(current, elements) if step == 6 else None
        rows, skipped = [], []
        for e in elements:
            kind, name = e.get("type"), _text(e.get("nom"), 120)
            if not name:
                raise TransformationError("Chaque élément doit avoir un nom.")
            tables = []
            for t in e.get("tables") or []:
                full = t if t in known else short.get(str(t))
                if not full:
                    raise TransformationError(f"Table « {t} » absente de la découverte : lancez la découverte ou "
                                              "citez une table découverte.")
                tables.append(full)
            if kind in ("domaine", "processus", "cas_usage") and not tables:
                raise TransformationError(f"« {name} » : un {ITEM_LABELS[kind].lower()} doit citer au moins une table "
                                          "découverte (preuve).")
            if (kind, name.lower()) in dupes:
                skipped.append(name)
                continue
            dupes.add((kind, name.lower()))
            payload = {"description": _text(e.get("description"), 2000),
                       "hypotheses": [_text(h, 300) for h in (e.get("hypotheses") or [])][:10],
                       "domaine": _text(e.get("domaine"), 120) or None}
            evidence = {"tables": tables}
            if kind == "cas_usage":
                payload.update(self._use_case(name, e, validated))
                if payload["processus"]:
                    evidence["processus"] = payload["processus"]
            elif kind in TARGET_TYPES:
                payload.update(self._target(kind, name, e, tables, validated, in_plan, existing))
                evidence["cas_usage"] = payload["cas_usage"]
            elif kind == "vague":
                payload.update(self._wave(name, e, roadmap))
                evidence["elements"] = payload["elements"]
            rows.append({"plan_id": plan_id, "item_id": _new_id("ti_"), "item_type": kind, "name": name,
                         "payload": json.dumps(payload, ensure_ascii=False),
                         "evidence": json.dumps(evidence, ensure_ascii=False), "status": "propose",
                         "origin": origin, "created_by": user, "created_at": self.now(), "decided_by": None,
                         "decided_at": None, "decision_note": None})
        self.store.insert_items(rows)
        self.store.update_plan(plan_id, {"updated_at": self.now()})
        return {"etape": step, "ajoutes": [{"item_id": r["item_id"], "type": r["item_type"], "nom": r["name"]}
                                           for r in rows], "deja_presents": skipped}

    @staticmethod
    def _use_case(name: str, e: dict, validated: dict) -> dict:
        """Étape 4 : cas d'usage appuyé sur des tables découvertes ; gain décrit sans chiffre inventé, limites listées.

        Processus facultatif (reportés) ; s'il est cité, il doit être VALIDÉ dans le plan."""
        cited, proc = _text(e.get("processus"), 120), None
        if cited:
            proc = validated["processus"].get(cited.lower())
            if not proc:
                raise TransformationError(f"« {name} » : citez un processus VALIDÉ du plan ou aucun processus (validés : "
                                          f"{', '.join(validated['processus'].values()) or 'aucun'}).")
        obj = _text(e.get("objectif"), 120)
        if obj and obj.lower() not in validated["objectif"]:
            raise TransformationError(f"« {name} » : objectif « {obj} » non validé dans le plan.")
        out = {"processus": proc, "objectif": validated["objectif"].get(obj.lower()) if obj else None,
               "gain_attendu": _text(e.get("gain_attendu"), 600),
               "limites": [_text(x, 300) for x in (e.get("limites") or [])][:10]}
        dom = _text(e.get("domaine"), 120)
        if dom:
            if dom.lower() not in validated["domaine"]:
                raise TransformationError(f"« {name} » : domaine « {dom} » non validé dans le plan (validés : "
                                          f"{', '.join(validated['domaine'].values()) or 'aucun'}).")
            out["domaine"] = validated["domaine"][dom.lower()]
        out.update(opportunity_fields(name, e))
        return out

    @staticmethod
    def _target(kind: str, name: str, e: dict, tables: list, validated: dict, in_plan: dict,
                existing: dict) -> dict:
        """Étape 5 : sert des cas d'usage VALIDÉS ; réutilisation d'un objet réel de la plateforme vérifiée."""
        cases = []
        for c in e.get("cas_usage") or []:
            v = validated["cas_usage"].get(_text(c, 120).lower())
            if not v:
                raise TransformationError(f"« {name} » : cas d'usage « {c} » non validé (validés : "
                                          f"{', '.join(validated['cas_usage'].values()) or 'aucun'}).")
            cases.append(v)
        if not cases:
            raise TransformationError(f"« {name} » : citez au moins un cas d'usage validé qu'il sert.")
        mode, ref = e.get("mode"), _text(e.get("existant"), 200)
        if mode not in MODES:
            raise TransformationError(f"« {name} » : mode attendu parmi {', '.join(MODES)}.")
        catalog = (existing or {}).get(kind) or {}
        if mode == "creer" and ref:
            raise TransformationError(f"« {name} » : mode « creer » sans objet existant (sinon « adapter »).")
        if mode != "creer" and ref not in catalog:
            raise TransformationError(f"« {name} » : « {ref or '(vide)'} » n'est pas un(e) {ITEM_LABELS[kind].lower()} "
                                      "existant(e) visible ; donnez son identifiant exact ou choisissez « creer ».")
        if kind == "outil" and mode == "creer" and not tables:
            raise TransformationError(f"« {name} » : un nouvel outil cite les tables découvertes qu'il interroge.")

        def refs(field: str, ref_kind: str) -> list[str]:
            out = []
            for r in e.get(field) or []:
                r = _text(r, 200)
                hit = in_plan[ref_kind].get(r.lower()) or ((existing or {}).get(ref_kind) or {}).get(r) and r
                if not hit:
                    raise TransformationError(f"« {name} » : « {r} » n'est ni un(e) {ITEM_LABELS[ref_kind].lower()} du "
                                              "plan ni un objet existant (identifiant exact).")
                out.append(hit)
            return out

        return {"cas_usage": cases, "mode": mode, "existant": ref or None,
                "existant_nom": catalog.get(ref) if ref else None,
                "membres": refs("membres", "agent") if kind == "equipe" else [],
                "outils": refs("outils", "outil") if kind == "agent" else []}

    @staticmethod
    def _wave_elements(payload: dict) -> list[dict]:
        """Éléments d'une vague, normalisés en {type, nom} ; tolère les anciens payloads stockés en chaînes."""
        payload = _load(payload) or {}
        out = []
        for x in (payload or {}).get("elements") or []:
            if isinstance(x, dict) and x.get("type") and x.get("nom"):
                out.append({"type": x["type"], "nom": x["nom"]})
            elif isinstance(x, str) and _text(x, 200):
                raw = _text(x, 200)
                kind, _, label = raw.partition(":") if ":" in raw else (None, "", raw)
                out.append({"type": kind or "?", "nom": label.strip()})
        return out

    @classmethod
    def _roadmap_state(cls, current: list[dict], elements: list[dict]) -> dict:
        """État de l'étape 6 : cible validée, éléments déjà placés et vagues connues (plan + envoi courant)."""
        targets: dict[str, list] = {}
        for i in current:
            if i["item_type"] in TARGET_TYPES and i["status"] == "valide":
                targets.setdefault(i["name"].lower(), []).append({"type": i["item_type"], "nom": i["name"]})
        waves = [i for i in current if i["item_type"] == "vague" and i["status"] != "rejete"]
        placed = {(x["type"], x["nom"]): w["name"] for w in waves for x in cls._wave_elements(w["payload"])}
        orders = {w["name"].lower(): (w["name"], (_load(w["payload"]) or {}).get("ordre")) for w in waves}
        for e in elements:
            name = _text(e.get("nom"), 120)
            if e.get("type") == "vague" and name and name.lower() not in orders:
                orders[name.lower()] = (name, e.get("ordre"))
        return {"targets": targets, "placed": placed, "orders": orders}

    @staticmethod
    def _wave(name: str, e: dict, st: dict) -> dict:
        """Étape 6 : une vague ordonnée d'éléments de la cible VALIDÉS, avec valeur/effort justifiés."""
        order = e.get("ordre")
        if not isinstance(order, int) or isinstance(order, bool) or not 1 <= order <= 20:
            raise TransformationError(f"« {name} » : ordre de vague attendu (entier de 1 à 20).")
        for field in ("valeur", "effort"):
            if e.get(field) not in LEVELS:
                raise TransformationError(f"« {name} » : {field} attendu parmi {', '.join(LEVELS)}.")
        if not _text(e.get("justification"), 1000):
            raise TransformationError(f"« {name} » : justifiez la valeur et l'effort, sans chiffre ni seuil inventé.")
        chosen = []
        for ref in e.get("elements") or []:
            raw = _text(ref, 200)
            kind, _, label = raw.partition(":") if ":" in raw else (None, "", raw)
            hits = [x for x in st["targets"].get(label.strip().lower(), []) if kind in (None, x["type"])]
            if not hits:
                raise TransformationError(f"« {name} » : « {raw} » n'est pas un élément de la cible VALIDÉ.")
            if len(hits) > 1:
                raise TransformationError(f"« {name} » : « {raw} » est ambigu ; précisez type:nom.")
            key = (hits[0]["type"], hits[0]["nom"])
            if key in st["placed"]:
                raise TransformationError(f"« {name} » : « {hits[0]['nom']} » est déjà dans la vague « {st['placed'][key]} ».")
            st["placed"][key] = name
            chosen.append(hits[0])
        if not chosen:
            raise TransformationError(f"« {name} » : une vague contient au moins un élément de la cible validé.")
        deps = []
        for dep in e.get("dependances") or []:
            hit = st["orders"].get(_text(dep, 120).lower())
            if not hit or hit[0].lower() == name.lower():
                raise TransformationError(f"« {name} » : dépendance « {dep} » inconnue.")
            if not isinstance(hit[1], int) or hit[1] >= order:
                raise TransformationError(f"« {name} » : une vague ne dépend que d'une vague d'ordre inférieur.")
            deps.append(hit[0])
        return {"ordre": order, "elements": chosen, "valeur": e["valeur"], "effort": e["effort"],
                "justification": _text(e["justification"], 1000), "dependances": deps,
                "prerequis": [_text(x, 300) for x in (e.get("prerequis") or [])][:10],
                "risques": [_text(x, 300) for x in (e.get("risques") or [])][:10]}

    @classmethod
    def planned(cls, items: list[dict]) -> list[dict]:
        """Éléments validés, placés dans une vague validée, ordonnés par vague."""
        by_key = {(i["item_type"], i["name"]): i for i in items if i["item_type"] in TARGET_TYPES and i["status"] == "valide"}
        waves = sorted((w for w in items if w["item_type"] == "vague" and w["status"] == "valide"),
                       key=lambda w: (w["payload"].get("ordre") or 99, w["name"]))
        out = []
        for w in waves:
            for x in cls._wave_elements(w["payload"]):
                if (x["type"], x["nom"]) in by_key:
                    out.append({"vague": w["name"], "ordre": w["payload"].get("ordre"), "item": by_key[(x["type"], x["nom"])]})
        return out

    @classmethod
    def tracking(cls, items: list[dict], catalog: dict | None) -> list[dict]:
        """Étape 7 : suivi des objets réels liés ou réutilisés, et prochaine action."""
        out = []
        for row in cls.planned(items):
            i, pl = row["item"], row["item"]["payload"]
            real = pl.get("realisation") or {}
            obj = real.get("objet_id") or (pl.get("existant") if pl.get("mode") == "reutiliser" else None)
            live = ((catalog or {}).get(i["item_type"]) or {}).get(obj) if obj else None
            state = ("a_faire" if not obj else "introuvable" if catalog is not None and not live
                     else "publie" if (live or {}).get("statut") == "publie" else "brouillon")
            nxt = {"a_faire": {"creer": "créer ou concevoir le brouillon, puis le relier",
                               "adapter": "modifier l'objet existant, puis le relier"}.get(pl.get("mode"), ""),
                   "brouillon": "tester puis demander la publication",
                   "publie": "", "introuvable": "objet non visible ou archivé : relier un autre objet"}[state]
            out.append({"vague": row["vague"], "ordre": row["ordre"], "item_id": i["item_id"], "type": i["item_type"],
                        "nom": i["name"], "mode": pl.get("mode"), "objet_id": obj,
                        "objet_nom": (live or {}).get("nom") or real.get("objet_nom"), "statut": state,
                        "prochaine_action": nxt, "relie_par": real.get("lie_par"), "relie_le": real.get("lie_le")})
        return out

    def link(self, plan_id: str, user: str, element: str, objet: str, catalog: dict) -> dict:
        """Relie un élément planifié à l'objet réel créé ou adapté, jamais à une réutilisation déjà en place."""
        self._owned(plan_id, user)
        items = self.items(plan_id, user, False)
        ref = _text(element, 200)
        rows = [r for r in self.planned(items) if ref in (r["item"]["item_id"], r["item"]["name"])
                or ref.lower() in (r["item"]["name"].lower(), f"{r['item']['item_type']}:{r['item']['name']}".lower())]
        if len(rows) != 1:
            raise TransformationError(f"« {element} » : élément planifié introuvable"
                                      + (" ou ambigu (précisez type:nom)" if rows else "") + ".")
        i, pl = rows[0]["item"], dict(rows[0]["item"]["payload"])
        if pl.get("mode") == "reutiliser":
            raise TransformationError(f"« {i['name']} » réutilise déjà {pl.get('existant')} : rien à relier.")
        if (pl.get("realisation") or {}).get("objet_id"):
            raise TransformationError(f"« {i['name']} » est déjà relié à {pl['realisation']['objet_id']}.")
        obj = _text(objet, 200)
        live = (catalog.get(i["item_type"]) or {}).get(obj)
        if not live:
            raise TransformationError(f"« {objet} » n'est pas un(e) {ITEM_LABELS[i['item_type']].lower()} visible.")
        if pl.get("mode") == "adapter" and obj != pl.get("existant"):
            raise TransformationError(f"« {i['name']} » adapte {pl.get('existant')} : reliez cet objet-là.")
        taken = {(x["item_type"], (x["payload"].get("realisation") or {}).get("objet_id")) for x in items
                 if x["item_id"] != i["item_id"]}
        if pl.get("mode") == "creer" and (i["item_type"], obj) in taken:
            raise TransformationError(f"« {obj} » est déjà relié à un autre élément du plan.")
        pl["realisation"] = {"objet_id": obj, "objet_nom": live["nom"], "lie_par": user, "lie_le": self.now()}
        self.store.update_payload(plan_id, i["item_id"], json.dumps(pl, ensure_ascii=False))
        self.store.update_plan(plan_id, {"updated_at": self.now()})
        return {"element": i["name"], "type": i["item_type"], "objet_id": obj, "objet_nom": live["nom"],
                "statut_objet": live.get("statut")}

    def decide_many(self, plan_id: str, user: str, item_ids: list[str], status: str) -> int:
        """Décision groupée (bouton « Tout valider ») : mêmes règles que decide, élément par élément."""
        self._owned(plan_id, user)
        known = {i["item_id"] for i in self.store.list_items(plan_id)}
        missing = [i for i in item_ids if i not in known]
        if missing or not item_ids:
            raise TransformationError("Élément(s) introuvable(s) dans ce plan." if missing else "Aucun élément.")
        for item_id in item_ids:
            self.decide(plan_id, item_id, user, status)
        return len(item_ids)

    def decide(self, plan_id: str, item_id: str, user: str, status: str, note: str = "") -> None:
        """Décision humaine (page Transformation) : valide, rejete, ou propose pour rouvrir."""
        self._owned(plan_id, user)
        if status not in STATUSES:
            raise TransformationError(f"Statut inconnu : {status}.")
        if not any(i["item_id"] == item_id for i in self.store.list_items(plan_id)):
            raise TransformationError("Élément introuvable dans ce plan.")
        decided = status != "propose"
        self.store.update_item(plan_id, item_id, {"status": status, "decided_by": user if decided else None,
                                                  "decided_at": self.now() if decided else None,
                                                  "decision_note": _text(note, 500) or None})
        self.store.update_plan(plan_id, {"updated_at": self.now()})

    # Avancement
    @classmethod
    def progress(cls, plan: dict, items: list[dict], catalog: dict | None = None) -> list[dict]:
        """catalog : objets réels visibles ; sans lui, l'étape 7 ne peut pas être évaluée à « fait »."""
        ctx, valid = plan.get("context") or {}, {i["item_type"] for i in items if i["status"] == "valide"}
        procs = {i["name"] for i in items if i["item_type"] == "processus" and i["status"] == "valide"}
        cases = {i["name"] for i in items if i["item_type"] == "cas_usage" and i["status"] == "valide"
                 and (not i["payload"].get("processus") or i["payload"]["processus"] in procs)}
        served = {c for i in items if i["item_type"] in TARGET_TYPES and i["status"] == "valide"
                  for c in i["payload"].get("cas_usage") or []}
        done = {1: bool(ctx.get("secteur") and ctx.get("objectifs")), 2: bool(plan.get("discovery")),
                3: "domaine" in valid and bool(valid & {"objectif", "processus"}), 4: bool(cases),
                5: bool(cases) and cases <= served and not cls.coherence(items)}
        targets = {(i["item_type"], i["name"]) for i in items if i["item_type"] in TARGET_TYPES and i["status"] == "valide"}
        planned = {(r["item"]["item_type"], r["item"]["name"]) for r in cls.planned(items)}
        done[6] = done[5] and targets <= planned and not cls.coherence(items)
        track = cls.tracking(items, catalog) if catalog is not None else []
        done[7] = done[6] and catalog is not None and bool(track) and all(t["statut"] == "publie" for t in track)
        out, current = [], None
        for n, key, label in STEPS:
            if n > AVAILABLE_LAST_STEP:
                status = "lot_b2"
            elif done[n]:
                status = "fait"
            elif current is None:
                status, current = "en_cours", n
            else:
                status = "a_faire"
            out.append({"etape": n, "cle": key, "libelle": label, "statut": status})
        return out

    @staticmethod
    def gaps(items: list[dict], catalog: dict | None = None) -> list[dict]:
        """Écarts AS-IS → TO-BE : pour chaque cas d'usage non rejeté, les éléments de la cible non rejetés qui le
        servent, avec le type de changement et l'état de l'objet réel. Un cas sans cible est signalé."""
        targets = [i for i in items if i["item_type"] in TARGET_TYPES and i["status"] != "rejete"]
        out = []
        for c in items:
            if c["item_type"] != "cas_usage" or c["status"] == "rejete":
                continue
            base = {"cas_usage": c["name"], "statut_cas": c["status"], "tables": (c.get("evidence") or {}).get("tables") or [],
                    "limites": (c.get("payload") or {}).get("limites") or []}
            served = [t for t in targets if c["name"] in (t["payload"].get("cas_usage") or [])]
            if not served:
                out.append({**base, "type": None, "element": None, "changement": "Aucune cible", "statut_element": None,
                            "objet": None, "statut_objet": None})
            for t in served:
                pl = t["payload"]
                obj = (pl.get("realisation") or {}).get("objet_id") or pl.get("existant")
                live = ((catalog or {}).get(t["item_type"]) or {}).get(obj) if obj else None
                out.append({**base, "type": t["item_type"], "element": t["name"],
                            "changement": CHANGE_LABELS.get(pl.get("mode"), pl.get("mode") or "—"),
                            "statut_element": t["status"], "objet": (live or {}).get("nom") or pl.get("existant_nom") or obj,
                            "statut_objet": (live or {}).get("statut")})
        return out

    @staticmethod
    def coherence(items: list[dict]) -> list[str]:
        """Éléments validés dont un parent n'est plus validé (rejeté ou rouvert après coup)."""
        ok = {(i["item_type"], i["name"]) for i in items if i["status"] == "valide"}
        out = []
        for i in items:
            if i["status"] != "valide":
                continue
            parents = ([("processus", i["payload"].get("processus"))] if i["item_type"] == "cas_usage" else
                       [("cas_usage", c) for c in i["payload"].get("cas_usage") or []] if i["item_type"] in TARGET_TYPES
                       else [(x["type"], x["nom"]) for x in TransformationService._wave_elements(i["payload"])]
                            + [("vague", d) for d in i["payload"].get("dependances") or []] if i["item_type"] == "vague"
                       else [])
            for kind, name in parents:
                if name and (kind, name) not in ok:
                    out.append(f"{ITEM_LABELS[i['item_type']]} « {i['name']} » validé alors que son "
                               f"{ITEM_LABELS[kind].lower()} « {name} » ne l'est plus : à revoir.")
        return out


def org_chart(items: list[dict], root: str = "Cible", catalog: dict | None = None) -> dict:
    """Organigramme de la cible (TO-BE) : plan → équipes → agents → outils et flux. Éléments rejetés exclus ;
    les objets cités mais hors plan (références existantes) apparaissent comme « existant »."""
    live = [i for i in items if i["item_type"] in TARGET_TYPES and i["status"] != "rejete"]
    nodes, edges = {"root": {"type": "plan", "nom": root, "statut": None, "mode": None}}, []
    key = {}
    for i in live:
        k = f"{i['item_type']}:{i['name']}"
        key[(i["item_type"], i["name"].lower())] = k
        nodes[k] = {"type": i["item_type"], "nom": i["name"], "statut": i["status"], "mode": i["payload"].get("mode"),
                    "existant": i["payload"].get("existant_nom") or i["payload"].get("existant")}

    def ref(kind: str, name: str) -> str:
        k = key.get((kind, name.lower()))
        if not k:
            k = f"{kind}:{name}"
            label = (((catalog or {}).get(kind) or {}).get(name) or {}).get("nom") or name   # identifiant → nom lisible
            nodes.setdefault(k, {"type": kind, "nom": label, "statut": "existant", "mode": None, "existant": name})
        return k

    in_team, has_parent = set(), set()
    for i in live:
        if i["item_type"] == "equipe":
            edges.append(("root", key[("equipe", i["name"].lower())]))
            for m in i["payload"].get("membres") or []:
                a = ref("agent", m)
                edges.append((key[("equipe", i["name"].lower())], a))
                in_team.add(a)
    for i in live:
        if i["item_type"] == "agent":
            a = key[("agent", i["name"].lower())]
            if a not in in_team:
                edges.append(("root", a))
            for o in i["payload"].get("outils") or []:
                t = key.get(("outil", o.lower())) or key.get(("flux", o.lower())) or ref("outil", o)
                edges.append((a, t))
                has_parent.add(t)
    for k, n in nodes.items():   # outils et flux du plan non rattachés à un agent
        if n["type"] in ("outil", "flux") and k not in has_parent and n["statut"] != "existant":
            edges.append(("root", k))
    return {"nodes": nodes, "edges": list(dict.fromkeys(edges))}


_ORG_STYLE = {"plan": ("#4A1942", "white", "box"), "equipe": ("#B0124F", "white", "box"),
              "agent": ("#7A3E9D", "white", "box"), "outil": ("#F3E9F7", "#4A1942", "ellipse"),
              "flux": ("#FDE9F0", "#B0124F", "hexagon")}
_ORG_STATUS = {"valide": "Validé", "propose": "Proposé", "existant": "Existant"}


def org_chart_dot(chart: dict) -> str:
    """Graphviz DOT de l'organigramme : trait plein = validé ou existant, pointillé = proposé."""
    def q(s: str) -> str:
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    ids = {k: f"n{i}" for i, k in enumerate(chart["nodes"])}
    out = ["digraph G {", "rankdir=TB; nodesep=0.3; ranksep=0.5;",
           'node [fontname="Segoe UI", fontsize=11, style="filled,rounded", penwidth=1.5];', 'edge [color="#888888"];']
    for k, n in chart["nodes"].items():
        fill, font, shape = _ORG_STYLE.get(n["type"], ("white", "black", "box"))
        sub = ITEM_LABELS.get(n["type"], "Plan") + (f" · {MODES[n['mode']]}" if n.get("mode") in MODES else "")
        if n["statut"]:
            sub += f" · {_ORG_STATUS.get(n['statut'], n['statut'])}"
        style = "filled,rounded,dashed" if n["statut"] == "propose" else "filled,rounded"
        out.append(f"{ids[k]} [label={q(n['nom'] + chr(10) + sub)}, shape={shape}, fillcolor={q(fill)}, "
                   f"fontcolor={q(font)}, style={q(style)}];")
    for a, b in chart["edges"]:
        dashed = chart["nodes"][b]["statut"] == "propose"
        out.append(f"{ids[a]} -> {ids[b]}" + (" [style=dashed]" if dashed else "") + ";")
    out.append("}")
    return "\n".join(out)


def phases(steps: list[dict]) -> list[dict]:
    """Regroupe l'avancement des 7 étapes en 4 phases, avec l'action attendue pour l'étape en cours."""
    by_n = {s["etape"]: s["statut"] for s in steps}
    out = []
    for key, label, nums in PHASES:
        sts = [by_n.get(n, "a_faire") for n in nums]
        status = "fait" if all(s == "fait" for s in sts) else "en_cours" if "en_cours" in sts or "fait" in sts else "a_faire"
        current = next((n for n in nums if by_n.get(n) == "en_cours"), None)
        out.append({"cle": key, "libelle": label, "etapes": list(nums), "statut": status,
                    "action": NEXT_ACTION[current] if current else None})
    return out


def next_action(steps: list[dict]) -> str:
    current = next((s["etape"] for s in steps if s["statut"] == "en_cours"), None)
    return NEXT_ACTION[current] if current else "Démarche terminée : tous les objets prévus sont publiés."


def proposal_step(elements: list[dict]) -> int:
    """Étape d'un envoi de propositions : une seule étape par envoi, et seulement les étapes disponibles."""
    if not elements:
        raise TransformationError("Aucun élément à proposer.")
    steps = set()
    for e in elements:
        kind = e.get("type") if isinstance(e, dict) else None
        if kind not in ITEM_TYPES_AVAILABLE:
            raise TransformationError(f"Type « {kind} » non disponible (types : {', '.join(ITEM_TYPES_AVAILABLE)}).")
        steps.add(ITEM_STEP[kind])
    if len(steps) > 1:
        raise TransformationError("Une proposition ne couvre qu'une étape : étape 3 (objectif, domaine), "
                                  "4 (cas_usage), 5 (agent, outil, flux, equipe) ou 6 (vague).")
    return steps.pop()


def platform_catalog(agents: list[dict], tools: list, teams: list[dict]) -> dict:
    """Objets visibles par l'utilisateur, normalisés pour le suivi du plan."""
    out: dict[str, dict] = {"agent": {}, "outil": {}, "flux": {}, "equipe": {}}
    for a in agents:
        if a.get("status") != "archive":
            out["agent"][a["agent_id"]] = {"nom": a.get("name") or a["agent_id"], "statut": a.get("status")}
    for s in tools:
        if s.status != "archive":
            out["flux" if s.category == "Flux" else "outil"][s.tool_id] = {"nom": s.name, "statut": s.status}
    for t in teams:
        if t.get("status") != "archive":
            out["equipe"][t["team_id"]] = {"nom": t["name"], "statut": t.get("status")}
    return out


def catalog_names(catalog: dict) -> dict:
    return {kind: {oid: obj["nom"] for oid, obj in objs.items()} for kind, objs in catalog.items()}
