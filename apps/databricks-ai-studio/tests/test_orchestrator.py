"""Orchestration multi-agents : délégation, garde-fous, journalisation (modèle simulé)."""
import json

import pytest

from backend.agent_designer import AgentDesigner
from backend.agent_runtime import AgentConfig
from backend.orchestrator import ASK_AGENT, Orchestrator, is_supervisor, plain_tools, sub_agent_ids
from backend.tool_registry import ToolContext, ToolError, ToolRegistry, ToolSpec
from tools.catalog import BUILTIN_TOOLS
from tools.orchestration import ask_agent


def call(i, name, args):
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class FakeSql:
    def query(self, statement, params=None, row_limit=None):
        return {"columns": ["tableName"], "rows": [{"tableName": "t1", "isTemporary": "false"}], "truncated": False}


class Model:
    """Réponses scriptées par rôle : 'sup' pour le superviseur, nom d'agent pour les délégués."""
    def __init__(self, scripts):
        self.scripts, self.seen = {k: list(v) for k, v in scripts.items()}, []

    def chat(self, endpoint, messages, tools=None, temperature=None, max_tokens=None):
        system = messages[0]["content"]
        role = "sup" if "Rôle de superviseur" in system else next(k for k in self.scripts if k != "sup" and k in system)
        self.seen.append((role, [t["function"]["name"] for t in (tools or [])], tools))
        return {"message": self.scripts[role].pop(0), "usage": {"total_tokens": 1}}


def cfg(aid, name, tools=(), instr=None):
    return AgentConfig(agent_id=aid, version=1, name=name, model_endpoint="m",
                       instructions=instr or f"Tu es {name}.", tool_ids=list(tools))


DQ = cfg("dq", "DQ Advisor", ["list_tables"])
SQLA = cfg("sql", "SQL Assistant")
NESTED = cfg("sup2", "Autre superviseur", ["agent:dq"])
AGENTS = {"dq": ({"description": "Qualité des données"}, DQ), "sql": ({"description": "Requêtes SQL"}, SQLA),
          "sup2": ({"description": "x"}, NESTED)}


def make(model, max_delegations=4):
    logged = []
    orch = Orchestrator(model, ToolRegistry(BUILTIN_TOOLS), lambda: ToolContext(sql=FakeSql(), workspace=None),
                        AGENTS.get, on_sub_event=lambda aid, ev: logged.append((aid, ev.tool_id, ev.status)),
                        max_delegations=max_delegations)
    return orch, logged


def test_supervisor_delegates_and_synthesizes():
    sup = cfg("sup", "Superviseur DQ", ["agent:dq", "agent:sql", "describe_table"])
    model = Model({
        "sup": [{"role": "assistant", "content": "", "tool_calls": [
                    call("a", ASK_AGENT, {"agent": "DQ Advisor", "question": "Tables du schéma s ?"}),
                    call("b", ASK_AGENT, {"agent": "SQL Assistant", "question": "Écris le SQL de comptage."})]},
                {"role": "assistant", "content": "Selon DQ Advisor : 1 table. Selon SQL Assistant : SELECT count(*)."}],
        "DQ Advisor": [{"role": "assistant", "content": "", "tool_calls": [
                           call("x", "list_tables", {"catalog": "c", "schema": "s"})]},
                       {"role": "assistant", "content": "Le schéma contient 1 table (t1)."}],
        "SQL Assistant": [{"role": "assistant", "content": "SELECT count(*) FROM t1"}]})
    orch, logged = make(model)
    rt, run_cfg, warns = orch.prepare(sup)
    assert warns == [] and run_cfg.tool_ids == ["describe_table", ASK_AGENT]
    res = rt.run(run_cfg, [{"role": "user", "content": "Combien de tables et quel SQL ?"}])
    assert res.final_text.startswith("Selon DQ Advisor")
    asks = [e for e in res.events if e.tool_id == ASK_AGENT]
    assert [e.status for e in asks] == ["succes", "succes"]
    assert asks[0].result["reponse"] == "Le schéma contient 1 table (t1)."
    assert asks[0].result["outils"] == [{"outil": "list_tables", "statut": "succes"}]
    assert logged == [("dq", "list_tables", "succes")]        # appel du délégué journalisé sous son identifiant
    sup_tools = model.seen[0][2]
    enum = next(t for t in sup_tools if t["function"]["name"] == ASK_AGENT)["function"]["parameters"]["properties"]["agent"]["enum"]
    assert enum == ["DQ Advisor", "SQL Assistant"]
    # Le délégué ne voit que ses propres outils, jamais ask_agent
    assert [s[1] for s in model.seen if s[0] == "DQ Advisor"][0] == ["list_tables"]


