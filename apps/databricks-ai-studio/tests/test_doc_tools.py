import json

import pytest

from backend.agent_runtime import AgentConfig, AgentRuntime
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS

REG = ToolRegistry(BUILTIN_TOOLS)
SPEC = REG.specs["search_documents"]
RESP = {"manifest": {"columns": [{"name": "chunk_id"}, {"name": "file_name"}, {"name": "page"}, {"name": "content"},
                                 {"name": "score"}]},
        "result": {"data_array": [["c1", "doc.pdf", 3.0, "Le fournisseur annonce un retard. " * 80, 0.97],
                                  ["c2", "doc.pdf", 4, "Zone humide protégée.", 0.9]]}}


class Api:
    def __init__(self, resp=RESP, fail=None):
        self.resp, self.fail, self.calls = resp, fail, []

    def do(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.fail:
            raise RuntimeError(self.fail)
        return self.resp


class W:
    def __init__(self, api):
        self.api_client = api


def ctx(api):
    return ToolContext(sql=None, workspace=W(api), user_email="a@sncf.fr")


def test_spec_published_read_only_with_configured_base():
    assert SPEC.status == "publie" and SPEC.read_only and not SPEC.requires_confirmation
    assert SPEC.config["bases"]["corisk"]["index"] == "dataops_dev.knowledge.corisk_chunks_index"


def test_hybrid_query_and_citations():
    api = Api()
    r = REG.run(SPEC, ctx(api), {"query": "retard fournisseur", "nombre": 3})
    m, path, body = api.calls[0]
    assert path == "/api/2.0/vector-search/indexes/dataops_dev.knowledge.corisk_chunks_index/query"
    assert body["query_type"] == "HYBRID" and body["num_results"] == 3 and "filters_json" not in body
    p = r["passages"][0]
    assert (p["fichier"], p["page"], p["rang"]) == ("doc.pdf", 3, 1) and isinstance(p["page"], int)
    assert p["tronque"] and len(p["extrait"]) == 1500
    assert "_texte" not in p and len(r["_ui_sources"][0]["texte"]) > 1500 and "cite" in r["consigne"]


def test_only_configured_bases_and_bounds():
    with pytest.raises(ToolError, match="non autorisée"):           # 1re barrière : schéma de l'outil (enum)
        REG.run(SPEC, ctx(Api()), {"query": "x", "base": "dataops_dev.autre.index"})
    from tools.doc_tools import search_documents
    with pytest.raises(ToolError, match="Base inconnue"):           # 2e barrière : configuration de l'outil
        search_documents(ctx(Api()), SPEC, "x", base="dataops_dev.autre.index")
    api = Api()
    REG.run(SPEC, ctx(api), {"query": "x", "nombre": 99, "fichier": "doc.pdf"})
    body = api.calls[0][2]
    assert body["num_results"] == 10 and json.loads(body["filters_json"]) == {"file_name": "doc.pdf"}


def test_permission_error_is_explained():
    with pytest.raises(ToolError, match="droits"):
        REG.run(SPEC, ctx(Api(fail="403 PERMISSION_DENIED")), {"query": "x"})


class Model:
    def __init__(self):
        self.n, self.seen = 0, []

    def chat(self, endpoint, messages, tools=None, temperature=0.1):
        self.n += 1
        self.seen.append(messages)
        if self.n == 1:
            return {"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                    "function": {"name": "search_documents", "arguments": json.dumps({"query": "retard"})}}]}}
        return {"message": {"role": "assistant", "content": "ok"}}


def test_model_gets_excerpts_not_full_ui_sources():
    m = Model()
    AgentRuntime(m, REG, ctx(Api())).run(
        AgentConfig("a", 1, "A", "m", "Instructions de test suffisantes.", ["search_documents"]),
        [{"role": "user", "content": "q"}])
    tool_msg = next(x for x in m.seen[-1] if x.get("role") == "tool")
    assert "_ui_sources" not in tool_msg["content"] and "doc.pdf" in tool_msg["content"]
