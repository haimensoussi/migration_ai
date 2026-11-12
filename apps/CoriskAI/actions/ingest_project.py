"""Préparation RAG et stockage des segments dans Delta via SQL Warehouse."""
import hashlib
import os
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
from extract_project_pdf import extract_project_pdf


def split_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError('chunk_size doit être > overlap >= 0')
    result = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        result.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return result


def ingest_project(project_id: str, pdf_path: str) -> dict:
    """Retourne des chunks, sans écrire en base. À connecter à Delta/Vector Search ensuite."""
    extracted = extract_project_pdf(project_id, pdf_path)
    chunks = []
    for page in extracted['pages']:
        for index, content in enumerate(split_text(page['text'])):
            key = f"{project_id}:{extracted['file_name']}:{page['page']}:{index}"
            chunks.append({'chunk_id': hashlib.sha256(key.encode()).hexdigest(),
                           'project_id': project_id, 'file_name': extracted['file_name'],
                           'page': page['page'], 'chunk_index': index, 'content': content})
    return {'project_id': project_id, 'chunk_count': len(chunks), 'chunks': chunks,
            'next_step': 'Persist chunks to a Delta table and create a Vector Search index'}
