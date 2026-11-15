"""Reconnaissance des mentions @agent dans un message utilisateur (sans dépendance Streamlit)."""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

MAX_MENTIONS = 3


def _norm_char(ch: str) -> str:
    m = "".join(c for c in unicodedata.normalize("NFKD", ch.lower()) if not unicodedata.combining(c))
    return m if len(m) == 1 else ch.lower()


def norm(text: str) -> str:
    """Minuscules sans accents, longueur conservée (positions alignées sur le texte d'origine)."""
    return "".join(_norm_char(c) for c in text)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")


@dataclass
class MentionResult:
    agents: list[dict] = field(default_factory=list)       # agents mentionnés, dans l'ordre, sans doublon
    text: str = ""                                          # message sans les mentions
    unknown: list[tuple[str, list[str]]] = field(default_factory=list)   # (mention, suggestions)
    truncated: bool = False                                 # plus de MAX_MENTIONS mentions


def _keys(agents: list[dict]) -> list[tuple[str, dict]]:
    keys, firsts = [], {}
    for a in agents:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        for k in {norm(name), slug(name)}:
            keys.append((k, a))
        extra = [a.get("handle")] + list(a.get("aliases") or [])
        for k in {x for e in extra if e for x in (norm(str(e)), slug(str(e)))}:
            keys.append((k, a))
        if a.get("kind") != "team":
            firsts.setdefault(slug(name).split("-")[0], []).append(a)
    for first, lst in firsts.items():           # alias court (@sentinelle) seulement s'il est non ambigu
        if len(lst) == 1 and len(first) >= 3:
            keys.append((first, lst[0]))
    return sorted(keys, key=lambda kv: -len(kv[0]))


def parse_mentions(text: str, agents: list[dict], max_mentions: int = MAX_MENTIONS) -> MentionResult:
    res = MentionResult(text=text or "")
    if not text or "@" not in text:
        return res
    keys, n = _keys(agents), norm(text)
    names = {norm(a["name"]): a["name"] for a in agents if a.get("name")}
    names.update({slug(a["name"]): a["name"] for a in agents if a.get("name")})
    names.update({a["handle"]: a["name"] for a in agents if a.get("handle") and a.get("name")})
    spans, i = [], 0
    while (j := text.find("@", i)) >= 0:
        if j > 0 and text[j - 1].isalnum():          # adresse e-mail : pas une mention
            i = j + 1
            continue
        rest = n[j + 1:]
        hit = next(((k, a) for k, a in keys
                    if rest.startswith(k) and (len(rest) == len(k) or not rest[len(k)].isalnum())), None)
        if hit:
            k, a = hit
            if all(x["agent_id"] != a["agent_id"] for x in res.agents):
                res.agents.append(a)
            spans.append((j, j + 1 + len(k)))
            i = j + 1 + len(k)
            continue
        tok = re.match(r"[\w\-]+", text[j + 1:])
        if tok:
            sugg = difflib.get_close_matches(norm(tok.group(0)), list(names), n=3, cutoff=0.45)
            res.unknown.append((tok.group(0), list(dict.fromkeys(names[s] for s in sugg))))
        i = j + 1
    out, last = [], 0
    for a, b in spans:
        out.append(text[last:a])
        last = b
    out.append(text[last:])
    cleaned = re.sub(r"\s+", " ", "".join(out))
    cleaned = re.sub(r"\s+([,;:])", r"\1", cleaned)          # « Bonjour , » -> « Bonjour, »
    cleaned = re.sub(r"([,;:])(?=[,;:]|\s*$)", "", cleaned)   # ponctuation orpheline
    res.text = re.sub(r"^[\s,;:]+", "", cleaned).strip()
    if len(res.agents) > max_mentions:
        res.agents, res.truncated = res.agents[:max_mentions], True
    return res
