import json

import pytest

from backend.agent_designer import AgentDesigner, CATEGORIES
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS


class FakeSql:
    """SHOW TABLES / DESCRIBE pour une seule table connue : dataops_dev.s.t1."""
    def query(self, statement, params=None, row_limit=None):
        if statement.startswith("SHOW TABLES"):
            return {"columns": ["tableName"], "rows": [{"tableName": "t1", "isTemporary": "false"}], "truncated": False}
        if "`t1`" in statement:
            return {"columns": [], "rows": [{"col_name": "id", "data_type": "string", "comment": None}],
                    "truncated": False}
        raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND")


def call(i, name, args):
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class Model:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, endpoint, messages, tools=None, temperature=None, max_tokens=None):
        self.seen.append({"tools": [t["function"]["name"] for t in tools]})
        return {"message": self.replies.pop(0), "usage": {"total_tokens": 5}}


def designer(replies):
    ctx = ToolContext(sql=FakeSql(), workspace=None, allowed_tables=["x.y.z"])
    return AgentDesigner(Model(replies), ToolRegistry(BUILTIN_TOOLS), ctx, "m-default")


PROPOSAL = {"name": "DQ Advisor", "description": "Explique la qualité.", "category": "Qualité des données",
            "icon": "verified", "instructions": "Tu es un conseiller qualité. Les seuils sont à valider.",
            "tool_ids": ["describe_table", "execute_sql", "outil_invente", "run_job"],
            "knowledge_tables": ["dataops_dev.s.t1", "dataops_dev.s.absente", "t_courte"],
            "temperature": 3, "max_iterations": 50, "test_questions": ["q1", "q2"], "hypotheses": ["h1"]}


def test_explore_then_propose_with_validation():
    d = designer([
        {"role": "assistant", "content": "", "tool_calls": [call("a", "list_tables", {"catalog": "dataops_dev", "schema": "s"})]},
        {"role": "assistant", "content": "", "tool_calls": [call("b", "describe_table", {"table": "dataops_dev.s.t1"})]},
        {"role": "assistant", "content": "", "tool_calls": [call("c", "propose_agent", PROPOSAL)]}])
    res = d.design("Je veux un agent qui explique la qualité des données du schéma s.")
    assert [e.status for e in res.events] == ["succes", "succes"]
    assert d.ctx.allowed_tables == []  # exploration non restreinte pendant la conception
    dr = res.draft
    assert dr["tool_ids"] == ["describe_table", "execute_sql"]          # inventé et non publié écartés
    assert dr["knowledge_tables"] == ["dataops_dev.s.t1"]              # absente et nom court écartés
    assert dr["temperature"] == 1.0 and dr["max_iterations"] == 12     # bornes
    assert dr["model_endpoint"] == "m-default" and dr["category"] in CATEGORIES
    assert any("outil_invente" in w for w in res.warnings) and any("absente" in w for w in res.warnings)
    assert res.test_questions == ["q1", "q2"] and res.hypotheses == ["h1"]
    assert set(d.model.seen[0]["tools"]) == {"list_tables", "describe_table", "propose_agent"}


def test_nudge_then_fail():
    d = designer([{"role": "assistant", "content": "voici mon idée"}, {"role": "assistant", "content": "encore du texte"}])
    with pytest.raises(ToolError):
        d.design("Un agent pour suivre les Jobs en échec.")


def test_nudge_then_success_and_unknown_category():
    p = {**PROPOSAL, "category": "Inconnue", "icon": "licorne", "knowledge_tables": [], "tool_ids": ["get_job_status"]}
    d = designer([{"role": "assistant", "content": "texte"},
                  {"role": "assistant", "content": "", "tool_calls": [call("p", "propose_agent", p)]}])
    res = d.design("Un agent pour suivre les Jobs en échec.")
    assert res.draft["category"] == "Général" and res.draft["icon"] == "smart_toy"
    assert res.draft["tool_ids"] == ["get_job_status"]


def test_short_request_refused():
    with pytest.raises(ToolError):
        designer([]).design("agent")


def test_exploration_tool_outside_scope_is_refused():
    d = designer([
        {"role": "assistant", "content": "", "tool_calls": [call("x", "execute_sql", {"query": "SELECT 1"})]},
        {"role": "assistant", "content": "", "tool_calls": [call("p", "propose_agent", {**PROPOSAL, "knowledge_tables": []})]}])
    res = d.design("Un agent SQL pour explorer les données.")
    assert res.events[0].status == "erreur" and "non disponible" in res.events[0].error


def test_improve_keeps_model_and_lists_changes():
    from backend.agent_designer import config_diff
    current = {"name": "DQ Advisor", "description": "d", "category": "Qualité des données", "icon": "verified",
               "model_endpoint": "modele-choisi", "instructions": "Tu es un conseiller qualité des données.",
               "tool_ids": ["describe_table"], "knowledge_tables": [], "temperature": 0.1, "max_iterations": 6}
    improved = {**PROPOSAL, "name": "DQ Advisor", "tool_ids": ["describe_table", "get_table_profile"],
                "knowledge_tables": [], "temperature": 0.1, "max_iterations": 6,
                "changes": ["Ajout de get_table_profile pour mesurer les nulls"]}
    d = designer([{"role": "assistant", "content": "", "tool_calls": [call("p", "propose_agent", improved)]}])
    res = d.improve(current, "", [{"tool_id": "execute_sql", "status": "erreur", "error": "TABLE_OR_VIEW_NOT_FOUND"}])
    assert res.draft["model_endpoint"] == "modele-choisi"            # le copilote ne change pas le modèle
    assert res.changes == ["Ajout de get_table_profile pour mesurer les nulls"]
    diff = {x["cle"]: x for x in config_diff(current, res.draft)}
    assert diff["tool_ids"]["ajouts"] == ["get_table_profile"] and "model_endpoint" not in diff
    assert "instructions" in diff and "name" not in diff


def test_improve_sends_config_and_errors_to_model():
    class Spy(Model):
        def chat(self, endpoint, messages, tools=None, temperature=None, max_tokens=None):
            self.last = messages
            return super().chat(endpoint, messages, tools, temperature, max_tokens)
    p = {**PROPOSAL, "knowledge_tables": [], "changes": []}
    d = AgentDesigner(Spy([{"role": "assistant", "content": "", "tool_calls": [call("p", "propose_agent", p)]}]),
                      ToolRegistry(BUILTIN_TOOLS), ToolContext(FakeSql(), None), "m")
    res = d.improve({"name": "X", "instructions": "Tu es X, assistant de test.", "model_endpoint": "m"}, "",
                    [{"tool_id": "execute_sql", "error": "TABLE_OR_VIEW_NOT_FOUND"}])
    user_msg = d.model.last[1]["content"]
    assert "Configuration actuelle" in user_msg and "TABLE_OR_VIEW_NOT_FOUND" in user_msg
    assert "Mode amélioration" in d.model.last[0]["content"]
    assert any("aucune modification" in w for w in res.warnings)    # changes vide signalé
