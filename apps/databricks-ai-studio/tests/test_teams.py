import types

import pytest

from backend import teams as T
from backend.mentions import parse_mentions
from backend.team_repository import TeamRepository

AG = [
    {"agent_id": "j", "name": "Jules", "handle": "jules", "status": "publie", "tool_ids": ["agent:c", "agent:v"]},
    {"agent_id": "c", "name": "Clara", "handle": "clara", "status": "publie", "tool_ids": ["execute_sql"]},
    {"agent_id": "v", "name": "Victor", "handle": "victor", "status": "publie", "tool_ids": ["execute_sql"]},
    {"agent_id": "m", "name": "Margot", "handle": "margot", "status": "publie", "tool_ids": ["render_map"]},
    {"agent_id": "s", "name": "Sam", "handle": "sam", "status": "brouillon", "tool_ids": []},
]
Q = {"team_id": "q", "name": "Qualité des données", "handle": "qualite", "members": ["c", "v"], "lead_agent_id": "j",
     "mission": "Contrôles, anomalies et fraîcheur.", "status": "publie"}


def errs(t, teams=()):
    return " | ".join(T.validate(T.normalize(t), AG, list(teams)))


def test_normalize_suggests_handle_and_removes_lead_from_members():
    n = T.normalize({"name": "Équipe Géographie", "members": ["m", "m", "j"], "lead_agent_id": "j"})
    assert n["handle"] == "geographie" and n["members"] == ["m"] and n["filiere"] == "Transverse"
    assert errs(Q) == ""


@pytest.mark.parametrize("change,msg", [
    ({"handle": "victor"}, "nom d'appel de l'agent « Victor »"),
    ({"handle": "tous"}, "réservé"),
    ({"members": []}, "Au moins un membre"),
    ({"lead_agent_id": None}, "besoin d'un chef"),
    ({"members": ["c", "j"], "lead_agent_id": "m"}, "« Jules » coordonne d'autres agents"),
    ({"human_owner": "pas-un-mail"}, "adresse e-mail"),
    ({"mission": "x" * 141}, "Mission trop longue"),
])
def test_rules(change, msg):
    assert msg in errs({**Q, **change})


def test_one_level_of_delegation_across_teams():
    other = {"team_id": "o", "name": "Autre", "handle": "autre", "members": ["m"], "lead_agent_id": "j", "status": "brouillon"}
    assert "dirige déjà l'équipe « Autre »" in errs(Q, [other])
    assert "@qualite est déjà utilisé" in errs({**Q, "team_id": "n"}, [Q])
    archived = {**Q, "team_id": "z", "status": "archive"}
    assert errs(Q, [archived]) == ""


def test_publish_rules_and_routing():
    assert T.publish_errors(T.normalize(Q), AG) == []
    assert "membre doit être publié" in T.publish_errors(T.normalize({**Q, "members": ["s"], "lead_agent_id": None}), AG)[0]
    assert T.target_agent(T.normalize(Q)) == "j"
    assert T.target_agent(T.normalize({"members": ["m"]})) == "m"
    assert T.lead_tool_ids(["render_map", "agent:x"], ["c", "v"]) == ["render_map", "agent:c", "agent:v"]
    txt = T.lead_instructions(T.normalize(Q), [a for a in AG if a["agent_id"] in "cv"])
    assert "« Clara »" in txt and "« Victor »" in txt and "N'invente aucun résultat" in txt


def test_team_mention_goes_to_lead_and_no_first_word_alias():
    e = T.mention_entry(T.normalize(Q), AG)
    assert e["agent_id"] == "j" and e["handle"] == "qualite" and e["kind"] == "team" and e["persona"] == "2 agents"
    geo = T.mention_entry(T.normalize({"name": "Géographie", "handle": "geo", "members": ["m"]}), AG)
    pool = [e, geo] + AG
    assert [a["name"] for a in parse_mentions("@qualite point ?", pool).agents] == ["Équipe Qualité des données"]
    assert [a["agent_id"] for a in parse_mentions("@geo carte", pool).agents] == ["m"]
    assert parse_mentions("@equipe ?", [e]).agents == []          # pas d'alias « premier mot » pour une équipe


class Sql:
    def __init__(self, teams_rows, member_rows):
        self.t, self.m, self.exec = teams_rows, member_rows, []

    def query(self, statement, params=None, row_limit=None):
        if "FROM t.team_members" in statement or "team_members" in statement and "SELECT team_id, agent_id" in statement:
            return {"rows": [dict(r) for r in self.m]}
        if "teams" in statement:
            return {"rows": [dict(r) for r in self.t]}
        return {"rows": []}

    def execute(self, statement, params=None):
        self.exec.append((statement, params))


def trepo(user_admin=False, team_owner="owner@sncf.fr"):
    rows = [{"team_id": "q", "name": "Qualité", "handle": "qualite", "mission": "", "filiere": "Transverse",
             "icon": "groups", "lead_agent_id": "j", "human_owner": None, "status": "brouillon", "owner": team_owner}]
    mem = [{"team_id": "q", "agent_id": "j", "role": "chef", "is_primary": False, "position": 0},
           {"team_id": "q", "agent_id": "c", "role": "membre", "is_primary": True, "position": 1},
           {"team_id": "q", "agent_id": "v", "role": "membre", "is_primary": True, "position": 2}]
    sql = Sql(rows, mem)
    settings = types.SimpleNamespace(table=lambda n: f"t.{n}", team_admins=("admin@sncf.fr",) if user_admin else (),
                                     tool_admins=())
    agents = types.SimpleNamespace(sql=sql, s=settings, list_agents=lambda: AG)
    return TeamRepository(agents), sql


def test_list_and_publication_reserved_to_admins():
    r, sql = trepo()
    t = r.list_teams()[0]
    assert t["members"] == ["c", "v"] and t["primary"] == ["c", "v"] and t["lead_agent_id"] == "j"
    with pytest.raises(PermissionError, match="administrateur"):
        r.set_status("q", "publie", "owner@sncf.fr")
    with pytest.raises(PermissionError, match="créateur"):
        r.set_status("q", "archive", "autre@sncf.fr")
    r.set_status("q", "archive", "owner@sncf.fr")
    assert any("SET status" in s and p["s"] == "archive" for s, p in sql.exec)
    assert any("team_history" in s and p["a"] == "archivage" for s, p in sql.exec)
    ra, sqla = trepo(user_admin=True)
    ra.set_status("q", "publie", "admin@sncf.fr")
    assert any("SET status" in s and p["s"] == "publie" for s, p in sqla.exec)


def test_only_owner_or_admin_edits():
    r, _ = trepo()
    with pytest.raises(PermissionError, match="créateur"):
        r.save({"team_id": "q", "name": "Qualité", "handle": "qualite", "members": ["c", "v"], "lead_agent_id": "j"},
               "autre@sncf.fr")
