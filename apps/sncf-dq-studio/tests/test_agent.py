import json

from backend.agent import MAX_STEPS, TOOLS, DqAnalyst, system_prompt
from tests.conftest import FakeSql


class FakeModel:
    """Modele factice : renvoie une suite de messages programmes."""

    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = []

    def chat(self, endpoint, messages, tools=None, temperature=None):
        self.calls.append({"endpoint": endpoint, "messages": [dict(m) for m in messages], "tools": tools})
        msg = self.messages.pop(0) if self.messages else {"role": "assistant", "content": "fin"}
        return {"message": msg, "usage": {"total_tokens": 10}}


def call(name, args, cid="c1"):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def agent(model, sql):
    return DqAnalyst(model, sql, "databricks-claude-sonnet-4-6", "dataops_dev", "sncf_dqv3_ddr",
                     bronze_fqn="dataops_dev.description_du_reseau_bronze", source_label="DDR")


def test_outils_declares():
    names = {t["function"]["name"] for t in TOOLS}
    assert {"synthese_qualite", "resultats_regles", "anomalies", "executer_sql", "proposer_regle"} <= names
    p = system_prompt("sncf_dqv3_ddr", "dataops_dev", "dataops_dev.description_du_reseau_bronze", "DDR")
    assert "a_valider" in p and "sans emojis" in p and "dataops_dev.sncf_dqv3_ddr_gold" in p


def test_boucle_outil_puis_reponse():
    sql = FakeSql([[{"table_name": "vitesse_limite_ligne_v", "nb_critiques_en_echec": "1"}]])
    model = FakeModel([call("synthese_qualite", {"table_name": "vitesse_limite_ligne_v"}),
                       {"role": "assistant", "content": "1 regle critique en echec."}])
    events = []
    a = agent(model, sql)
    a.on_event = events.append
    res = a.run("Synthese ?")
    assert res.answer == "1 regle critique en echec."
    assert res.tool_calls[0]["outil"] == "synthese_qualite" and events
    stmt, params, row_limit = sql.calls[0]
    assert "dataops_dev.sncf_dqv3_ddr_gold.v_dq_synthese_table" in stmt and params == {"table_name": "vitesse_limite_ligne_v"}
    assert row_limit == 200
    tool_msg = model.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1" and "vitesse_limite_ligne_v" in tool_msg["content"]
    assert res.usage["total_tokens"] == 20


def test_sql_hors_perimetre_refuse():
    sql = FakeSql()
    a = agent(FakeModel([]), sql)
    out = a.call_tool("executer_sql", {"requete": "SELECT * FROM dataops_dev.ai_studio.agents"})
    assert "erreur" in out and not sql.calls
    out = a.call_tool("executer_sql", {"requete": "DELETE FROM dataops_dev.sncf_dqv3_ddr_gold.dq_kpi_daily"})
    assert "erreur" in out and not sql.calls
    a.call_tool("executer_sql", {"requete": "SELECT count(*) FROM dataops_dev.description_du_reseau_bronze.vitesse_limite_ligne_v"})
    assert len(sql.calls) == 1  # Bronze de la source autorise en lecture


def test_regle_proposee_brouillon_non_enregistree():
    sql = FakeSql()
    model = FakeModel([call("proposer_regle", {
        "table_name": "vitesse_limite_ligne_v", "colonnes": ["codeLigne"], "dimension": "Completude",
        "template": "not_null", "definition_metier": "Le code ligne est renseigne",
        "justification": "3 valeurs nulles au profilage", "seuil_propose": 0.99}),
        {"role": "assistant", "content": "Regle proposee."}])
    res = agent(model, sql).run("Propose une regle")
    assert len(res.drafts) == 1
    d = res.drafts[0]
    assert d["statut_validation"] == "a_valider" and d["origine"] == "agent_ia" and d["criticite_proposee"] == "a_definir"
    assert not sql.calls  # aucune ecriture ni lecture


def test_erreurs_outils_remontees_au_modele():
    sql = FakeSql(fail_on="v_dq_kpi_courant")
    model = FakeModel([call("outil_inconnu", {}), call("resultats_regles", {}, "c2"),
                       {"role": "assistant", "content": "ok"}])
    res = agent(model, sql).run("?")
    assert res.answer == "ok"
    assert "Outil inconnu" in res.tool_calls[0]["erreur"] and "PERMISSION_DENIED" in res.tool_calls[1]["erreur"]


def test_limite_appels():
    model = FakeModel([call("synthese_qualite", {}, f"c{i}") for i in range(MAX_STEPS)]
                      + [{"role": "assistant", "content": "synthese finale"}])
    res = agent(model, FakeSql()).run("?")
    assert res.answer == "synthese finale" and len(res.tool_calls) == MAX_STEPS
    assert model.calls[-1]["tools"]  # outils toujours declares au dernier appel


def test_historique_limite():
    model = FakeModel([{"role": "assistant", "content": "r"}])
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}", "tools": []} for i in range(30)]
    agent(model, FakeSql()).run("q", hist)
    msgs = model.calls[0]["messages"]
    assert msgs[0]["role"] == "system" and len(msgs) == 12 and msgs[-1]["content"] == "q"
    assert all(set(m) <= {"role", "content"} for m in msgs)
