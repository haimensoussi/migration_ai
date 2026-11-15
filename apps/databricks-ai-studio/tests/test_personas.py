import types

import pytest

from backend import personas as P
from backend.agent_repository import AgentRepository
from backend.mentions import parse_mentions

AGENTS = [
    {"agent_id": "m", "name": "Margot", "handle": "margot", "persona": "la cartographe",
     "tagline": "Je situe les gares sur une carte.", "aliases": ["Carto Réseau"]},
    {"agent_id": "v", "name": "Victor", "handle": "victor", "persona": "le veilleur", "aliases": ["Sentinelle DQ Réseau"]},
    {"agent_id": "c", "name": "Clara", "handle": "clara", "persona": "la conseillère qualité",
     "aliases": ["Data Quality Advisor"]},
]


def test_normalize_and_display():
    p = P.normalize({"name": "Léa", "handle": " @Léa ", "persona": "l'assistante bureau",
                     "call_examples": "lire mes messages\n\nrépondre à un mail", "tagline": "  Je lis   vos messages. "})
    assert p["handle"] == "lea" and p["call_examples"] == ["lire mes messages", "répondre à un mail"]
    assert p["tagline"] == "Je lis vos messages."
    assert P.display({"name": "Léa", "persona": "l'assistante bureau"}) == "Léa, l'assistante bureau"
    assert P.display({"name": "Sam"}) == "Sam" and P.mention({"name": "Sam"}) == "Sam"
    assert P.suggest_handle("Jean-Éric Dupont") == "jean"


@pytest.mark.parametrize("handle,msg", [("m", "invalide"), ("Margot!", "invalide"), ("9lives", "invalide"),
                                        ("tous", "réservé"), ("victor", "déjà utilisé par « Victor »"),
                                        ("carto-reseau", "déjà utilisé par « Margot »")])
def test_validate_rejects(handle, msg):
    errs = P.validate(P.normalize({"name": "X", "handle": handle}), AGENTS, "nouveau")
    assert any(msg in e for e in errs), errs


def test_validate_accepts_own_handle_and_checks_lengths():
    assert P.validate(P.normalize({"name": "Margot", "handle": "margot"}), AGENTS, "m") == []
    errs = P.validate(P.normalize({"name": "X", "handle": "xavier", "tagline": "a" * 91,
                                   "call_examples": ["b" * 101]}), AGENTS, None)
    assert len(errs) == 2


def test_mentions_by_handle_alias_and_name():
    r = parse_mentions("@victor et @Carto Réseau : état ?", AGENTS)
    assert [a["agent_id"] for a in r.agents] == ["v", "m"] and r.text == "et: état ?"
    assert [a["agent_id"] for a in parse_mentions("@Clara bonjour", AGENTS).agents] == ["c"]
    assert [a["agent_id"] for a in parse_mentions("@data-quality-advisor ok", AGENTS).agents] == ["c"]
    unk = parse_mentions("@victr ?", AGENTS).unknown
    assert unk and "Victor" in unk[0][1]


class Sql:
    def __init__(self, rows):
        self.rows, self.exec = rows, []

    def query(self, statement, params=None, row_limit=None):
        if "max(version)" in statement:
            return {"rows": [{"v": 2}]}
        return {"rows": [dict(r) for r in self.rows]}

    def execute(self, statement, params=None):
        self.exec.append((statement, params))


def repo(rows):
    s = types.SimpleNamespace(table=lambda n: n, max_iterations=6)
    return AgentRepository(Sql(rows), s)


ROWS = [{"agent_id": "v", "name": "Victor", "description": "", "icon": "", "category": "", "status": "publie",
         "current_version": 1, "owner": "u", "updated_at": None, "handle": "victor", "persona": "le veilleur",
         "tagline": None, "call_examples": None, "aliases": '["Sentinelle DQ Réseau"]', "model_endpoint": "m",
         "tool_ids": "[]", "knowledge_tables": "[]"}]


def test_repository_refuses_duplicate_before_any_write():
    r = repo(ROWS)
    cfg = {"model_endpoint": "m", "instructions": "i"}
    with pytest.raises(ValueError, match="déjà utilisé"):
        r.create_agent({"name": "Vic", "handle": "victor"}, cfg, "u")
    assert r.sql.exec == []                              # ni version ni en-tête écrits
    with pytest.raises(ValueError, match="déjà utilisé"):
        r.save_version("autre", {"name": "Vic", "handle": "sentinelle-dq-reseau"}, cfg, "u")
    assert r.sql.exec == []
    aid = r.create_agent({"name": "Margot", "handle": "margot", "persona": "la cartographe",
                          "aliases": ["Carto Réseau"]}, cfg, "u")
    upd = [p for s, p in r.sql.exec if "SET handle" in s]
    assert aid and upd and upd[0]["handle"] == "margot" and upd[0]["aliases"] == '["Carto Réseau"]'
    assert r.list_agents()[0]["aliases"] == ["Sentinelle DQ Réseau"]
