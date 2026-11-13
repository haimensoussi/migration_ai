"""Garde-fou de l'outil execute_sql : une seule instruction, en lecture seule.

C'est une défense en profondeur : le contrôle d'accès réel reste celui de Unity Catalog,
appliqué parce que la requête s'exécute avec le jeton de l'utilisateur.
"""
from __future__ import annotations

import re

ALLOWED_FIRST = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "VALUES"}
FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT",
    "REVOKE", "OPTIMIZE", "VACUUM", "REFRESH", "RESTORE", "MSCK", "CALL", "EXECUTE",
    "IMMEDIATE", "COPY", "CACHE", "UNCACHE", "SECRET", "READ_FILES", "HTTP_REQUEST",
}


class SqlGuardError(ValueError):
    pass


def _strip(sql: str) -> str:
    """Retire commentaires, littéraux et identifiants entre guillemets (remplacés par des jetons neutres)."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                raise SqlGuardError("Commentaire non fermé.")
            i = j + 2
            out.append(" ")
        elif c in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == "\\" and c != "`":
                    j += 2
                    continue
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:  # guillemet doublé
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise SqlGuardError("Littéral ou identifiant non fermé.")
            out.append(" `id` " if c == "`" else " 'lit' ")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def check_read_only(sql: str) -> str:
    """Valide la requête et renvoie sa forme normalisée (sans point-virgule final)."""
    if not sql or not sql.strip():
        raise SqlGuardError("Requête vide.")
    cleaned = _strip(sql).strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    if ";" in cleaned:
        raise SqlGuardError("Une seule instruction SQL est autorisée.")
    m = re.match(r"\(*\s*([A-Za-z]+)", cleaned)
    first = m.group(1).upper() if m else ""
    if first not in ALLOWED_FIRST:
        raise SqlGuardError(f"Instruction « {first or '?'} » non autorisée : lecture seule (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN).")
    words = {wd.upper() for wd in re.findall(r"\b[A-Za-z_]+\b", cleaned)}
    bad = sorted(words & FORBIDDEN)
    if bad:
        raise SqlGuardError(f"Mot-clé interdit en lecture seule : {', '.join(bad)}.")
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


_NAME = r"(?:`[^`]+`|[A-Za-z0-9_\-]+)"
_REF = re.compile(rf"\b(?:FROM|JOIN)\s+({_NAME}(?:\s*\.\s*{_NAME}){{0,2}})", re.I)
_CTE = re.compile(rf"(?:\bWITH\b|,)\s*({_NAME})\s+AS\s*\(", re.I)


def _norm(name: str) -> str:
    return ".".join(p.strip().strip("`") for p in name.split(".")).lower()


def extract_table_refs(sql: str) -> set[str]:
    """Noms de tables cités après FROM / JOIN (hors CTE et sous-requêtes)."""
    no_comments = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    ctes = {_norm(m) for m in _CTE.findall(no_comments)}
    refs = set()
    for m in _REF.finditer(no_comments):
        name = _norm(m.group(1))
        if name and name not in ctes and not name.startswith("("):
            refs.add(name)
    return refs
