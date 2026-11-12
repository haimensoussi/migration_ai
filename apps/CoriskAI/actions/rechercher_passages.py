# DÉMONSTRATION : Action HORIZON reconstituée (recherche RAG de CORISK.IA). Ce n'est pas le code HORIZON réel.
# Côté HORIZON, chaque projet a un index FAISS et ses segments sur disque ; le migrateur doit les remplacer par
# l'index Vector Search déclaré dans assistant.yaml (dependencies.vector_indexes), filtré par project_id.
import json
import os
import re

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from logs.logs import logger
from aistudio.model.run.RunContext import RunContext
from utils.exceptions import AppException

DATA_DIR = "/data/corisk"          # un dossier par projet : index.faiss + chunks.json
EMBEDDING_MODEL = "dangvantuan/sentence-camembert-base"
TOP_K_DEFAULT = 8
TOP_K_MAX = 20
PROJECT_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

_encoder = None


def get_input_value(context, name):
    if hasattr(context, 'inputs') and context.inputs:
        for input_item in context.inputs:
            if input_item.name == name:
                return input_item.value
    return None


def _encode(text):
    global _encoder
    if _encoder is None:
        _encoder = SentenceTransformer(EMBEDDING_MODEL)
    return _encoder.encode([text], normalize_embeddings=True).astype(np.float32)


async def rechercher_passages(context: RunContext):
    logger.info("Exécution rechercher_passages")
    question = get_input_value(context, 'question')
    project_id = get_input_value(context, 'project_id')
    top_k = get_input_value(context, 'top_k')

    if question is None or not str(question).strip():
        raise AppException(status_code=422, app_code="MISSING_QUESTION", message="Paramètre 'question' requis")
    if project_id is None or not PROJECT_RE.match(str(project_id)):
        raise AppException(status_code=422, app_code="INVALID_PROJECT",
                           message="Paramètre 'project_id' requis (lettres, chiffres, _ et -, 64 caractères au plus)")
    if top_k is None:
        top_k = TOP_K_DEFAULT
    else:
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            raise AppException(status_code=422, app_code="INVALID_TOP_K",
                               message=f"top_k doit être un entier entre 1 et {TOP_K_MAX}")
        if not 1 <= top_k <= TOP_K_MAX:
            raise AppException(status_code=422, app_code="INVALID_TOP_K",
                               message=f"top_k doit être un entier entre 1 et {TOP_K_MAX}")

    folder = os.path.join(DATA_DIR, str(project_id))
    try:
        index = faiss.read_index(os.path.join(folder, "index.faiss"))
        with open(os.path.join(folder, "chunks.json"), encoding="utf-8") as f:
            chunks = json.load(f)
    except (OSError, RuntimeError):
        chunks = []
    if not chunks:
        raise AppException(status_code=404, app_code="PROJECT_NOT_INDEXED",
                           message=f"Aucun document indexé pour le projet '{project_id}'")

    scores, ids = index.search(_encode(str(question)), top_k)
    passages = []
    for score, i in zip(scores[0], ids[0]):
        if i < 0:
            continue
        c = chunks[i]
        passages.append({"chunk_id": c["chunk_id"], "content": c["content"], "file_name": c["file_name"],
                         "page": c["page"], "score": round(float(score), 4)})

    context.addValue("passages", passages, type="list")
    context.addValue("nb_passages", len(passages), type="int")
    context.bot = f"{len(passages)} passage(s) trouvé(s) pour le projet {project_id}."
    return context
