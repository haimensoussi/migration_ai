import json

import pytest

from backend.tool_designer import ToolDesigner
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS

T = "dataops_dev.description_du_reseau_bronze.gares_de_voyageurs"


def call(i, name, args):
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class Model:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, endpoint, messages, tools=None, temperature=None, max_tokens=None):
        self.seen.append([dict(m) for m in messages])
        return {"message": self.replies.pop(0), "usage": {"total_tokens": 10}}


class Sql:
    def __init__(self):
        self.calls = []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, row_limit))
        if statement.startswith("EXPLAIN"):
            return {"columns": ["plan"], "rows": [{"plan": "== Physical Plan =="}], "truncated": False}
        return {"columns": ["c"], "rows": [{"c": 1}], "truncated": False}


GOOD = {"feasible": True, "name": "Gares par département", "category": "Données", "type": "sql_template",
        "description": "Liste les gares voyageurs d'un département (code à 2 chiffres) avec coordonnées.",
        "sql": f"SELECT Nom_Gare FROM {T} WHERE left(`Code commune`, 2) = :departement ORDER BY Nom_Gare",
        "parameters": [{"name": "departement", "type": "string", "description": "Code", "required": True,
                        "example": "35"}], "hypotheses": ["Département = 2 premiers caractères du code commune"]}


def designer(replies, sql=None):
    sql = sql or Sql()
    return ToolDesigner(Model(replies), ToolRegistry(BUILTIN_TOOLS),
                        ToolContext(sql=sql, workspace=None, max_rows=200), "m", "u@sncf.fr"), sql


def test_explore_then_propose_valid_tool():
    d, sql = designer([
        {"role": "assistant", "content": "", "tool_calls": [call("1", "execute_sql", {"query": f"SELECT * FROM {T}", "limit": 500})]},
        {"role": "assistant", "content": "", "tool_calls": [call("2", "propose_tool", GOOD)]}])
    res = d.design("Un outil qui liste les gares d'un département")
    assert res.draft["tool_id"] == "gares_par_departement" and res.check.ok and res.attempts == 1
    assert res.events[0].arguments["limit"] == 20 and sql.calls[0][1] == 20      # exploration bornée
    assert res.hypotheses == GOOD["hypotheses"]


def test_errors_are_sent_back_for_correction():
    bad = {**GOOD, "sql": f"SELECT * FROM {T} WHERE a = :departement AND b = :oublie"}
    model_replies = [{"role": "assistant", "content": "", "tool_calls": [call("1", "propose_tool", bad)]},
                     {"role": "assistant", "content": "", "tool_calls": [call("2", "propose_tool", GOOD)]}]
    d, _ = designer(model_replies)
    res = d.design("Un outil qui liste les gares d'un département")
    assert res.check.ok and res.attempts == 2
    feedback = json.loads(d.model.seen[1][-1]["content"])
    assert feedback["statut"] == "a_corriger" and "oublie" in feedback["erreurs"][0]


def test_gives_up_after_two_fixes_and_returns_errors():
    bad = {**GOOD, "sql": f"DELETE FROM {T} WHERE a = :departement"}
    d, _ = designer([{"role": "assistant", "content": "", "tool_calls": [call(str(i), "propose_tool", bad)]}
                     for i in range(3)])
    res = d.design("Un outil qui supprime les gares d'un département")
    assert not res.check.ok and res.attempts == 3 and "refusée" in res.check.errors[0]


def test_unsupported_request_and_short_request():
    d, _ = designer([{"role": "assistant", "content": "", "tool_calls": [call("1", "propose_tool", {
        "feasible": False, "unsupported_reason": "Les appels HTTP ne sont pas encore disponibles."})]}])
    res = d.design("Un connecteur vers l'API météo externe")
    assert res.draft is None and "HTTP" in res.unsupported
    with pytest.raises(ToolError):
        d.design("outil")


def test_improve_keeps_identifier():
    other = {**GOOD, "tool_id": "nouveau_nom", "changes": ["Description précisée"]}
    d, _ = designer([{"role": "assistant", "content": "", "tool_calls": [call("1", "propose_tool", other)]}])
    res = d.improve({**GOOD, "tool_id": "gares_par_departement"}, "précise la description")
    assert res.draft["tool_id"] == "gares_par_departement" and res.changes == ["Description précisée"]
    assert "gares_par_departement" in d.model.seen[0][0]["content"]



def test_scope_in_prompt_and_budget_warning():
    explore = {"role": "assistant", "content": "", "tool_calls": [call("e", "list_tables", {"catalog": "c", "schema": "s"})]}
    replies = [explore] * 4 + [{"role": "assistant", "content": "", "tool_calls": [call("p", "propose_tool", GOOD)]}]
    d, _ = designer(replies)
    d.max_steps = 5
    res = d.design("Un outil qui liste les gares d'un département", scope="dataops_dev.description_du_reseau_bronze")
    assert res.check.ok
    assert "dataops_dev.description_du_reseau_bronze" in d.model.seen[0][0]["content"]
    assert any("Il te reste 2 étapes" in (m.get("content") or "") for m in d.model.seen[-1] if m["role"] == "user")
