"""Contrôles applicatifs de HakimAI : ils ne dépendent pas du modèle et complètent ses consignes.

1. Présentation avant enregistrement : creer_outil / creer_agent ne sont soumis à la validation de l'utilisateur
   que si la proposition a été présentée en texte pendant le tour (identifiant, paramètres, cas testés).
2. Refus : la réponse après un refus est écrite par l'application (« Vous avez refusé… »), sans appel au modèle.
3. Fidélité : les nombres et les libellés à apostrophe de la réponse finale sont comparés aux résultats d'outils ;
   en cas d'écart, le modèle est relancé une fois, puis l'écart restant est signalé à l'utilisateur.
"""
import bisect
import json
import re
import unicodedata
from itertools import combinations

from backend.agent_runtime import ToolEvent, TurnResult, _parse_args, unanswered_calls

GUARD_PREFIX = "[Contrôle automatique DISCOVERY]"
CHECKED_WRITES = {"creer_outil", "creer_agent"}
MIN_PRESENTATION_CHARS = 120
FREE_INTEGERS = 10          # 0..10 sans décimale : numérotation, « 3 cas », « 2 paramètres »
MAX_SOURCE_VALUES = 200_000

# Nombre au format français ou anglais : 2 792 · 91,26 · 0.9126 · 12 % (pas les codes v2, DQ_010, 2013-01, 3e).
NUM = re.compile(r"(?<![\w.,/@#-])(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:,(\d+)|\.(\d+))?(?![\w/@-])(\s?%)?")
PLAIN = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
APOS = re.compile(r"\b(\w+)['’](\w+)\b")
CODE = re.compile(r"```.*?```|`[^`\n]*`|https?://\S+", re.S)


def _norm(s) -> str:
    return unicodedata.normalize("NFC", str(s or "")).replace("’", "'").lower()


def _turn_text(messages: list[dict]) -> str:
    """Texte des messages assistant depuis le dernier message de l'utilisateur."""
    out = []
    for m in reversed(messages):
        if m.get("role") == "user":
            break
        if m.get("role") == "assistant" and m.get("content"):
            out.append(m["content"])
    return "\n".join(reversed(out))


# -- 1. Présentation avant la fiche de validation ---------------------------------------------------------
def presentation_issue(tool_id: str, args: dict, messages: list[dict], drafts: dict | None) -> str | None:
    """Message d'erreur renvoyé au modèle si la proposition n'a pas été présentée, sinon None."""
    if tool_id not in CHECKED_WRITES:
        return None
    args = args or {}
    d = ((drafts or {}).get(args.get("brouillon_id")) or {}).get("draft") or {}
    raw = _turn_text(messages)
    text = _norm(raw)
    missing = []
    if len(raw.strip()) < MIN_PRESENTATION_CHARS:
        missing.append("un résumé de 3 à 5 lignes")
    if tool_id == "creer_outil":
        ident = [x for x in (d.get("tool_id"), d.get("name")) if x]
        if ident and not any(_norm(x) in text for x in ident):
            missing.append(f"l'identifiant de l'outil ({d.get('tool_id') or d.get('name')})")
        for p in d.get("parameters") or []:
            if p.get("name") and _norm(p["name"]) not in text:
                missing.append(f"le paramètre {p['name']}")
        if not re.search(r"\bcas\b|\btest", text):
            missing.append("chaque cas testé avec son nombre de lignes")
    else:
        name = args.get("nom") or d.get("name")
        handle = str(args.get("nom_appel") or d.get("handle") or "").lstrip("@")
        if (name or handle) and not ((name and _norm(name) in text) or (handle and _norm(handle) in text)):
            missing.append("le prénom et le @nom d'appel de l'agent")
        if "outil" not in text:
            missing.append("les outils de l'agent")
    if not missing:
        return None
    return (f"Fiche non présentée à l'utilisateur : présente d'abord la proposition dans ton message (manque : "
            f"{', '.join(missing)}), puis appelle de nouveau {tool_id} dans ce même message. Ce n'est pas un refus de "
            "l'utilisateur et rien n'a été écrit.")


