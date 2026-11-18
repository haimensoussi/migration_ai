"""Garde-fous de l'outil SQL de l'agent : une seule instruction SELECT, sur un perimetre de schemas autorise.

Defense en profondeur : le controle d'acces reel reste celui d'Unity Catalog, applique parce que
la requete s'execute avec le jeton de l'utilisateur.
"""
from __future__ import annotations

import re

ALLOWED_FIRST = {"SELECT", "WITH"}
FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT",
    "REVOKE", "OPTIMIZE", "VACUUM", "REFRESH", "RESTORE", "MSCK", "CALL", "EXECUTE",
    "IMMEDIATE", "COPY", "CACHE", "UNCACHE", "SECRET", "READ_FILES", "HTTP_REQUEST", "AI_QUERY",
}


class SqlGuardError(ValueError):
    pass


def _strip(sql: str) -> str:
    """Retire commentaires, litteraux et identifiants entre guillemets (remplaces par des jetons neutres)."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                raise SqlGuardError("Commentaire non ferme.")
            i = j + 2
            out.append(" ")
        elif c in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == "\\" and c != "`":
                    j += 2
                    continue
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise SqlGuardError("Litteral ou identifiant non ferme.")
            out.append(" `id` " if c == "`" else " 'lit' ")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def check_read_only(sql: str) -> str:
    """Valide la requete (SELECT/WITH unique) et renvoie sa forme sans point-virgule final."""
    if not sql or not sql.strip():
        raise SqlGuardError("Requete vide.")
    cleaned = _strip(sql).strip()
    while cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    if ";" in cleaned:
        raise SqlGuardError("Une seule instruction SQL est autorisee.")
    m = re.match(r"\(*\s*([A-Za-z]+)", cleaned)
    first = m.group(1).upper() if m else ""
    if first not in ALLOWED_FIRST:
        raise SqlGuardError(f"Instruction {first or '?'} non autorisee : lecture seule (SELECT ou WITH).")
    words = {wd.upper() for wd in re.findall(r"\b[A-Za-z_]+\b", cleaned)}
    bad = sorted(words & FORBIDDEN)
    if bad:
        raise SqlGuardError(f"Mot-cle interdit en lecture seule : {', '.join(bad)}.")
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
    """Noms de tables cites apres FROM / JOIN (hors CTE et sous-requetes)."""
    no_comments = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    ctes = {_norm(m) for m in _CTE.findall(no_comments)}
    refs = set()
    for m in _REF.finditer(no_comments):
        name = _norm(m.group(1))
        if name and name not in ctes and not name.startswith("("):
            refs.add(name)
    return refs


def check_scope(sql: str, allowed_schemas: set[str]) -> set[str]:
    """Chaque table citee doit etre qualifiee catalogue.schema.table et appartenir a un schema autorise."""
    allowed = {s.lower() for s in allowed_schemas}
    refs = extract_table_refs(sql)
    if not refs:
        raise SqlGuardError("Aucune table identifiee : citez les tables avec leur nom complet catalogue.schema.table.")
    hors = sorted(r for r in refs if r.count(".") != 2 or r.rsplit(".", 1)[0] not in allowed)
    if hors:
        raise SqlGuardError("Tables hors perimetre ou non qualifiees : " + ", ".join(hors)
                            + ". Schemas autorises : " + ", ".join(sorted(allowed)) + ".")
    return refs
