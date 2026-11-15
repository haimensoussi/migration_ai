"""Outil http_call : appelle une URL HTTP(S) fournie et renvoie le résultat du test.

L'appel part de l'App (réseau de l'App, sans identifiants Databricks). Garde-fous :
- validation humaine à chaque appel (l'URL et le corps sont montrés à l'utilisateur avant envoi) ;
- schémas http/https et ports 80, 443, 8080, 8443 uniquement ;
- adresses privées, locales, de lien local (métadonnées cloud) et réservées refusées après résolution DNS ;
- redirections non suivies (l'adresse de redirection est seulement indiquée) ;
- en-têtes d'identification refusés (Authorization, Cookie...) ; valeurs sensibles de l'URL masquées dans les
  résultats et le journal (sig, token, key, code...) ;
- liste optionnelle de domaines autorisés : AI_STUDIO_HTTP_ALLOWED_DOMAINS (ex. "logic.azure.com,sncf.fr").
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.tool_registry import ToolContext, ToolError, ToolPermissionError

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
PORTS = {80, 443, 8080, 8443}
FORBIDDEN_HEADERS = {"authorization", "proxy-authorization", "cookie", "host", "x-api-key", "x-databricks-token"}
HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
SENSITIVE = re.compile(r"^(sig|signature|token|access_token|refresh_token|key|apikey|api_key|code|secret|password|pwd|"
                       r"auth|sv|client_secret)$", re.I)
MAX_READ = 256 * 1024
MAX_TEXT = 4000
ALLOWED_ENV = "AI_STUDIO_HTTP_ALLOWED_DOMAINS"


def mask_url(url: str) -> str:
    try:
        u = urlparse(url)
        q = [(k, "***" if SENSITIVE.match(k) else v) for k, v in parse_qsl(u.query, keep_blank_values=True)]
        netloc = u.hostname or ""
        if u.port:
            netloc += f":{u.port}"
        return urlunparse((u.scheme, netloc, u.path, u.params, urlencode(q, safe="*/:"), ""))
    except ValueError:
        return "(URL invalide)"


def _allowed_domains() -> list[str]:
    return [d.strip().lower().lstrip(".") for d in os.environ.get(ALLOWED_ENV, "").split(",") if d.strip()]


def check_target(url: str, resolver=socket.getaddrinfo) -> tuple[str, int]:
    u = urlparse(str(url or "").strip())
    if u.scheme not in ("http", "https"):
        raise ToolPermissionError("URL refusée : http:// ou https:// attendu.")
    if u.username or u.password:
        raise ToolPermissionError("URL refusée : identifiants dans l'URL interdits.")
    host = (u.hostname or "").lower()
    if not host:
        raise ToolPermissionError("URL refusée : hôte manquant.")
    try:
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError as e:
        raise ToolPermissionError("URL refusée : port invalide.") from e
    if port not in PORTS:
        raise ToolPermissionError(f"Port refusé : {port} (80, 443, 8080 ou 8443).")
    domains = _allowed_domains()
    if domains and not any(host == d or host.endswith("." + d) for d in domains):
        raise ToolPermissionError(f"Domaine non autorisé : {host} (domaines autorisés : {', '.join(domains)}).")
    try:
        infos = resolver(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ToolError(f"Erreur réseau (DNS) : le nom {host} ne peut pas être résolu depuis l'App ({e}). "
                        "Le réseau de l'App bloque probablement ce domaine.") from e
    ips = {ipaddress.ip_address(i[4][0]) for i in infos}
    bad = sorted(str(ip) for ip in ips if not ip.is_global or ip.is_multicast)
    if bad or not ips:
        raise ToolPermissionError(f"Adresse refusée : {host} pointe vers une adresse non publique ({', '.join(bad)}).")
    return host, port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_call(ctx: ToolContext, url: str, method: str = "GET", body=None, headers: dict | None = None,
              timeout_s: int = 15) -> dict:
    method = str(method or "GET").upper()
    if method not in METHODS:
        raise ToolPermissionError(f"Méthode refusée : {method}.")
    check_target(url)
    hdrs = {"User-Agent": "DISCOVERY-http_call/1.0"}
    for k, v in (headers or {}).items():
        if not HEADER_NAME.match(str(k)) or str(k).lower() in FORBIDDEN_HEADERS or any(c in str(v) for c in "\r\n"):
            raise ToolPermissionError(f"En-tête refusé : {k}. Pour une API authentifiée, utilisez un connecteur "
                                      "HTTP sur une connexion Unity Catalog.")
        hdrs[str(k)] = str(v)
    data = None
    if body not in (None, "", {}) and method not in ("GET", "HEAD"):
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        else:
            data = str(body).encode("utf-8")
    timeout = max(1, min(int(timeout_s or 15), 30))
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(str(url).strip(), data=data, method=method, headers=hdrs)
    t0, masked = time.monotonic(), mask_url(url)
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:      # 3xx (non suivie), 4xx, 5xx : résultat du test, pas une panne réseau
        resp = e
    except urllib.error.URLError as e:
        reason = e.reason
        kind = ("TLS" if isinstance(reason, ssl.SSLError) else "délai dépassé" if isinstance(reason, TimeoutError)
                else "connexion")
        raise ToolError(f"Erreur réseau ({kind}) vers {masked} : {reason}") from e
    except TimeoutError as e:
        raise ToolError(f"Erreur réseau (délai dépassé) : pas de réponse de {masked} après {timeout} s.") from e
    try:
        raw = resp.read(MAX_READ + 1) if method != "HEAD" else b""
    finally:
        resp.close()
    code = int(getattr(resp, "status", None) or resp.getcode())
    text = raw[:MAX_READ].decode("utf-8", "replace")
    out = {"url": masked, "methode": method, "statut_http": code, "succes_http": 200 <= code < 300,
           "duree_ms": int((time.monotonic() - t0) * 1000),
           "content_type": resp.headers.get("Content-Type", ""), "reponse": text[:MAX_TEXT],
           "tronque": len(raw) > MAX_TEXT}
    if 300 <= code < 400 and resp.headers.get("Location"):
        out["redirection"] = mask_url(resp.headers["Location"]) + " (non suivie)"
    if "json" in out["content_type"].lower() and len(text) <= MAX_TEXT:
        try:
            out["json"] = json.loads(text)
        except ValueError:
            pass
    return out
