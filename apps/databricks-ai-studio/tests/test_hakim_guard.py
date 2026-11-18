import json

from backend import hakim_guard as g
from backend.agent_runtime import AgentConfig, AgentRuntime, TurnResult
from backend.tool_registry import ToolContext, ToolRegistry, ToolSpec

ECHO = ToolSpec(tool_id="echo", name="Echo", category="Test", description="renvoie le texte",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={"type": "object"}, executor="tools.testing:echo")
CREER = ToolSpec(tool_id="creer_outil", name="Créer un outil", category="Test", description="écriture",
                 input_schema={"type": "object", "properties": {"brouillon_id": {"type": "string"}}},
                 output_schema={"type": "object"}, executor="tools.testing:echo_empty",
                 requires_confirmation=True, read_only=False)
DRAFTS = {"b1": {"kind": "outil", "draft": {"tool_id": "gares_par_region", "name": "Gares par région",
                                            "parameters": [{"name": "region", "type": "string"}]}}}
GOOD = ("Je vais enregistrer l'outil gares_par_region en brouillon. Paramètre : region (facultatif, exemple "
        "Bretagne). Logique : COUNT(*) des gares groupées par région. Cas testés : sans région 13 lignes, "
        "Bretagne 1 ligne.")


class ScriptedModel:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, endpoint, messages, tools=None, temperature=None, max_tokens=2048):
        self.calls.append(list(messages))
        return {"message": self.replies.pop(0), "usage": {"total_tokens": 10}}


def call(i, name, args):
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def cfg():
    return AgentConfig(agent_id="h", version=1, name="HakimAI", model_endpoint="m", instructions="test",
                       tool_ids=["echo", "creer_outil"], max_iterations=6)


def runtime(replies):
    return AgentRuntime(ScriptedModel(replies), ToolRegistry([ECHO, CREER]), ToolContext(None, None),
                        before_confirm=lambda t, a, m: g.presentation_issue(t, a, m, DRAFTS))


def tool_msg(payload):
    return {"role": "tool", "tool_call_id": "x", "content": json.dumps(payload, ensure_ascii=False)}


# -- 1. Présentation avant la fiche ------------------------------------------------------------------
def test_presentation_required():
    msgs = [{"role": "user", "content": "crée l'outil"}, {"role": "assistant", "content": ""}]
    issue = g.presentation_issue("creer_outil", {"brouillon_id": "b1"}, msgs, DRAFTS)
    assert issue and "gares_par_region" in issue and "region" in issue and "résumé" in issue
    msgs[-1]["content"] = GOOD
    assert g.presentation_issue("creer_outil", {"brouillon_id": "b1"}, msgs, DRAFTS) is None
    assert g.presentation_issue("archiver", {}, msgs[:1], DRAFTS) is None


def test_presentation_ignores_previous_turns():
    msgs = [{"role": "assistant", "content": GOOD}, {"role": "user", "content": "ok vas-y"},
            {"role": "assistant", "content": ""}]
    assert g.presentation_issue("creer_outil", {"brouillon_id": "b1"}, msgs, DRAFTS)


def test_runtime_blocks_then_proposes_fiche():
    rt = runtime([{"role": "assistant", "content": "", "tool_calls": [call("c1", "creer_outil", {"brouillon_id": "b1"})]},
                  {"role": "assistant", "content": GOOD,
                   "tool_calls": [call("c2", "creer_outil", {"brouillon_id": "b1"})]}])
    res = rt.run(cfg(), [{"role": "user", "content": "crée l'outil"}])
    assert [e.status for e in res.events] == ["erreur"] and "Fiche non présentée" in res.events[0].error
    assert res.pending and res.pending["call"]["id"] == "c2"


def test_runtime_without_guard_unchanged():
    rt = AgentRuntime(ScriptedModel([{"role": "assistant", "content": "",
                                      "tool_calls": [call("c1", "creer_outil", {"brouillon_id": "b1"})]}]),
                      ToolRegistry([ECHO, CREER]), ToolContext(None, None))
    assert rt.run(cfg(), [{"role": "user", "content": "x"}]).pending["call"]["id"] == "c1"


# -- 2. Refus écrit par l'application ---------------------------------------------------------------
def test_refusal_result_fixed_text_no_model():
    msgs = [{"role": "user", "content": "crée"},
            {"role": "assistant", "content": GOOD,
             "tool_calls": [call("c1", "creer_outil", {"brouillon_id": "b1"}), call("c2", "echo", {"text": "a"})]}]
    res = g.refusal_result(msgs, "c1", "Enregistrer l'outil « Gares par région » (gares_par_region) en brouillon")
    assert res.final_text.startswith("Vous avez refusé l'enregistrement")
    assert "Rien n'a été écrit" in res.final_text and "plateforme" not in res.final_text
    assert [e.status for e in res.events] == ["refuse", "erreur"]
    assert [m["role"] for m in res.new_messages] == ["tool", "tool", "assistant"]
    assert not g.unanswered_calls(res.messages) and res.pending is None


