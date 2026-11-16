"""Outil search_documents (Knowledge Studio, lot 1) : recherche dans un index AI Search, au nom de l'utilisateur.

- Le modèle choisit une BASE déclarée dans la configuration de l'outil, jamais un index arbitraire.
- La requête part avec l'identité de l'utilisateur (droits Unity Catalog sur l'index, scope OAuth de l'App).
- Chaque passage renvoyé porte sa source (fichier, page) pour que l'agent la cite.
"""
from __future__ import annotations

import json

from backend.tool_registry import ToolContext, ToolError

MAX_RESULTS = 10
EXCERPT = 1500          # caractères transmis au modèle par passage
DEFAULT_COLUMNS = {"id": "chunk_id", "texte": "content", "fichier": "file_name", "page": "page"}


def _bases(spec) -> dict:
    bases = (spec.config or {}).get("bases") or {}
    if not bases:
        raise ToolError("Aucune base de connaissances n'est configurée pour cet outil.")
    return bases


def query_index(ctx: ToolContext, index: str, query: str, columns: list[str], k: int, filters: dict | None) -> dict:
    body = {"query_text": query, "columns": columns, "num_results": k, "query_type": "HYBRID"}
    if filters:
        body["filters_json"] = json.dumps(filters, ensure_ascii=False)
    try:
        return ctx.workspace.api_client.do("POST", f"/api/2.0/vector-search/indexes/{index}/query", body=body)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if any(s in msg for s in ("403", "PERMISSION_DENIED", "scope", "Forbidden")):
            raise ToolError("Recherche refusée avec vos droits : il faut SELECT sur l'index (Unity Catalog), le droit "
                            "d'interroger le modèle d'embedding et le scope AI Search autorisé pour l'application. "
                            f"Détail : {msg[:300]}") from e
        raise ToolError(f"Recherche impossible : {msg[:400]}") from e


def search_documents(ctx: ToolContext, spec, query: str, base: str = "", nombre: int = 5, fichier: str = "") -> dict:
    bases = _bases(spec)
    name = base or (spec.config or {}).get("defaut") or next(iter(bases))
    if name not in bases:
        raise ToolError(f"Base inconnue : {name}. Bases disponibles : {', '.join(bases)}.")
    b = bases[name]
    cols = {**DEFAULT_COLUMNS, **(b.get("colonnes") or {})}
    if not str(query or "").strip():
        raise ToolError("Question vide.")
    k = max(1, min(int(nombre or 5), MAX_RESULTS))
    wanted = [cols["id"], cols["fichier"], cols["page"], cols["texte"]]
    r = query_index(ctx, b["index"], query, wanted, k, {cols["fichier"]: fichier} if fichier else None)
    names = [c["name"] for c in (r.get("manifest") or {}).get("columns", [])]
    passages = []
    for i, row in enumerate((r.get("result") or {}).get("data_array") or [], start=1):
        d = dict(zip(names, row))
        texte = str(d.get(cols["texte"]) or "")
        page = d.get(cols["page"])
        if isinstance(page, float) and page.is_integer():   # l'API renvoie les entiers en flottants (3.0)
            page = int(page)
        passages.append({"rang": i, "fichier": d.get(cols["fichier"]), "page": page,
                         "score": round(float(d["score"]), 4) if d.get("score") is not None else None,
                         "id": d.get(cols["id"]), "extrait": texte[:EXCERPT], "tronque": len(texte) > EXCERPT,
                         "_texte": texte})
    out = {"base": name, "titre_base": b.get("titre", name), "question": query, "nombre": len(passages),
           "passages": [{k_: v for k_, v in p.items() if k_ != "_texte"} for p in passages],
           "consigne": ("Réponds uniquement à partir de ces passages et cite chaque source sous la forme "
                        "[fichier, p. N]. Si les passages ne répondent pas, dis-le."),
           "_ui_sources": [{"rang": p["rang"], "fichier": p["fichier"], "page": p["page"], "score": p["score"],
                            "texte": p["_texte"]} for p in passages]}
    if not passages:
        out["message"] = "Aucun passage trouvé dans cette base."
    return out


search_documents.needs_spec = True
