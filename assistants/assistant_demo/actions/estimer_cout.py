# EXEMPLE FICTIF d'Action HORIZON (écrit pour tester la migration d'un assistant multi-Actions).
# Grille et formule identiques à _compute_finops de l'Action llm_call (USD par million de tokens, 0,92 EUR/USD).
from logs.logs import logger
from aistudio.model.run.RunContext import RunContext
from utils.exceptions import AppException

PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-5": {"input": 2.00, "output": 8.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
}
USD_TO_EUR = 0.92


def get_input_value(context, name):
    if hasattr(context, 'inputs') and context.inputs:
        for input_item in context.inputs:
            if input_item.name == name:
                return input_item.value
    return None


def _to_tokens(value, name):
    if value is None:
        return 0
    try:
        n = int(value)
    except (ValueError, TypeError):
        n = -1
    if n < 0:
        raise AppException(
            status_code=422,
            app_code="INVALID_TOKENS",
            message=f"Le paramètre '{name}' doit être un entier positif ou nul"
        )
    return n


async def estimer_cout(context: RunContext):
    logger.info("Exécution estimer_cout")
    model = get_input_value(context, 'model')
    # Correspondance exacte (préfixe d'endpoint Databricks accepté) : pas de recherche par sous-chaîne
    key = str(model or "").strip().lower()
    if key.startswith("databricks-"):
        key = key[len("databricks-"):]
    pricing = PRICING.get(key)
    if pricing is None:
        raise AppException(
            status_code=422,
            app_code="INVALID_MODEL",
            message=f"Modèle inconnu : '{model}'. Modèles tarifés : {sorted(PRICING)}"
        )

    prompt_tokens = _to_tokens(get_input_value(context, 'prompt_tokens'), 'prompt_tokens')
    completion_tokens = _to_tokens(get_input_value(context, 'completion_tokens'), 'completion_tokens')

    prompt_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    completion_cost = (completion_tokens / 1_000_000) * pricing["output"]
    total_cost = prompt_cost + completion_cost

    context.addValue("modele", key, type="string")
    context.addValue("cout_usd", total_cost, type="number")
    context.addValue("cout_micro_eur", round(total_cost * 1_000_000 * USD_TO_EUR, 2), type="number")
    context.addValue("cout_entree_micro_eur", round(prompt_cost * 1_000_000 * USD_TO_EUR, 2), type="number")
    context.addValue("cout_sortie_micro_eur", round(completion_cost * 1_000_000 * USD_TO_EUR, 2), type="number")
    context.bot = (f"{key} : {prompt_tokens} tokens en entrée + {completion_tokens} en sortie = "
                   f"{round(total_cost * 1_000_000 * USD_TO_EUR, 2)} µ€ ({total_cost:.6f} USD).")
    return context