# -- 3. Fidélité -----------------------------------------------------------------------------------
def conv(answer, *payloads, user="compte les gares par département"):
    return [{"role": "user", "content": user}, *[tool_msg(p) for p in payloads],
            {"role": "assistant", "content": answer}]


ROWS = {"rows": [{"departement": f"Dept {chr(65 + i % 26)}{chr(65 + i // 26)}", "nb": "29"} for i in range(96)],
        "nombre_lignes": 96}


def test_invented_count_flagged():
    issues = g.fidelity_issues(conv("Il y a 80 départements.", ROWS))
    assert [i["valeur"] for i in issues] == ["80"]


def test_row_count_and_sum_accepted():
    assert g.fidelity_issues(conv("96 départements, 2 784 gares au total.", ROWS)) == []


def test_french_formats_and_percent():
    p = {"rows": [{"annee": "2025", "taux": "0.912634", "trains": "2792"}]}
    assert g.fidelity_issues(conv("En 2025 : 91,26 % de régularité sur 2 792 trains.", p)) == []
    assert [i["valeur"] for i in g.fidelity_issues(conv("Taux 93,10 %.", p))] == ["93,10 %"]


def test_derived_values_accepted():
    p = {"rows": [{"a": "300"}, {"a": "200"}], "autre": "700"}
    # 500 = somme (colonne), 100 = écart, 42,86 = 300/700 en %
    assert g.fidelity_issues(conv("300 contre 200 (écart 100), soit 42,86 % de 700.", p)) == []


def test_small_integers_codes_dates_and_code_blocks_ignored():
    ans = ("Étape 3 : la règle DQ_010 v2 couvre 2013-01 à 2026-03.\n```sql\nSELECT 12345 FROM t\n```\n"
           "Voir `LIMIT 500`.")
    assert g.fidelity_issues(conv(ans, {"rows": []})) == []


def test_user_numbers_are_sources_but_guard_messages_are_not():
    assert g.fidelity_issues(conv("Filtre sur 75 appliqué.", {"rows": []}, user="les gares du 75")) == []
    msgs = conv("Il y a 80 départements.", ROWS)
    msgs.insert(-1, g.correction_message([{"detail": "le nombre « 80 » n'apparaît dans aucun résultat d'outil"}]))
    assert [i["valeur"] for i in g.fidelity_issues(msgs)] == ["80"]


def test_apostrophe_added_to_returned_value_flagged():
    p = {"rows": [{"region": "Provence-Alpes-Côte dAzur", "nb": "146"}]}
    issues = g.fidelity_issues(conv("Provence-Alpes-Côte d'Azur : 146 gares.", p))
    assert [i["type"] for i in issues] == ["libelle"] and "dAzur" in issues[0]["detail"]
    ok = {"rows": [{"region": "Provence-Alpes-Côte d'Azur", "nb": "146"}]}
    assert g.fidelity_issues(conv("Provence-Alpes-Côte d’Azur : 146 gares.", ok)) == []
    assert g.fidelity_issues(conv("L'outil renvoie 146 gares pour Côte dAzur.", p)) == []


def test_truncated_tool_result_still_read():
    msgs = conv("2 792 gares.", {})
    msgs[1]["content"] = '{"status": "succes", "result": {"total": 2792, "rows": [... [résultat tronqué]'
    assert g.fidelity_issues(msgs) == []


def test_verify_turn_corrects_once():
    rt = runtime([{"role": "assistant", "content": "Il y a 96 départements."}])
    first_msgs = conv("Il y a 80 départements.", ROWS)
    first = TurnResult(messages=first_msgs, new_messages=first_msgs[1:], events=[],
                       final_text="Il y a 80 départements.")
    res, left = g.verify_turn(rt, cfg(), first)
    assert left == [] and res.final_text == "Il y a 96 départements."
    shown = [m["content"] for m in res.new_messages if m["role"] == "assistant"]
    assert shown == ["Il y a 96 départements."]
    assert not any(m["role"] == "user" for m in res.new_messages)
    sent = rt.model.calls[0][-1]
    assert sent["role"] == "user" and sent["content"].startswith(g.GUARD_PREFIX) and "80" in sent["content"]


def test_verify_turn_reports_remaining_issue():
    rt = runtime([{"role": "assistant", "content": "Toujours 80 départements."}])
    m = conv("Il y a 80 départements.", ROWS)
    res, left = g.verify_turn(rt, cfg(), TurnResult(messages=m, new_messages=m[1:], events=[], final_text=m[-1]["content"]))
    assert [i["valeur"] for i in left] == ["80"] and "80" in g.warning_text(left)
    assert len(rt.model.calls) == 1   # une seule relance


def test_verify_turn_noop_when_clean():
    rt = runtime([])
    m = conv("Il y a 96 départements.", ROWS)
    first = TurnResult(messages=m, new_messages=m[1:], events=[], final_text=m[-1]["content"])
    res, left = g.verify_turn(rt, cfg(), first)
    assert res is first and left == [] and rt.model.calls == []
