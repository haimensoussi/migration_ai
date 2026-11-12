"""Appel LLM Databricks pour analyse de risques à partir d'un contexte documentaire."""
import os
from databricks.sdk import WorkspaceClient

SYSTEM_PROMPT = """Tu es un analyste des risques projets SNCF Réseau.
Identifie uniquement les risques étayés par le contexte fourni.
Pour chaque risque, indique description, probabilité (1-5), impact (1-5),
criticité (produit), mitigation et citations des pages si disponibles.
N'invente pas de faits; signale les informations manquantes.
Réponds en français."""


def agent_risk_chat(question: str, context_chunks: list[dict], endpoint: str | None = None) -> dict:
    endpoint = endpoint or os.environ.get('DATABRICKS_LLM_ENDPOINT')
    if not endpoint:
        raise ValueError('DATABRICKS_LLM_ENDPOINT est requis')
    if not question.strip():
        raise ValueError('Question vide')
    context = '\n\n'.join(
        f"[Document: {c.get('file_name','?')}, page {c.get('page','?')}]\n{c.get('content','')}"
        for c in context_chunks[:12]
    )
    client = WorkspaceClient()
    response = client.serving_endpoints.query(
        name=endpoint,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': f'Contexte documentaire :\n{context}\n\nQuestion : {question}'},
        ],
        max_tokens=1500,
        temperature=0.1,
    )
    answer = response.choices[0].message.content if response.choices else ''
    return {'question': question, 'answer': answer, 'sources': [
        {'file_name': c.get('file_name'), 'page': c.get('page')} for c in context_chunks[:12]
    ]}
