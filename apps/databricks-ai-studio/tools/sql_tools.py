"""Outil execute_sql : lecture seule, nombre de lignes borné, tables limitées aux connaissances de l'agent."""
from __future__ import annotations

from backend.sql_guard import SqlGuardError, check_read_only, extract_table_refs
from backend.tool_registry import ToolContext, ToolError, ToolPermissionError


def execute_sql(ctx: ToolContext, query: str, limit: int = 100) -> dict:
    try:
        statement = check_read_only(query)
    except SqlGuardError as e:
        raise ToolPermissionError(f"Requête refusée : {e}") from e
    if ctx.allowed_tables:
        allowed = {t.lower() for t in ctx.allowed_tables}
        refs = extract_table_refs(statement)
        partial = sorted(r for r in refs if r.count(".") != 2)
        if partial:
            raise ToolPermissionError("Utilisez des noms complets catalog.schema.table : " + ", ".join(partial))
        outside = sorted(r for r in refs if r not in allowed)
        if outside:
            raise ToolPermissionError("Tables hors des connaissances de l'agent : " + ", ".join(outside))
    n = max(1, min(int(limit), ctx.max_rows))
    r = ctx.sql.query(statement, row_limit=n)
    return {"colonnes": r["columns"], "lignes": r["rows"], "nombre_lignes": len(r["rows"]),
            "tronque": r["truncated"], "limite": n}
