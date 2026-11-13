"""Outils Smart Office : appel d'un flux Power Automate (déclencheur HTTP « manual »).

- L'URL du flux (signature SAS incluse) est un secret : lue depuis l'environnement
  (ressource secret de l'App), jamais stockée dans le code ni dans les tables.
- Le flux s'exécute avec la connexion Office 365 de son propriétaire, pas avec l'identité
  de l'utilisateur : les envois passent donc par une validation humaine (office_send).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from backend.tool_registry import ToolContext, ToolError, ToolPermissionError

FLOW_ENV = "POWER_AUTOMATE_SMART_OFFICE_URL"
DOMAINS_ENV = "POWER_AUTOMATE_ALLOWED_RECIPIENT_DOMAINS"  # optionnel : "sncf.fr,reseau.sncf.fr"
ALLOWED_HOST_SUFFIXES = (".powerplatform.com", ".logic.azure.com")
PARAM_KEYS = ("to", "subject", "body", "query", "message_id")
TIMEOUT_S = 60
MAX_BODY = 20000


def _flow_url() -> str:
    url = os.environ.get(FLOW_ENV, "").strip()
    if not url:
        raise ToolError("Flux Power Automate non configuré (ressource secret smart-office-flow absente).")
    u = urlparse(url)
    if u.scheme != "https" or not (u.hostname or "").endswith(ALLOWED_HOST_SUFFIXES):
        raise ToolError("URL du flux refusée : hôte Power Platform HTTPS attendu.")
    return url


def build_payload(ctx: ToolContext, technology: str, operation: str, parameters: dict,
                  question: str = "", requires_confirmation: bool = False, status: str = "requested") -> dict:
    """Corps conforme au schéma du déclencheur (technology, operation, parameters requis)."""
    params = {k: str(v) for k, v in parameters.items() if k in PARAM_KEYS and v not in (None, "")}
    return {"sessionId": ctx.conversation_id or "", "question": question or "", "technology": technology,
            "operation": operation, "parameters": params, "status": status,
            "requires_confirmation": bool(requires_confirmation)}


def post_flow(payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(_flow_url(), data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw, code = resp.read().decode("utf-8", "replace"), resp.status
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise ToolError(f"Le flux Power Automate a répondu HTTP {e.code} : {detail}") from e
    except urllib.error.URLError as e:
        raise ToolError(f"Flux Power Automate injoignable : {e.reason}") from e
    except TimeoutError as e:
        raise ToolError(f"Flux Power Automate : pas de réponse après {TIMEOUT_S} s.") from e
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = raw[:MAX_BODY]
    return {"http_status": code, "reponse_flux": body}


def _check_recipients(to: str) -> None:
    domains = [d.strip().lower() for d in os.environ.get(DOMAINS_ENV, "").split(",") if d.strip()]
    addrs = [a.strip().lower() for a in to.replace(";", ",").split(",") if a.strip()]
    if not addrs or any("@" not in a for a in addrs):
        raise ToolError("Destinataire(s) invalide(s).")
    if domains:
        bad = [a for a in addrs if a.rsplit("@", 1)[1] not in domains]
        if bad:
            raise ToolPermissionError("Domaine de destinataire non autorisé : " + ", ".join(bad))


def office_read(ctx: ToolContext, technology: str, operation: str, query: str = "", message_id: str = "",
                question: str = "") -> dict:
    """Opérations de consultation (recherche, lecture d'un message) : sans validation humaine."""
    payload = build_payload(ctx, technology, operation, {"query": query, "message_id": message_id}, question,
                            requires_confirmation=False, status="requested")
    return {"operation": operation, **post_flow(payload)}


def office_send(ctx: ToolContext, technology: str, operation: str, to: str, subject: str, body: str,
                question: str = "", message_id: str = "") -> dict:
    """Opérations d'envoi ou de réponse : exécutées uniquement après approbation dans AI Studio."""
    _check_recipients(to)
    if len(body) > MAX_BODY:
        raise ToolError(f"Corps du message trop long ({len(body)} caractères, maximum {MAX_BODY}).")
    payload = build_payload(ctx, technology, operation,
                            {"to": to, "subject": subject, "body": body, "message_id": message_id}, question,
                            requires_confirmation=True, status="approved")
    return {"operation": operation, "destinataires": to, **post_flow(payload)}
