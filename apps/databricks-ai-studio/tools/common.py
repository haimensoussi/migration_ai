from __future__ import annotations

import re

from backend.tool_registry import ToolContext, ToolError, ToolPermissionError

_IDENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")


def split_name(full: str, parts: int) -> list[str]:
    items = [p.strip().strip("`") for p in (full or "").split(".")]
    if len(items) != parts or not all(_IDENT.match(p) for p in items):
        attendu = "catalog.schema.table" if parts == 3 else "catalog.schema"
        raise ToolError(f"Nom invalide « {full} » : format attendu {attendu}.")
    return items


def quote(items: list[str]) -> str:
    return ".".join(f"`{p}`" for p in items)


def check_allowed(ctx: ToolContext, full: str) -> None:
    """Restreint aux tables de connaissance de l'agent lorsqu'une liste est définie."""
    if ctx.allowed_tables and full.lower() not in {t.lower() for t in ctx.allowed_tables}:
        raise ToolPermissionError(f"La table {full} ne fait pas partie des connaissances autorisées pour cet agent.")
