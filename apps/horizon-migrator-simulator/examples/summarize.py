# EXEMPLE FICTIF d'Action HORIZON (écrit pour tester le simulateur ; ne provient pas de la plateforme).
from logs.logs import logger
from aistudio.model.run.RunContext import RunContext
from utils.exceptions import AppException
from apis.run.common.socle_client import SocleClient


def get_input_value(context, name):
    if hasattr(context, 'inputs') and context.inputs:
        for item in context.inputs:
            if item.name == name:
                return item.value
    return None


async def summarize(context: RunContext):
    text = get_input_value(context, 'text')
    max_words = get_input_value(context, 'max_words') or 50

    if not text:
        raise AppException(status_code=422, app_code="MISSING_TEXT",
                           message="Paramètre 'text' requis")
    try:
        max_words = int(max_words)
    except (ValueError, TypeError):
        raise AppException(status_code=422, app_code="INVALID_MAX_WORDS",
                           message="Le paramètre 'max_words' doit être un entier")

    client = SocleClient(context)
    result = client.llm_call(prompt=f"Résume en {max_words} mots maximum :\n{text}",
                             temperature=0.2)

    context.addValue("summary", result["content"], type="string")
    context.addValue("tokens_used", result["tokens_used"], type="int")
    context.bot = result["content"]
    logger.info(f"Résumé généré : {result['tokens_used']} tokens")
    return context
