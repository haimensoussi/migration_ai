"""HakimAI Voix (prototype) : conversation vocale temps réel avec le modèle OpenAI gpt-realtime.

Principes :
- la clé API permanente reste côté serveur (secret Databricks -> variable OPENAI_API_KEY) ; le navigateur ne reçoit
  qu'une clé éphémère (quelques minutes) pour ouvrir la connexion WebRTC directement avec OpenAI ;
- le modèle ne fait que DEMANDER un outil ; l'outil est exécuté ici, avec les droits de l'utilisateur, et seulement
  s'il figure dans la liste blanche en lecture seule (VOICE_TOOLS) ;
- chaque appel d'outil est journalisé dans tool_calls (agent « hakimai »), comme sur la page HakimAI ;
- durée de session et nombre d'appels d'outils plafonnés (coût).

La voix et les réponses transitent par OpenAI (hors Databricks / Unity Gateway) : nécessite l'accord sécurité.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

from backend.agent_runtime import ToolEvent
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec

CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
CALLS_URL = "https://api.openai.com/v1/realtime/calls"
VOICE_TOOLS = ("aide_plateforme", "lister_agents", "activite")   # lecture seule, validé pour le prototype
MAX_OUTPUT_CHARS = 4000

INSTRUCTIONS = (
    "Tu es HakimAI, l'architecte de la plateforme DISCOVERY de SNCF Réseau, en conversation vocale. "
    "Réponds en français, phrases courtes et naturelles, sans listes ni mise en forme. "
    "Tu es en LECTURE SEULE : tu peux expliquer la plateforme, lister les agents et décrire leur activité "
    "avec les outils fournis. N'invente jamais d'agent, de chiffre ou de résultat : si un outil ne renvoie rien, "
    "dis-le. Pour créer ou modifier un agent, un outil ou une équipe, invite l'utilisateur à utiliser la page "
    "HakimAI écrite, où chaque action est validée. Ne lis jamais à voix haute d'identifiants techniques longs."
)


class VoiceError(RuntimeError):
    """Erreur destinée à l'utilisateur (configuration, réseau, OpenAI)."""


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, default))))
    except ValueError:
        return default


def settings() -> dict:
    return {
        "enabled": os.environ.get("AI_STUDIO_VOICE_ENABLED", "false").strip().lower() in ("1", "true", "oui", "on"),
        "model": os.environ.get("AI_STUDIO_VOICE_MODEL", "gpt-realtime").strip() or "gpt-realtime",
        "voice": os.environ.get("AI_STUDIO_VOICE_VOICE", "marin").strip() or "marin",
        "max_seconds": _int_env("AI_STUDIO_VOICE_MAX_SECONDS", 300, 30, 1800),
        "max_tool_calls": _int_env("AI_STUDIO_VOICE_MAX_TOOL_CALLS", 20, 1, 100),
        "has_key": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
    }


def status() -> tuple[bool, str]:
    """(disponible, message) sans jamais exposer la clé."""
    s = settings()
    if not s["enabled"]:
        return False, "HakimAI Voix est désactivé (AI_STUDIO_VOICE_ENABLED)."
    if not s["has_key"]:
        return False, "Clé OpenAI absente : ressource secret « openai-key » non configurée sur l'App."
    return True, ""


def voice_specs(all_specs: list[ToolSpec]) -> list[ToolSpec]:
    """Outils de la liste blanche, et seulement s'ils sont en lecture seule et sans confirmation."""
    return [t for t in all_specs if t.tool_id in VOICE_TOOLS and t.read_only and not t.requires_confirmation]


def session_config(specs: list[ToolSpec], model: str, voice: str, key_seconds: int = 120) -> dict:
    """Corps de la demande de clé éphémère : la session (modèle, consignes, outils) est fixée côté serveur."""
    return {
        "expires_after": {"anchor": "created_at", "seconds": key_seconds},
        "session": {
            "type": "realtime",
            "model": model,
            "instructions": INSTRUCTIONS,
            "tools": [{"type": "function", "name": t.tool_id, "description": t.description,
                       "parameters": t.input_schema} for t in specs],
            "tool_choice": "auto",
            "audio": {"input": {"transcription": {"model": "gpt-4o-mini-transcribe", "language": "fr"}},
                      "output": {"voice": voice}},
        },
    }


Opener = Callable[[urllib.request.Request, int], Any]


def _default_open(req: urllib.request.Request, timeout: int):
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - URL fixe https


def mint_client_secret(api_key: str, body: dict, opener: Opener = _default_open, timeout: int = 15) -> dict:
    """Demande une clé éphémère à OpenAI. Renvoie {"value", "expires_at"}. La clé permanente n'est jamais renvoyée."""
    if not api_key:
        raise VoiceError("Clé OpenAI absente.")
    req = urllib.request.Request(CLIENT_SECRETS_URL, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with opener(req, timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        raise VoiceError(f"OpenAI a refusé la demande (HTTP {e.code}) {detail}".strip()) from None
    except urllib.error.URLError as e:
        raise VoiceError("api.openai.com injoignable depuis l'App : le domaine doit être autorisé dans la "
                         f"politique réseau serverless du workspace ({e.reason}).") from None
    value = data.get("value") or (data.get("client_secret") or {}).get("value")
    if not value:
        raise VoiceError("Réponse OpenAI inattendue : clé éphémère absente.")
    return {"value": value, "expires_at": data.get("expires_at")}


def _truncate(obj: Any) -> str:
    if isinstance(obj, dict):   # données d'affichage internes jamais envoyées au modèle
        obj = {k: v for k, v in obj.items() if not str(k).startswith("_ui")}
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "…(tronqué)"


def run_tool(registry: ToolRegistry, ctx: ToolContext, name: str, arguments: str | dict,
             call_id: str = "") -> tuple[ToolEvent, str]:
    """Exécute un appel demandé par le modèle. Renvoie (événement pour le journal, sortie JSON pour le modèle)."""
    t0, args = time.monotonic(), {}
    cid = call_id or f"voice_{uuid.uuid4().hex[:12]}"
    try:
        if name not in VOICE_TOOLS or name not in registry.specs:
            raise ToolError(f"Outil « {name} » non autorisé en mode vocal.")
        spec = registry.specs[name]
        if not spec.read_only or spec.requires_confirmation:
            raise ToolError(f"Outil « {name} » non autorisé en mode vocal (écriture).")
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                raise ToolError("Arguments JSON invalides.") from None
        else:
            args = dict(arguments or {})
        out = registry.run(spec, ctx, args)
        ev = ToolEvent(cid, name, args, "succes", result=out, duration_ms=int((time.monotonic() - t0) * 1000))
        return ev, _truncate(out)
    except ToolError as e:
        msg = str(e)
    except Exception as e:  # noqa: BLE001 - erreur technique, distincte d'un refus
        msg = f"Erreur technique ({type(e).__name__}) : {e}"
    ev = ToolEvent(cid, name, args if isinstance(args, dict) else {}, "erreur", error=msg[:2000],
                   duration_ms=int((time.monotonic() - t0) * 1000))
    return ev, json.dumps({"erreur": msg[:500]}, ensure_ascii=False)
