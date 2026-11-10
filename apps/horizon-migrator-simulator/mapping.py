"""Règles locales du simulateur (sans LLM) :
- correspondance prévisionnelle HORIZON -> Databricks calculée à partir des faits de l'analyse statique ;
- contrôles de la configuration générée (équivalence des modèles, endpoints, services externes)."""
from __future__ import annotations

import re

CONTEXT_ATTRS_HANDLED = {"addValue", "bot", "inputs"}


def planned_mapping(f: dict) -> list[dict]:
    rows = []

    def add(src, tgt, status, note):
        rows.append({"Élément source": src, "Cible Databricks": tgt, "Statut prévu": status, "Remarque": note})

    for e in f["entrypoints"]:
        add(f"{'async ' if e['async'] else ''}def {e['name']}({e['context_param']}: RunContext)",
            "Classe MLflow ResponsesAgent (predict / predict_stream)", "Adapté",
            "Action asynchrone HORIZON -> agent synchrone servi par Model Serving.")
    for m in f["internal_imports"]:
        add(f"import {m}", "Supprimé", "Automatique", "Dépendance de la plateforme HORIZON.")
    for m in f["third_party_imports"]:
        add(f"import {m}", "Conservé (requirements.txt)", "Automatique", "Bibliothèque tierce.")
    for i in f["inputs"]:
        if i in ("prompt", "messages"):
            add(f"get_input_value(context, '{i}')", f"request.input + custom_inputs['{i}']", "Automatique",
                "Messages au format Responses ; entrée HORIZON aussi acceptée dans custom_inputs.")
        else:
            add(f"get_input_value(context, '{i}')", f"custom_inputs['{i}']", "Adapté",
                "Mêmes validations et conversions que la source.")
    for o in f["outputs"]:
        add(f"context.addValue('{o['name']}', ...)", f"custom_outputs['{o['name']}']", "Automatique",
            f"Type déclaré : {o.get('type') or 'non précisé'}.")
    if "bot" in f["context_attributes"]:
        add("context.bot", "Message texte de sortie de l'agent", "Adapté", "Réponse conversationnelle.")
    for c in f["error_codes"]:
        add(f"AppException(app_code='{c}')", f"AgentError('{c}')", "Adapté", "Code, statut HTTP et message conservés.")
    for c in f["llm_calls"]:
        add(f"{c['call']}(...)", "Model Serving : /serving-endpoints/<endpoint>/invocations", "Adapté",
            "Endpoint choisi dans model_config.yml ; changement de modèle à valider.")
    for h in f["http_calls"]:
        add(f"{h['call']}({h.get('url') or '...'})", "Service externe paramétré (enabled, url, timeout_s, proxy)",
            "Manuel", "Accès réseau sortant depuis Databricks à vérifier.")
    if f.get("insecure_tls"):
        add("verify=False", "verify=True", "Adapté", "Vérification TLS rétablie.")
    for a in f["context_attributes"]:
        if a not in CONTEXT_ATTRS_HANDLED:
            add(f"context.{a}", "Clé de model_config.yml", "Adapté", "Attribut de contexte HORIZON -> configuration.")
    return rows


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _find_key(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from _find_key(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _find_key(v, key)


def _strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def check_model_mapping(cfg: dict) -> list[dict]:
    """Vérifie que chaque modèle source est associé à un endpoint de même famille et version.
    Exemple accepté : claude-sonnet-4-6 -> databricks-claude-sonnet-4-6 ; refusé : gpt-4o -> databricks-gpt-oss-120b."""
    out = []
    for table in _find_key(cfg or {}, "model_endpoints"):
        if not isinstance(table, dict):
            continue
        for src, ep in table.items():
            if not isinstance(src, str) or not isinstance(ep, str):
                continue
            s, t = _norm(src), _norm(ep)
            if s.startswith("databricks-"):
                ok = s == t
            else:
                t = t[len("databricks-"):] if t.startswith("databricks-") else t
                ok = t == s or t.startswith(s + "-")
            out.append({"Modèle source": src, "Endpoint Databricks": ep, "Équivalent": ok,
                        "Remarque": "Même famille et version" if ok else "Modèle différent : correspondance à refuser ou à valider"})
    return out


def config_endpoints(cfg: dict) -> list[str]:
    return sorted({s for s in _strings(cfg or {}) if s.startswith("databricks-")})


def external_services(cfg: dict) -> list[dict]:
    out = []

    def walk(o, name=""):
        if isinstance(o, dict):
            if "enabled" in o and "url" in o:
                out.append({"Service": name or "-", "URL": o.get("url"), "Activé": o.get("enabled"),
                            "Timeout (s)": o.get("timeout_s"), "Proxy": o.get("proxy")})
            for k, v in o.items():
                walk(v, str(k))
        elif isinstance(o, list):
            for v in o:
                walk(v, name)

    walk(cfg or {})
    return out
