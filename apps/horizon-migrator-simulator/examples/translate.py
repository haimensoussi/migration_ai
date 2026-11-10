# EXEMPLE FICTIF d'Action HORIZON (écrit pour tester le simulateur ; ne provient pas de la plateforme).
# Illustre un appel HTTP externe non bloquant et une liste de valeurs autorisées.
import requests
from logs.logs import logger
from aistudio.model.run.RunContext import RunContext
from utils.exceptions import AppException
from apis.run.common.socle_client import SocleClient

GLOSSARY_URL = "https://glossaire.example.org/api/terms"  # service fictif
SUPPORTED_LANGUAGES = ("en", "de", "es", "it")


def get_input_value(context, name):
    if hasattr(context, 'inputs') and context.inputs:
        for item in context.inputs:
            if item.name == name:
                return item.value
    return None


def _load_glossary(domain):
    try:
        r = requests.get(GLOSSARY_URL, params={"domain": domain}, timeout=5)
        r.raise_for_status()
        return r.json().get("terms", [])
    except Exception as e:
        logger.warning(f"Glossaire indisponible (non bloquant) : {e}")
        return []


async def translate(context: RunContext):
    text = get_input_value(context, 'text')
    target = get_input_value(context, 'target_language') or "en"
    domain = get_input_value(context, 'domain') or "ferroviaire"

    if not text:
        raise AppException(status_code=422, app_code="MISSING_TEXT",
                           message="Paramètre 'text' requis")
    if target not in SUPPORTED_LANGUAGES:
        raise AppException(status_code=422, app_code="UNSUPPORTED_LANGUAGE",
                           message="Langue cible non supportée")

    terms = _load_glossary(domain)
    glossary = "\n".join(f"- {t['source']} -> {t['target']}" for t in terms if t.get("lang") == target)

    client = SocleClient(context)
    result = client.llm_call(
        messages=[{"role": "system", "content": f"Traduis en '{target}'. Glossaire :\n{glossary}"},
                  {"role": "user", "content": text}],
        temperature=0,
    )

    context.addValue("translation", result["content"], type="string")
    context.addValue("glossary_terms_used", len(terms), type="int")
    context.addValue("tokens_used", result["tokens_used"], type="int")
    context.bot = result["content"]
    return context