# -- 2. Refus : réponse écrite par l'application ---------------------------------------------------------------
def refusal_text(label: str | None) -> str:
    what = f" : « {label} »" if label else ""
    return (f"Vous avez refusé l'enregistrement{what}. Rien n'a été écrit et aucune autre action n'a été lancée. "
            "Dites-moi ce que vous souhaitez changer.")


def refusal_result(messages: list[dict], call_id: str, label: str | None = None) -> TurnResult:
    """Clôt l'appel refusé (et les appels suivants du même message) sans rappeler le modèle."""
    msgs, events = list(messages), []
    start = len(msgs)
    for c in unanswered_calls(msgs):
        refused = c["id"] == call_id
        err = ("Exécution refusée par l'utilisateur." if refused
               else "Non exécuté : l'utilisateur a refusé une autre action de ce message.")
        ev = ToolEvent(c["id"], c["function"]["name"], _parse_args(c), "refuse" if refused else "erreur", error=err)
        msgs.append({"role": "tool", "tool_call_id": c["id"],
                     "content": json.dumps({"status": ev.status, "error": err}, ensure_ascii=False)})
        events.append(ev)
    text = refusal_text(label)
    msgs.append({"role": "assistant", "content": text})
    return TurnResult(messages=msgs, new_messages=msgs[start:], events=events, final_text=text)


# -- 3. Fidélité des nombres et des libellés ---------------------------------------------------------------
def _text_numbers(text: str) -> list[tuple[str, float, int, bool]]:
    """(texte, valeur, nombre de décimales, pourcentage) pour chaque nombre d'un texte rédigé."""
    out = []
    for m in NUM.finditer(CODE.sub(" ", text or "")):
        ent = re.sub(r"[ \u00a0\u202f]", "", m.group(1))
        dec = m.group(2) or m.group(3) or ""
        val = float(f"{ent}.{dec}" if dec else ent)
        out.append((m.group(0).strip(), val, len(dec), bool(m.group(4))))
    return out


