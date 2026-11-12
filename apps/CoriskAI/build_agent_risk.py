"""Configuration d'un agent de risques; l'exécution est assurée par agent_risk_chat."""
import os
from agent_risk_chat import SYSTEM_PROMPT, agent_risk_chat


def build_agent_risk() -> dict:
    return {
        'name': 'CORISK Risk Analyst',
        'endpoint': os.environ.get('DATABRICKS_LLM_ENDPOINT'),
        'system_prompt': SYSTEM_PROMPT,
        'action': agent_risk_chat,
    }