def test_invalid_sub_agents_are_excluded_with_warnings():
    sup = cfg("sup", "Superviseur", ["agent:sup", "agent:absent", "agent:sup2", "agent:sql"])
    orch, _ = make(Model({"sup": []}))
    _, run_cfg, warns = orch.prepare(sup)
    assert ASK_AGENT in run_cfg.tool_ids and len(warns) == 3
    assert any("lui-même" in w for w in warns) and any("absent" in w for w in warns)
    assert any("un seul niveau" in w for w in warns)


def test_no_valid_sub_agent_falls_back_to_plain_agent():
    orch, _ = make(Model({}))
    _, run_cfg, warns = orch.prepare(cfg("sup", "Superviseur", ["agent:absent", "execute_sql"]))
    assert run_cfg.tool_ids == ["execute_sql"] and any("répond seul" in w for w in warns)
    assert "Rôle de superviseur" not in run_cfg.instructions


def test_delegation_limit_and_unknown_agent():
    sup = cfg("sup", "Superviseur", ["agent:sql"])
    model = Model({
        "sup": [{"role": "assistant", "content": "", "tool_calls": [
                    call("a", ASK_AGENT, {"agent": "SQL Assistant", "question": "q1"}),
                    call("b", ASK_AGENT, {"agent": "SQL Assistant", "question": "q2"}),
                    call("c", ASK_AGENT, {"agent": "Inconnu", "question": "q3"})]},
                {"role": "assistant", "content": "fin"}],
        "SQL Assistant": [{"role": "assistant", "content": "r1"}]})
    orch, _ = make(model, max_delegations=1)
    rt, run_cfg, _ = orch.prepare(sup)
    res = rt.run(run_cfg, [{"role": "user", "content": "go"}])
    st_ = [(e.status, e.error) for e in res.events]
    assert st_[0][0] == "succes"
    assert st_[1][0] == "erreur" and "Limite de 1" in st_[1][1]
    assert st_[2][0] == "erreur" and "non autorisée" in st_[2][1]   # enum : agent hors liste refusé


def test_confirmation_tools_never_run_by_delegation():
    confirm = ToolSpec("danger", "Action", "Test", "Action sensible", {"type": "object", "properties": {}},
                       {"type": "object"}, "tools.uc_tools:list_tables", requires_confirmation=True)
    agents = {"act": ({"description": "Agit"}, cfg("act", "Agent Action", ["danger"]))}
    model = Model({
        "sup": [{"role": "assistant", "content": "", "tool_calls": [
                    call("a", ASK_AGENT, {"agent": "Agent Action", "question": "Fais-le"})]},
                {"role": "assistant", "content": "Validation requise côté Agent Action."}],
        "Agent Action": [{"role": "assistant", "content": "", "tool_calls": [call("d", "danger", {})]}]})
    orch = Orchestrator(model, ToolRegistry(BUILTIN_TOOLS + [confirm]),
                        lambda: ToolContext(sql=FakeSql(), workspace=None), agents.get)
    rt, run_cfg, _ = orch.prepare(cfg("sup", "Superviseur", ["agent:act"]))
    res = rt.run(run_cfg, [{"role": "user", "content": "go"}])
    out = res.events[0].result
    assert out["statut"] == "validation_requise" and "danger" in out["message"]
    assert res.pending is None                                     # rien n'est en attente ni exécuté


def test_helpers_and_tool_without_delegate():
    assert sub_agent_ids(["agent:a", "x"]) == ["a"] and plain_tools(["agent:a", "x"]) == ["x"]
    assert is_supervisor(cfg("s", "S", ["agent:a"])) and not is_supervisor(cfg("s", "S", ["x"]))
    with pytest.raises(ToolError):
        ask_agent(ToolContext(sql=None, workspace=None), "a", "q")


def test_improve_keeps_delegated_agents():
    p = {"name": "Sup", "description": "d", "category": "Orchestration", "icon": "smart_toy",
         "instructions": "Tu es un superviseur clair et précis.", "tool_ids": ["describe_table"],
         "knowledge_tables": [], "temperature": 0.1, "max_iterations": 6, "changes": ["c"]}

    class M:
        def chat(self, *a, **k):
            return {"message": {"role": "assistant", "content": "", "tool_calls": [call("p", "propose_agent", p)]}}
    d = AgentDesigner(M(), ToolRegistry(BUILTIN_TOOLS), ToolContext(sql=FakeSql(), workspace=None), "m")
    res = d.improve({"name": "Sup", "instructions": "x", "model_endpoint": "m",
                     "tool_ids": ["describe_table", "agent:dq", "agent:sql"]})
    assert res.draft["tool_ids"] == ["describe_table", "agent:dq", "agent:sql"]
    assert not any("agent:" in w for w in res.warnings)
