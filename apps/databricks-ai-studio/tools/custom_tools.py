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
