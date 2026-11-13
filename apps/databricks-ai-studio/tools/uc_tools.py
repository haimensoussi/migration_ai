"""Outils Unity Catalog : exécutés en SQL avec l'identité de l'utilisateur (droits UC appliqués)."""
from __future__ import annotations

from backend.tool_registry import ToolContext
from tools.common import check_allowed, quote, split_name


def list_tables(ctx: ToolContext, catalog: str, schema: str) -> dict:
    cat, sch = split_name(f"{catalog}.{schema}", 2)
    r = ctx.sql.query(f"SHOW TABLES IN {quote([cat, sch])}", row_limit=500)
    allowed = {t.lower() for t in ctx.allowed_tables}
    tables = []
    for row in r["rows"]:
        full = f"{cat}.{sch}.{row['tableName']}"
        if str(row.get("isTemporary")).lower() == "true":
            continue
        tables.append({"table": full, "autorisee_pour_agent": (not allowed) or full.lower() in allowed})
    return {"schema": f"{cat}.{sch}", "nombre": len(tables), "tables": tables, "tronque": r["truncated"]}


def describe_table(ctx: ToolContext, table: str) -> dict:
    items = split_name(table, 3)
    full = ".".join(items)
    check_allowed(ctx, full)
    r = ctx.sql.query(f"DESCRIBE TABLE EXTENDED {quote(items)}", row_limit=1000)
    columns, details, section = [], {}, "columns"
    for row in r["rows"]:
        name, dtype, comment = row.get("col_name") or "", row.get("data_type"), row.get("comment")
        if section == "columns":
            if not name.strip() or name.startswith("#"):
                section = "details" if "Detailed" in name else "skip"
                continue
            columns.append({"name": name, "type": dtype, "comment": comment})
        elif name.startswith("# Detailed"):
            section = "details"
        elif section == "details" and name in ("Catalog", "Database", "Table", "Type", "Owner", "Comment",
                                               "Created Time", "Last Access", "Provider", "Location"):
            details[name] = dtype
        elif section == "skip" and name.startswith("# Detailed"):
            section = "details"
    return {"table": full, "nombre_colonnes": len(columns), "colonnes": columns, "details": details}


def get_table_profile(ctx: ToolContext, table: str, max_columns: int = 30) -> dict:
    desc = describe_table(ctx, table)
    cols = desc["colonnes"][: max(1, min(int(max_columns), 60))]
    exprs = ["count(*) AS n_lignes"]
    for i, c in enumerate(cols):
        q = "`" + c["name"].replace("`", "``") + "`"
        exprs.append(f"count({q}) AS nn_{i}")
        exprs.append(f"approx_count_distinct({q}) AS d_{i}")
    r = ctx.sql.query(f"SELECT {', '.join(exprs)} FROM {quote(split_name(table, 3))}")
    row = r["rows"][0]
    n = int(row["n_lignes"] or 0)
    profil = []
    for i, c in enumerate(cols):
        nn = int(row[f"nn_{i}"] or 0)
        profil.append({"colonne": c["name"], "type": c["type"], "non_nuls": nn,
                       "taux_nuls": round(1 - nn / n, 4) if n else None,
                       "distincts_approx": int(row[f"d_{i}"] or 0)})
    return {"table": desc["table"], "n_lignes": n, "colonnes_profilees": len(cols),
            "colonnes_totales": desc["nombre_colonnes"], "profil": profil,
            "note": "Constats statistiques : ils ne constituent pas des règles métier validées."}