def _as_float(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def _collect(obj, nums: list, texts: list) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            texts.append(str(k))
            _collect(v, nums, texts)
    elif isinstance(obj, list):
        nums.append(float(len(obj)))
        sums: dict = {}
        for x in obj:
            _collect(x, nums, texts)
            if isinstance(x, dict):
                for k, v in x.items():
                    f = _as_float(v)
                    if f is not None:
                        sums[k] = sums.get(k, 0.0) + f
        nums.extend(sums.values())
    elif isinstance(obj, str):
        texts.append(obj)
        nums.extend(float(x) for x in PLAIN.findall(obj))
        nums.extend(v for _, v, _, _ in _text_numbers(obj))
    else:
        f = _as_float(obj)
        if f is not None:
            nums.append(f)


def _sources(messages: list[dict]) -> tuple[list[float], str]:
    """Valeurs connues : résultats d'outils, messages de l'utilisateur et consignes (hors contrôles automatiques)."""
    nums, texts = [], []
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role not in ("tool", "user", "system") or not isinstance(content, str):
            continue
        if role == "user" and content.startswith(GUARD_PREFIX):
            continue
        if role == "tool":
            try:
                _collect(json.loads(content), nums, texts)
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        _collect(content, nums, texts)
    vals = sorted({abs(x) for x in nums if x == x})[:MAX_SOURCE_VALUES]
    return vals, "\n".join(texts)


def _near(vals: list[float], x: float, tol: float) -> bool:
    i = bisect.bisect_left(vals, x - tol)
    return i < len(vals) and vals[i] <= x + tol


def _known(v: float, dec: int, pct: bool, vals: list[float]) -> bool:
    tol = 0.5 * 10 ** -dec + 1e-9
    if _near(vals, v, tol):
        return True
    return (pct or dec > 0) and _near(vals, v / 100, tol / 100)   # 91,26 % <-> 0,9126


def _derived(v: float, dec: int, known: list[float]) -> bool:
    """Somme, écart ou part (en %) de deux nombres déjà vérifiés de la réponse, ou total de tous."""
    tol = 0.5 * 10 ** -dec + 1e-9
    if len(known) > 1 and abs(sum(known) - v) <= tol:
        return True
    for a, b in combinations(known[:60], 2):
        if abs(a + b - v) <= tol or abs(abs(a - b) - v) <= tol:
            return True
        for x, y in ((a, b), (b, a)):
            if y and (abs(x / y * 100 - v) <= tol or abs(x / y - v) <= tol):
                return True
    return False


def fidelity_issues(messages: list[dict]) -> list[dict]:
    """Écarts entre la dernière réponse de l'assistant et les données renvoyées par les outils."""
    last = messages[-1] if messages else {}
    if last.get("role") != "assistant" or not last.get("content") or last.get("tool_calls"):
        return []
    text = last["content"]
    vals, src_text = _sources(messages[:-1])
    issues, known, unknown = [], [], []
    for raw, v, dec, pct in _text_numbers(text):
        if dec == 0 and not pct and v <= FREE_INTEGERS:
            continue
        (known if _known(v, dec, pct, vals) else unknown).append((raw, v, dec))
    known_vals = [v for _, v, _ in known]
    seen = set()
    for raw, v, dec in unknown:
        if raw not in seen and not _derived(v, dec, known_vals):
            seen.add(raw)
            issues.append({"type": "nombre", "valeur": raw,
                           "detail": f"le nombre « {raw} » n'apparaît dans aucun résultat d'outil"})
    src_norm = _norm(src_text)
    for m in APOS.finditer(CODE.sub(" ", text)):
        full, joined = _norm(m.group(0)), m.group(1) + m.group(2)
        hit = re.search(rf"(?<!\w){re.escape(joined)}(?!\w)", src_text, re.I)
        if hit and full not in src_norm and full not in seen:
            seen.add(full)
            issues.append({"type": "libelle", "valeur": m.group(0),
                           "detail": f"« {m.group(0)} » est écrit « {hit.group(0)} » dans les données renvoyées"})
    return issues


def correction_message(issues: list[dict]) -> dict:
    lines = "\n".join(f"- {i['detail']}" for i in issues)
    return {"role": "user", "content": (
        f"{GUARD_PREFIX} Ta réponse contient des éléments absents des résultats d'outils :\n{lines}\n"
        "Réécris ta réponse complète pour l'utilisateur. N'utilise que des nombres renvoyés par les outils : si un "
        "chiffre manque (un nombre de départements, de lignes...), appelle l'outil qui le calcule (COUNT, SUM) ou "
        "retire-le. Recopie chaque libellé exactement comme il est renvoyé et, s'il paraît anormal, signale "
        "l'anomalie au lieu de le corriger. Ne mentionne pas ce contrôle.")}


def merge(first: TurnResult, second: TurnResult) -> TurnResult:
    """Tour corrigé : la réponse finale écartée et le message de contrôle ne sont ni affichés ni journalisés."""
    usage = dict(first.usage)
    for k, v in second.usage.items():
        usage[k] = usage.get(k, 0) + v
    return TurnResult(messages=second.messages, new_messages=first.new_messages[:-1] + second.new_messages,
                      events=first.events + second.events, final_text=second.final_text, pending=second.pending,
                      latency_ms=first.latency_ms + second.latency_ms, usage=usage)


def verify_turn(rt, cfg, res: TurnResult) -> tuple[TurnResult, list[dict]]:
    """Contrôle la réponse finale ; relance le modèle une fois si besoin. Renvoie (tour, écarts restants)."""
    if res.pending or not res.final_text:
        return res, []
    issues = fidelity_issues(res.messages)
    if not issues:
        return res, []
    try:
        second = rt.resume(cfg, res.messages[:-1] + [correction_message(issues)], {})
    except Exception:  # noqa: BLE001 - la réponse d'origine reste affichée avec l'avertissement
        return res, issues
    merged = merge(res, second)
    return merged, ([] if merged.pending else fidelity_issues(merged.messages))


def warning_text(issues: list[dict]) -> str:
    return ("Contrôle automatique : " + " ; ".join(i["detail"] for i in issues)
            + ". Vérifiez ces éléments avant de les réutiliser.")
