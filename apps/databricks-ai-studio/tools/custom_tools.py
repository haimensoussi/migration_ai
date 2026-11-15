"""Exécuteurs génériques des outils créés dans DISCOVERY.

Un outil créé n'apporte jamais de code : seulement une configuration (requête SQL paramétrée ou nom de fonction
Unity Catalog), exécutée ici avec les droits de l'utilisateur. Les valeurs fournies par l'agent sont toujours
transmises comme paramètres liés, jamais insérées dans le texte SQL.
"""
from __future__ import annotations

import re

from backend.sql_guard import SqlGuardError, check_read_only, extract_table_refs
from backend.tool_registry import ToolContext, ToolError, ToolPermissionError, ToolSpec

PARAM_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
UC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_MARKER = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")
_NOISE = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`[^`]*`|--[^\n]*|/\*.*?\*/""", re.S)


def placeholders(sql: str) -> list[str]:
    """Paramètres nommés (:nom) de la requête, hors chaînes, identifiants entre `...`, commentaires et casts ::."""
    return list(dict.fromkeys(_MARKER.findall(_NOISE.sub(" ", sql or ""))))


def _result(r: dict, n: int) -> dict:
    return {"colonnes": r["columns"], "lignes": r["rows"], "nombre_lignes": len(r["rows"]),
            "tronque": r["truncated"], "limite": n}


def _limit(ctx: ToolContext, cfg: dict) -> int:
    try:
        n = int(cfg.get("max_rows") or 100)
    except (TypeError, ValueError):
        n = 100
    return max(1, min(n, ctx.max_rows))


def checked_template(cfg: dict) -> str:
    """Requête de l'outil : lecture seule, une instruction, tables déclarées et en nom complet."""
    try:
        stmt = check_read_only(cfg.get("sql") or "")
    except SqlGuardError as e:
        raise ToolPermissionError(f"Requête de l'outil refusée : {e}") from e
    refs = extract_table_refs(stmt)
    partial = sorted(r for r in refs if r.count(".") != 2)
    if partial:
        raise ToolPermissionError("Noms complets catalog.schema.table requis : " + ", ".join(partial))
    declared = {t.lower() for t in cfg.get("tables") or []}
    extra = sorted(r for r in refs if r not in declared)
    if extra:
        raise ToolPermissionError("Tables non déclarées dans l'outil : " + ", ".join(extra))
    return stmt


def sql_template(ctx: ToolContext, spec: ToolSpec, **args) -> dict:
    cfg = spec.config or {}
    stmt = checked_template(cfg)
    names = placeholders(stmt)
    declared = set((spec.input_schema.get("properties") or {}).keys())
    if set(names) != declared:
        raise ToolError("Paramètres de la requête et de l'outil incohérents : outil à corriger.")
    n = _limit(ctx, cfg)
    return _result(ctx.sql.query(stmt, params={p: args.get(p) for p in names}, row_limit=n), n)


sql_template.needs_spec = True


def uc_call(cfg: dict) -> str:
    fn = str(cfg.get("function") or "")
    if not UC_NAME.match(fn):
        raise ToolPermissionError("Nom de fonction invalide : catalog.schema.fonction attendu.")
    params = list(cfg.get("params") or [])
    if any(not PARAM_NAME.match(str(p)) for p in params):
        raise ToolPermissionError("Nom de paramètre invalide dans la configuration de l'outil.")
    call = "{}({})".format(".".join(f"`{p}`" for p in fn.split(".")), ", ".join(f":{p}" for p in params))
    return f"SELECT * FROM {call}" if cfg.get("kind") == "table" else f"SELECT {call} AS resultat"


def uc_function(ctx: ToolContext, spec: ToolSpec, **args) -> dict:
    cfg = spec.config or {}
    stmt = uc_call(cfg)
    n = _limit(ctx, cfg)
    return _result(ctx.sql.query(stmt, params={p: args.get(p) for p in cfg.get("params") or []}, row_limit=n), n)


uc_function.needs_spec = True


# --- Connecteur HTTP (connexion Unity Catalog + http_request, exécuté sur l'entrepôt SQL) -------------------------
import json as _json
from urllib.parse import quote as _quote

CONN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
FORBIDDEN_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "host"}
TEMPLATE = re.compile(r"\{\{([a-z][a-z0-9_]{0,39})\}\}")
MAX_CHARS = 20000


def http_placeholders(cfg: dict) -> list[str]:
    """Paramètres {{nom}} utilisés dans le chemin, le corps et les paramètres de requête."""
    text = (cfg.get("path") or "") + _json.dumps(cfg.get("body")) + _json.dumps(cfg.get("query") or {})
    return list(dict.fromkeys(TEMPLATE.findall(text)))


def _render(obj, args: dict):
    """Remplace {{nom}} dans un modèle JSON déjà analysé (jamais par concaténation de texte JSON)."""
    if isinstance(obj, str):
        whole = TEMPLATE.fullmatch(obj)
        if whole:
            return args.get(whole.group(1))          # valeur typée (nombre, booléen, texte, null)
        return TEMPLATE.sub(lambda m: "" if args.get(m.group(1)) is None else str(args.get(m.group(1))), obj)
    if isinstance(obj, list):
        return [_render(x, args) for x in obj]
    if isinstance(obj, dict):
        return {k: _render(v, args) for k, v in obj.items()}
    return obj


def check_http_config(cfg: dict) -> None:
    conn, method, path = str(cfg.get("connection") or ""), str(cfg.get("method") or ""), str(cfg.get("path") or "")
    if not CONN_NAME.match(conn):
        raise ToolPermissionError("Nom de connexion invalide.")
    if conn.lower().startswith("system_"):
        raise ToolPermissionError("Les connexions système de Databricks ne peuvent pas être utilisées.")
    if method not in METHODS:
        raise ToolPermissionError(f"Méthode HTTP non autorisée : {method}.")
    if not path.startswith("/") or "://" in path or "/../" in path + "/" or "\\" in path:
        raise ToolPermissionError("Chemin invalide : relatif à la connexion, commençant par /.")
    for k, v in (cfg.get("headers") or {}).items():
        if not HEADER_NAME.match(str(k)) or str(k).lower() in FORBIDDEN_HEADERS or any(c in str(v) for c in "\r\n"):
            raise ToolPermissionError(f"En-tête interdit : {k} (les identifiants restent dans la connexion).")
    if method == "GET" and cfg.get("body") not in (None, {}, ""):
        raise ToolPermissionError("Une requête GET n'a pas de corps.")


def http_parts(cfg: dict, args: dict) -> tuple[str, dict]:
    check_http_config(cfg)
    path = TEMPLATE.sub(lambda m: _quote("" if args.get(m.group(1)) is None else str(args.get(m.group(1))), safe=""),
                        cfg["path"])
    body = None if cfg["method"] == "GET" or cfg.get("body") is None else _render(cfg["body"], args)
    query = {k: str(v) for k, v in (_render(cfg.get("query") or {}, args) or {}).items() if v not in (None, "")}
    stmt = ("SELECT r.status_code AS status_code, r.text AS text FROM (SELECT http_request("
            f"conn => '{cfg['connection']}', method => '{cfg['method']}', path => :path, json => :json, "
            "headers => from_json(:headers, 'map<string,string>'), "
            "params => from_json(:params, 'map<string,string>')) AS r)")
    params = {"path": path, "json": None if body is None else _json.dumps(body, ensure_ascii=False),
              "headers": _json.dumps({str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}),
              "params": _json.dumps(query, ensure_ascii=False)}
    return stmt, params


def http_call(ctx: ToolContext, spec: ToolSpec, **args) -> dict:
    cfg = spec.config or {}
    declared = set((spec.input_schema.get("properties") or {}).keys())
    if set(http_placeholders(cfg)) != declared:
        raise ToolError("Paramètres du connecteur et de l'outil incohérents : outil à corriger.")
    stmt, params = http_parts(cfg, args)
    rows = ctx.sql.query(stmt, params=params, row_limit=1)["rows"]
    if not rows:
        raise ToolError("Erreur technique : aucune réponse du connecteur.")
    code = int(rows[0].get("status_code") or 0)
    text = str(rows[0].get("text") or "")
    limit = max(200, min(int(cfg.get("max_chars") or 4000), MAX_CHARS))
    if code >= 400 or code == 0:
        raise ToolError(f"Erreur technique : le service a répondu HTTP {code} : {text[:300]}")
    out = {"statut_http": code, "reponse": text[:limit], "tronque": len(text) > limit}
    try:
        out["json"] = _json.loads(text) if len(text) <= limit else None
    except ValueError:
        pass
    return out


http_call.needs_spec = True
