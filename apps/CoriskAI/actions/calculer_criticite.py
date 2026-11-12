# DÉMONSTRATION : Action HORIZON reconstituée (criticité d'un risque CORISK.IA). Ce n'est pas le code HORIZON réel.
# GRILLE DE DÉMONSTRATION, NON VALIDÉE : niveaux et seuils à faire valider par le métier avant tout usage réel.
from logs.logs import logger
from aistudio.model.run.RunContext import RunContext
from utils.exceptions import AppException

GRILLE_VERSION = "demo-0 (à valider)"
# (borne haute incluse, niveau) sur la criticité = probabilité x impact (1 à 25)
NIVEAUX = [(4, "faible"), (9, "modéré"), (14, "élevé"), (25, "critique")]


def get_input_value(context, name):
    if hasattr(context, 'inputs') and context.inputs:
        for input_item in context.inputs:
            if input_item.name == name:
                return input_item.value
    return None


def _note(value, name, app_code):
    """Note entière de 1 à 5 (entier ou chaîne d'entier) ; sinon erreur explicite."""
    message = f"Paramètre '{name}' requis : entier de 1 à 5"
    if value is None or isinstance(value, bool):
        raise AppException(status_code=422, app_code=app_code, message=message)
    try:
        n = value if isinstance(value, int) else int(str(value).strip())
    except ValueError:
        raise AppException(status_code=422, app_code=app_code, message=message)
    if not 1 <= n <= 5:
        raise AppException(status_code=422, app_code=app_code, message=message)
    return n


async def calculer_criticite(context: RunContext):
    logger.info("Exécution calculer_criticite")
    probabilite = _note(get_input_value(context, 'probabilite'), 'probabilite', "INVALID_PROBABILITE")
    impact = _note(get_input_value(context, 'impact'), 'impact', "INVALID_IMPACT")

    criticite = probabilite * impact
    niveau = next(label for borne, label in NIVEAUX if criticite <= borne)

    context.addValue("criticite", criticite, type="int")
    context.addValue("niveau", niveau, type="str")
    context.addValue("grille_version", GRILLE_VERSION, type="str")
    context.bot = f"Criticité {criticite} ({probabilite} x {impact}) : niveau {niveau} (grille {GRILLE_VERSION})."
    return context
