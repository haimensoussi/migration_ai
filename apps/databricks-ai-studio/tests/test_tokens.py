"""T103 : les jetons du tour sont enregistrés avec la réponse finale (table conversations)."""
import re
import types

from backend.agent_repository import AgentRepository, token_counts
from backend.agent_runtime import AgentConfig


class Sql:
    def __init__(self):
        self.exec = []

    def execute(self, statement, params=None):
        self.exec.append((statement, params))


def repo():
    sql = Sql()
    return AgentRepository(sql, types.SimpleNamespace(table=lambda n: f"t.{n}", max_iterations=6)), sql


CFG = AgentConfig(agent_id="a1", version=3, name="SQL Assistant", model_endpoint="databricks-claude-sonnet-4-6",
                  instructions="")
MSGS = [{"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": "Voici"}]


def test_token_counts_normalises_usage():
    assert token_counts({"prompt_tokens": 10, "completion_tokens": 5}) == \
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert token_counts(None) == {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    assert token_counts({"total_tokens": "x", "prompt_tokens": -1, "completion_tokens": True})["total_tokens"] is None


def test_tokens_and_model_carried_by_final_answer_only():
    r, sql = repo()
    nxt = r.log_messages("conv", CFG, "u@sncf.fr", MSGS, 4, 1200,
                         usage={"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000})
    assert nxt == 8
    stmt, p = sql.exec[0]
    assert "prompt_tokens, completion_tokens, total_tokens, model_endpoint" in stmt
    assert [p[f"tt{i}"] for i in range(4)] == [None, None, None, 1000]
    assert p["pt3"] == 900 and p["ct3"] == 100 and p["l3"] == 1200
    assert [p[f"me{i}"] for i in range(4)] == [None, CFG.model_endpoint, None, CFG.model_endpoint]
    assert p["t3"] == "Voici"                                    # contenu non écrasé par les jetons
    used = set(re.findall(r":(\w+)", stmt))
    assert used == set(p)                                       # aucun paramètre inutilisé ni manquant


def test_without_usage_tokens_are_null():
    r, sql = repo()
    r.log_messages("conv", CFG, "u", MSGS[:1], 0)
    p = sql.exec[0][1]
    assert p["pt0"] is None and p["tt0"] is None and p["me0"] is None
