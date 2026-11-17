"""Construction, vérification et test des outils créés dans DISCOVERY.

Un outil créé est une configuration déclarative (requête SQL paramétrée ou fonction Unity Catalog) exécutée par
un exécuteur générique de tools/custom_tools.py. Aucun code fourni par l'utilisateur ou par le modèle n'est exécuté.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field

from backend.sql_guard import SqlGuardError, check_read_only, extract_table_refs
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec
from tools.custom_tools import (METHODS, PARAM_NAME, UC_NAME, check_http_config, http_parts, http_placeholders,
                                placeholders)

EXECUTORS = {"sql_template": "tools.custom_tools:sql_template", "uc_function": "tools.custom_tools:uc_function",
             "http_connection": "tools.custom_tools:http_call"}
TYPE_LABELS = {"sql_template": "Requête SQL paramétrée", "uc_function": "Fonction Unity Catalog",
               "http_connection": "Connecteur HTTP (connexion Unity Catalog)"}
TOOL_ID = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
PARAM_TYPES = ("string", "integer", "number", "boolean")
CATEGORIES = ["Données", "Analyse", "Qualité des données", "Visualisation", "Exploitation", "Gouvernance",
              "Documents", "Général"]
RESERVED = {"ctx", "spec", "self"}
MAX_PARAMS = 10
MAX_ROWS = 1000
OUTPUT_SCHEMA = {"type": "object", "properties": {"colonnes": {"type": "array"}, "lignes": {"type": "array"},
                                                  "nombre_lignes": {"type": "integer"}, "tronque": {"type": "boolean"}}}
HTTP_OUTPUT_SCHEMA = {"type": "object", "properties": {"statut_http": {"type": "integer"}, "reponse": {"type": "string"},
                                                       "json": {}, "tronque": {"type": "boolean"}}}
# 'd''Azur' : en Spark SQL, deux littéraux collés (dAzur), pas une apostrophe échappée
_DOUBLED_QUOTE = re.compile(r"[^\s'(,=]''[^\s')]")
_PLAN_ERROR = re.compile(r"error occurred during query planning|AnalysisException", re.I)


def is_custom(spec: ToolSpec) -> bool:
    return spec.executor in EXECUTORS.values()


def slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s or not s[0].isalpha():
        s = "outil_" + s
    return s[:40].rstrip("_")


def quote(name: str) -> str:
    return ".".join("`" + p.replace("`", "``") + "`" for p in name.split("."))


def _clamp_rows(v) -> int:
    try:
        return max(1, min(int(v), MAX_ROWS))
    except (TypeError, ValueError):
        return 100


def _json_obj(v, default):
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return default
        try:
            return json.loads(v)
        except ValueError:
            return {"__invalide__": v}
    return default if v is None else v


def normalize(p: dict) -> dict:
    """Proposition (copilote ou formulaire) -> brouillon homogène."""
    params = []
    for x in p.get("parameters") or []:
        if not isinstance(x, dict):
            continue
        enum = x.get("enum")
        params.append({"name": str(x.get("name") or "").strip(),
                       "type": str(x.get("type") or "string").strip().lower(),
                       "description": str(x.get("description") or "").strip(),
                       "required": bool(x.get("required", True)),
                       "enum": [str(v) for v in enum] if isinstance(enum, list) and enum else None,
                       "example": None if x.get("example") in (None, "") else str(x.get("example"))})
    if p.get("type") in EXECUTORS:          # type explicite prioritaire
        kind = p["type"]
    elif p.get("connection") and not p.get("sql"):
        kind = "http_connection"
    elif p.get("type") == "uc_function" or (p.get("function") and not p.get("sql")):
        kind = "uc_function"
    else:
        kind = "sql_template"
    http = kind == "http_connection"
    return {"tool_id": str(p.get("tool_id") or "").strip().lower() or slug(p.get("name", "")),
            "name": str(p.get("name") or "").strip()[:80],
            "description": str(p.get("description") or "").strip(),
            "category": str(p.get("category") or "Données").strip(),
            "type": kind,
            "sql": str(p.get("sql") or "").strip().rstrip(";").strip() if kind == "sql_template" else "",
            "function": str(p.get("function") or "").strip() if kind == "uc_function" else "",
            "function_kind": "table" if p.get("function_kind") == "table" else "scalar",
            "connection": str(p.get("connection") or "").strip() if http else "",
            "method": str(p.get("method") or "GET").strip().upper() if http else "",
            "path": str(p.get("path") or "/").strip() if http else "",
            "body": _json_obj(p.get("body"), None) if http else None,
            "query": _json_obj(p.get("query"), {}) if http else {},
            "headers": _json_obj(p.get("headers"), {}) if http else {},
            "parameters": params,
            "max_rows": _clamp_rows(p.get("max_rows", 100)),
            "hypotheses": [str(h) for h in p.get("hypotheses") or []]}


def coerce(value, kind: str):
    if value is None or value == "":
        return None
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
        if kind == "boolean":
            return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1", "oui", "vrai")
    except (TypeError, ValueError):
        return None
    return str(value)


def example_args(draft: dict) -> dict:
    out = {}
    for p in draft["parameters"]:
        v = coerce(p.get("example"), p["type"])
        if v is not None:
            out[p["name"]] = v
    return out


def fingerprint(draft: dict) -> str:
    keys = ("tool_id", "name", "description", "category", "type", "sql", "function", "function_kind",
            "connection", "method", "path", "body", "query", "headers", "parameters", "max_rows")
    return hashlib.sha256(json.dumps({k: draft.get(k) for k in keys}, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class Check:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def check(draft: dict, existing: dict[str, ToolSpec], owner: str, sql=None) -> Check:
    """Vérifie un brouillon. Avec `sql` (client de l'utilisateur), vérifie aussi l'accès et la compilation."""
    c = Check()
    tid = draft["tool_id"]
    if not TOOL_ID.match(tid):
        c.errors.append("Identifiant invalide : 3 à 40 caractères, minuscules, chiffres et _ (commence par une lettre).")
    cur = existing.get(tid)
    if cur is not None and (not is_custom(cur) or (cur.owner and cur.owner != owner)):
        c.errors.append(f"L'identifiant « {tid} » est déjà utilisé par un autre outil.")
    if len(draft["name"]) < 3:
        c.errors.append("Nom trop court.")
    if len(draft["description"]) < 30:
        c.errors.append("Description trop courte (30 caractères minimum) : c'est elle qui indique aux agents "
                        "quand utiliser l'outil.")
    if draft["type"] not in EXECUTORS:
        c.errors.append(f"Type d'outil non pris en charge : {draft['type']}.")
    names = [p["name"] for p in draft["parameters"]]
    if len(names) > MAX_PARAMS:
        c.errors.append(f"{MAX_PARAMS} paramètres au plus.")
    if len(set(names)) != len(names):
        c.errors.append("Paramètres en double.")
    for p in draft["parameters"]:
        if not PARAM_NAME.match(p["name"]) or p["name"] in RESERVED:
            c.errors.append(f"Nom de paramètre invalide : « {p['name']} » (minuscules, chiffres et _).")
        if p["type"] not in PARAM_TYPES:
            c.errors.append(f"Type invalide pour {p['name']} : {p['type']} (string, integer, number, boolean).")
        if not p["description"]:
            c.warnings.append(f"Paramètre {p['name']} sans description : l'agent devinera sa signification.")
        if p["required"] and coerce(p.get("example"), p["type"]) is None:
            c.warnings.append(f"Paramètre obligatoire {p['name']} sans valeur d'exemple : test impossible sans saisie.")

    if draft["type"] == "sql_template":
        try:
            stmt = check_read_only(draft["sql"])
        except SqlGuardError as e:
            c.errors.append(f"Requête refusée : {e}")
            return c
        if _DOUBLED_QUOTE.search(stmt):
            c.errors.append("Apostrophe doublée ('') dans une chaîne : en Spark SQL elle disparaît ('d''Azur' donne "
                            "dAzur). Écrivez \\' (d\\'Azur) ou utilisez des guillemets doubles (\"d'Azur\").")
        refs = extract_table_refs(stmt)
        partial = sorted(r for r in refs if r.count(".") != 2)
        if partial:
            c.errors.append("Utilisez des noms complets catalog.schema.table : " + ", ".join(partial))
        if not refs:
            c.warnings.append("La requête ne lit aucune table.")
        used = placeholders(stmt)
        if sorted(set(used) - set(names)):
            c.errors.append("Paramètres utilisés dans la requête mais non déclarés : "
                            + ", ".join(sorted(set(used) - set(names))))
        if sorted(set(names) - set(used)):
            c.errors.append("Paramètres déclarés mais absents de la requête : "
                            + ", ".join(sorted(set(names) - set(used))))
        if sql is not None and c.ok:
            for t in sorted(refs):
                try:
                    sql.query(f"DESCRIBE TABLE {quote(t)}", row_limit=1)
                except Exception as e:  # noqa: BLE001
                    c.errors.append(f"Table inaccessible : {t} ({str(e)[:200]})")
            if c.ok:
                params = {p["name"]: coerce(p.get("example"), p["type"]) for p in draft["parameters"]}
                try:
                    plan = sql.query("EXPLAIN " + stmt, params=params, row_limit=5)
                    text = " ".join(str(v) for r in plan.get("rows") or [] for v in r.values())
                    if _PLAN_ERROR.search(text):
                        c.errors.append("La requête ne compile pas : " + text[:400])
                except Exception as e:  # noqa: BLE001
                    c.errors.append(f"La requête ne compile pas : {str(e)[:400]}")
    elif draft["type"] == "http_connection":
        for k in ("body", "query", "headers"):
            v = draft.get(k)
            if isinstance(v, dict) and "__invalide__" in v:
                c.errors.append(f"{k} : JSON invalide.")
                return c
        if not isinstance(draft.get("query"), dict) or not isinstance(draft.get("headers"), dict):
            c.errors.append("Paramètres de requête et en-têtes : objets JSON attendus.")
            return c
        cfg = http_config(draft)
        try:
            check_http_config(cfg)
        except ToolError as e:
            c.errors.append(str(e))
            return c
        used = http_placeholders(cfg)
        if sorted(set(used) - set(names)):
            c.errors.append("Paramètres utilisés ({{nom}}) mais non déclarés : " + ", ".join(sorted(set(used) - set(names))))
        if sorted(set(names) - set(used)):
            c.errors.append("Paramètres déclarés mais absents du chemin, du corps ou de la requête : "
                            + ", ".join(sorted(set(names) - set(used))))
        if draft["method"] != "GET":
            c.warnings.append(f"Appel {draft['method']} : l'outil enverra ou modifiera des données. Il demandera une "
                              "validation humaine à chaque appel et seul un administrateur des outils peut le publier.")
        if sql is not None and c.ok:
            try:
                sql.query(f"DESCRIBE CONNECTION {quote(draft['connection'])}", row_limit=20)
            except Exception as e:  # noqa: BLE001
                c.errors.append(f"Connexion introuvable ou inaccessible : {draft['connection']} ({str(e)[:200]})")
            if c.ok:
                stmt, params = http_parts(cfg, example_args(draft))
                try:
                    plan = sql.query("EXPLAIN " + stmt, params=params, row_limit=5)
                    text = " ".join(str(v) for r in plan.get("rows") or [] for v in r.values())
                    if _PLAN_ERROR.search(text):
                        c.errors.append("L'appel ne compile pas : " + text[:400])
                except Exception as e:  # noqa: BLE001
                    c.errors.append(f"L'appel ne compile pas : {str(e)[:400]}")
    elif draft["type"] == "uc_function":
        if not UC_NAME.match(draft["function"]):
            c.errors.append("Fonction : nom complet catalog.schema.fonction attendu.")
        elif sql is not None:
            try:
                sql.query(f"DESCRIBE FUNCTION {quote(draft['function'])}", row_limit=50)
            except Exception as e:  # noqa: BLE001
                c.errors.append(f"Fonction inaccessible : {draft['function']} ({str(e)[:200]})")
    return c


def http_config(draft: dict) -> dict:
    return {"type": "http_connection", "connection": draft["connection"], "method": draft["method"],
            "path": draft["path"], "body": draft.get("body"), "query": draft.get("query") or {},
            "headers": draft.get("headers") or {}, "max_chars": 4000}


def build_spec(draft: dict, owner: str, status: str = "brouillon", version: str = "0") -> ToolSpec:
    props, required = {}, []
    for p in draft["parameters"]:
        d = {"type": p["type"], "description": p["description"] or p["name"]}
        if p.get("enum"):
            d["enum"] = p["enum"]
        props[p["name"]] = d
        if p["required"]:
            required.append(p["name"])
    names = [p["name"] for p in draft["parameters"]]
    if draft["type"] == "sql_template":
        stmt = check_read_only(draft["sql"])
        config = {"type": "sql_template", "sql": stmt, "tables": sorted(extract_table_refs(stmt)),
                  "max_rows": draft["max_rows"], "examples": example_args(draft)}
    elif draft["type"] == "http_connection":
        config = {**http_config(draft), "examples": example_args(draft)}
    else:
        config = {"type": "uc_function", "function": draft["function"], "kind": draft["function_kind"],
                  "params": names, "max_rows": draft["max_rows"], "examples": example_args(draft)}
    writes = draft["type"] == "http_connection" and draft["method"] != "GET"
    return ToolSpec(tool_id=draft["tool_id"], name=draft["name"], category=draft["category"],
                    description=draft["description"],
                    input_schema={"type": "object", "properties": props, "required": required},
                    output_schema=HTTP_OUTPUT_SCHEMA if draft["type"] == "http_connection" else OUTPUT_SCHEMA,
                    executor=EXECUTORS[draft["type"]], identity="utilisateur",
                    requires_confirmation=writes, read_only=not writes, status=status, version=version,
                    config=config, owner=owner)


def draft_from_spec(spec: ToolSpec) -> dict:
    cfg, props = spec.config or {}, spec.input_schema.get("properties") or {}
    req, ex = set(spec.input_schema.get("required") or []), cfg.get("examples") or {}
    return normalize({"tool_id": spec.tool_id, "name": spec.name, "description": spec.description,
                      "category": spec.category, "type": cfg.get("type"), "sql": cfg.get("sql", ""),
                      "function": cfg.get("function", ""), "function_kind": cfg.get("kind", "scalar"),
                      "connection": cfg.get("connection", ""), "method": cfg.get("method", ""),
                      "path": cfg.get("path", ""), "body": cfg.get("body"), "query": cfg.get("query"),
                      "headers": cfg.get("headers"),
                      "max_rows": cfg.get("max_rows", 100),
                      "parameters": [{"name": k, "type": v.get("type", "string"), "description": v.get("description", ""),
                                      "required": k in req, "enum": v.get("enum"), "example": ex.get(k)}
                                     for k, v in props.items()]})


def run_test(spec: ToolSpec, args: dict, ctx: ToolContext) -> dict:
    t0 = time.monotonic()
    clean = {k: v for k, v in args.items() if v is not None}
    try:
        out = ToolRegistry([spec]).run(spec, ctx, clean)
        if "statut_http" in out:
            return {"ok": True, "arguments": clean, "duree_ms": int((time.monotonic() - t0) * 1000),
                    "statut_http": out["statut_http"], "reponse": out["reponse"][:2000], "tronque": out["tronque"]}
        return {"ok": True, "arguments": clean, "duree_ms": int((time.monotonic() - t0) * 1000),
                "nombre_lignes": out.get("nombre_lignes"), "colonnes": out.get("colonnes"),
                "apercu": (out.get("lignes") or [])[:10], "tronque": out.get("tronque")}
    except ToolError as e:
        err = str(e)
    except Exception as e:  # noqa: BLE001
        err = f"Erreur technique ({type(e).__name__}) : {e}"
    return {"ok": False, "arguments": clean, "duree_ms": int((time.monotonic() - t0) * 1000), "erreur": err[:1000]}
