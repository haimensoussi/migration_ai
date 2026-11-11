# EXEMPLE FICTIF d'Action HORIZON (écrit pour tester la migration d'un assistant multi-Actions).
import math
import re

from logs.logs import logger
from aistudio.model.run.RunContext import RunContext
from utils.exceptions import AppException

CHARS_PER_TOKEN = 4  # estimation usuelle : environ 4 caractères par token
WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")  # « aujourd'hui », « porte-avions » = 1 mot
SENTENCE_SPLIT_RE = re.compile(r"[.!?…]+")


def get_input_value(context, name):
    if hasattr(context, 'inputs') and context.inputs:
        for input_item in context.inputs:
            if input_item.name == name:
                return input_item.value
    return None


async def analyser_texte(context: RunContext):
    logger.info("Exécution analyser_texte")
    texte = get_input_value(context, 'texte')

    if texte is None or not str(texte).strip():
        raise AppException(
            status_code=422,
            app_code="MISSING_TEXT",
            message="Paramètre 'texte' requis"
        )
    texte = str(texte)

    nb_caracteres = len(texte)
    nb_mots = len(WORD_RE.findall(texte))
    nb_phrases = len([s for s in SENTENCE_SPLIT_RE.split(texte) if s.strip()])
    tokens_estimes = math.ceil(nb_caracteres / CHARS_PER_TOKEN)

    context.addValue("nb_caracteres", nb_caracteres, type="int")
    context.addValue("nb_mots", nb_mots, type="int")
    context.addValue("nb_phrases", nb_phrases, type="int")
    context.addValue("tokens_estimes", tokens_estimes, type="int")
    context.bot = (f"{nb_mots} mots, {nb_phrases} phrase(s), {nb_caracteres} caractères, "
                   f"environ {tokens_estimes} tokens.")
    return context
