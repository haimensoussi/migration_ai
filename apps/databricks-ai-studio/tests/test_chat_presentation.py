"""Présentation Chat & Test : icônes, consigne de présentation et rendu sûr (Streamlit simulé)."""
import contextlib
import sys
import types
import xml.etree.ElementTree as ET

import pytest

from backend.agent_runtime import AgentConfig, ToolEvent, TurnResult
from ui import discovery_icons as di


def test_svg_assets_are_valid_and_present():
    for name in ["assistant_play", "discovery_train", "user", "tool", "database", "chart", "shield", "document", "alert", "success",
                 "play", "clock", "code", "settings"]:
        ET.fromstring((di.ICON_DIR / f"{name}.svg").read_text())
    assert (di.ASSETS / "css" / "chat.css").is_file()
    assert di.icon_uri("database").startswith("data:image/svg+xml;base64,")


def test_chips_are_capped_unique_and_metadata_driven():
    evs = [{"tool_id": "describe_table", "status": "succes"}, {"tool_id": "list_tables", "status": "succes"},
           {"tool_id": "execute_sql", "status": "succes"}, {"tool_id": "get_job_status", "status": "succes"}]
    chips = di.chips_for(evs, "Qualité des données")
    assert len(chips) == 3 and len({c[0] for c in chips}) == 3
    assert chips[0] == ("shield", "Qualité des données") and chips[1][0] == "database"
    failed = di.chips_for([{"tool_id": "execute_sql", "status": "erreur"}])
    assert failed[0][0] == "alert" and all(c[0] != "success" for c in failed)
    assert di.chips_for([]) == []                      # réponse simple : aucune icône
    assert di.chips_for([], error=True) == [("alert", "Incident d'exécution")]


def test_presentation_guideline_appended_not_replacing():
    out = di.with_presentation("Tu es SQL Assistant.")
    assert out.startswith("Tu es SQL Assistant.") and di.PRESENTATION_GUIDELINE in out
    assert di.with_presentation(out) == out            # pas de duplication


def test_capabilities_follow_tools():
    caps = di.capabilities_for(["list_tables", "execute_sql"])
    assert [c[0] for c in caps] == ["database", "code", "chart"]
    assert di.capabilities_for([]) == []


# ---- Streamlit simulé pour exercer ui/chat_panel.render_chat ---------------------------------
class Rerun(Exception):
    pass


class FakeSt(types.ModuleType):
    def __init__(self, prompt=None):
        super().__init__("streamlit")
        self.session_state, self.calls, self._prompt = {}, [], prompt

    def _ctx(self, *a, **k):
        self.calls.append(("ctx", a, k))
        return contextlib.nullcontext(self)

    chat_message = expander = spinner = container = popover = _ctx

    def markdown(self, body, unsafe_allow_html=False):
        self.calls.append(("markdown", body, unsafe_allow_html))

    def columns(self, spec):
        return [self] * (spec if isinstance(spec, int) else len(spec))

    def caption(self, *a, **k): pass
    def button(self, *a, **k): return False
    def json(self, *a, **k): pass
    def dataframe(self, *a, **k): pass
    def warning(self, *a, **k): self.calls.append(("warning", a))
    def error(self, *a, **k): self.calls.append(("error", a))

    def chat_input(self, *a, **k):
        p, self._prompt = self._prompt, None
        return p

    def rerun(self):
        raise Rerun()


@pytest.fixture
def panel(monkeypatch):
    def load(prompt, runtime):
        fake = FakeSt(prompt)
        monkeypatch.setitem(sys.modules, "streamlit", fake)
        state = types.ModuleType("ui.state")
        state.current_user = lambda: types.SimpleNamespace(email="u@sncf.fr", mode="utilisateur")
        state.UserAuthMissing = type("UserAuthMissing", (Exception,), {})
        logged = {}
        state.repository = lambda: types.SimpleNamespace(
            log_tool_call=lambda *a: None,
            log_messages=lambda conv, cfg, *a: logged.setdefault("cfg", cfg) and 1)
        state.build_runtime = lambda **k: runtime
        state.build_runtime_for = lambda cfg, **k: (runtime, cfg, [])
        state.mentionable_agents = lambda: []
        monkeypatch.setitem(sys.modules, "ui.state", state)
        import ui
        monkeypatch.setattr(ui, "state", state, raising=False)
        sys.modules.pop("ui.chat_panel", None)
        import ui.chat_panel as cp
        return cp, fake, logged
    return load


CFG = AgentConfig(agent_id="a1", version=2, name="SQL Assistant", model_endpoint="m",
                  instructions="Tu es SQL Assistant.", tool_ids=["list_tables", "execute_sql"])


class Runtime:
    def __init__(self, text="", events=(), boom=None):
        self.text, self.events, self.boom, self.seen = text, list(events), boom, None

    def run(self, cfg, messages):
        self.seen = cfg
        if self.boom:
            raise self.boom
        msgs = messages + [{"role": "assistant", "content": self.text}]
        return TurnResult(messages=msgs, new_messages=msgs[-1:], events=self.events, final_text=self.text,
                          pending=None, latency_ms=10)


def test_welcome_then_turn_with_icons_and_safe_markdown(panel):
    ev = ToolEvent("c1", "execute_sql", {"query": "SELECT 1"}, "succes", {"lignes": [{"x": 1}]}, None, 5)
    rt = Runtime("## Résultat\n\n| x |\n|---|\n| 1 |\n\n```sql\nSELECT 1\n```\n<script>alert(1)</script>", [ev])
    cp, fake, logged = panel("Combien ?", rt)
    with pytest.raises(Rerun):
        cp.render_chat(CFG, key="k", category="Analyse")
    # Accueil affiché avant le premier message, avec icônes de capacités
    assert any(c[0] == "markdown" and "Mes capacités" in c[1] for c in fake.calls)
    # Le runtime reçoit les instructions de l'agent + la consigne ; l'historique reçoit la config d'origine
    assert rt.seen.instructions.startswith("Tu es SQL Assistant.") and di.PRESENTATION_GUIDELINE in rt.seen.instructions
    assert logged["cfg"].instructions == "Tu es SQL Assistant."
    # Second passage : rendu de la conversation
    fake.calls.clear()
    with contextlib.suppress(Rerun):
        cp.render_chat(CFG, key="k", category="Analyse")
    md = [c for c in fake.calls if c[0] == "markdown"]
    llm = [c for c in md if "<script>" in c[1]]
    assert llm and all(c[2] is False for c in llm)         # contenu du modèle jamais rendu en HTML
    head = [c for c in md if "DISCOVERY — SQL Assistant" in c[1]]
    assert head and head[0][2] is True and "Analyse des données" in head[0][1]
    assert any(c[1] == "Combien ?" and c[2] is False for c in md)
    avatars = [c[2].get("avatar") for c in fake.calls if c[0] == "ctx" and c[2].get("avatar")]
    assert any(str(a).endswith("assistant_play.svg") for a in avatars)
    assert any(str(a).endswith("user.svg") for a in avatars) and any(str(a).endswith("tool.svg") for a in avatars)


def test_runtime_error_is_kept_visible_with_alert(panel):
    cp, fake, _ = panel("go", Runtime(boom=RuntimeError("WAREHOUSE_UNAVAILABLE")))
    with pytest.raises(Rerun):
        cp.render_chat(CFG, key="e")
    item = fake.session_state["chat_e"]["display"][-1]
    assert "WAREHOUSE_UNAVAILABLE" in item["content"] and item["chips"][0][0] == "alert"


def test_two_agents_have_separate_conversations(panel):
    cp, fake, _ = panel("q1", Runtime("r1"))
    with pytest.raises(Rerun):
        cp.render_chat(CFG, key="a1_v2")
    other = AgentConfig(agent_id="a2", version=1, name="Data Quality Advisor", model_endpoint="m", instructions="DQ")
    fake._prompt = "q2"
    with pytest.raises(Rerun):
        cp.render_chat(other, key="a2_v1", category="Qualité des données")
    a, b = fake.session_state["chat_a1_v2"]["display"], fake.session_state["chat_a2_v1"]["display"]
    assert a[-1]["agent"] == "SQL Assistant" and b[-1]["agent"] == "Data Quality Advisor"
    assert b[-1]["chips"] == [("shield", "Qualité des données")]



@pytest.fixture
def mention_panel(monkeypatch):
    """Chat avec deux agents mentionnables ; chaque agent a son runtime scripté."""
    def load(prompt, answers):
        fake = FakeSt(prompt)
        monkeypatch.setitem(sys.modules, "streamlit", fake)
        state = types.ModuleType("ui.state")
        state.current_user = lambda: types.SimpleNamespace(email="u@sncf.fr", mode="utilisateur")
        state.UserAuthMissing = type("UserAuthMissing", (Exception,), {})
        cfgs = {"se": AgentConfig("se", 1, "Sentinelle DQ Réseau", "m", "Tu es Sentinelle."),
                "dq": AgentConfig("dq", 1, "Data Quality Advisor", "m", "Tu es DQ.")}
        log = {"msgs": [], "calls": []}
        state.mentionable_agents = lambda: [{"agent_id": "se", "name": "Sentinelle DQ Réseau", "category": "Qualité des données"},
                                            {"agent_id": "dq", "name": "Data Quality Advisor", "category": "Qualité des données"}]
        state.repository = lambda: types.SimpleNamespace(
            get_config=lambda aid: cfgs.get(aid), log_tool_call=lambda *a: None,
            log_messages=lambda conv, c, u, msgs, idx, lat: log["msgs"].append((c.agent_id, [m["content"] for m in msgs])) or idx + len(msgs))

        def build(c, **k):
            rt = Runtime(answers[c.agent_id])
            log["calls"].append(rt)
            return rt, c, []
        state.build_runtime_for = build
        monkeypatch.setitem(sys.modules, "ui.state", state)
        import ui
        monkeypatch.setattr(ui, "state", state, raising=False)
        sys.modules.pop("ui.chat_panel", None)
        import ui.chat_panel as cp
        return cp, fake, log
    return load


def test_single_mention_answers_directly_with_context(mention_panel):
    cp, fake, log = mention_panel("@sentinelle la table est-elle à jour ?", {"se": "Oui, à jour.", "a1": "main"})
    with pytest.raises(Rerun):
        cp.render_chat(CFG, key="m1")
    s = fake.session_state["chat_m1"]
    last = s["display"][-1]
    assert last["agent"] == "Sentinelle DQ Réseau" and last["content"] == "Oui, à jour."
    assert len(log["calls"]) == 1                                 # l'agent principal n'a pas été appelé
    sent = log["calls"][0].seen
    assert sent.agent_id == "se"
    # Journalisation sous l'agent mentionné, message utilisateur d'origine conservé
    assert log["msgs"][0][0] == "se" and log["msgs"][0][1][0] == "@sentinelle la table est-elle à jour ?"
    # Historique de l'agent principal : question + réponse étiquetée
    assert s["history"][-1]["content"].startswith("[Réponse de Sentinelle DQ Réseau]")


def test_two_mentions_then_main_synthesis(mention_panel):
    cp, fake, log = mention_panel("@sentinelle et @Data Quality Advisor : état global ?",
                                  {"se": "Fraîcheur OK", "dq": "6198 anomalies", "a1": "Synthèse : ..."})
    with pytest.raises(Rerun):
        cp.render_chat(CFG, key="m2")
    s = fake.session_state["chat_m2"]
    speakers = [d["agent"] for d in s["display"] if d["kind"] == "msg" and d["role"] == "assistant"]
    assert speakers == ["Sentinelle DQ Réseau", "Data Quality Advisor", "SQL Assistant"]
    assert [c.seen.agent_id for c in log["calls"]] == ["se", "dq", "a1"]
    # Une seule entrée assistant regroupée avant la synthèse (alternance des rôles)
    roles = [m["role"] for m in s["history"]]
    assert roles.count("assistant") >= 1 and "assistant\nassistant" not in "\n".join(roles[:-1])


def test_unknown_mention_shows_notice_and_main_answers(mention_panel):
    cp, fake, log = mention_panel("@sentinel bonjour", {"a1": "réponse principale"})
    with pytest.raises(Rerun):
        cp.render_chat(CFG, key="m3")
    s = fake.session_state["chat_m3"]
    notes = [d["content"] for d in s["display"] if d["kind"] == "notice"]
    assert notes and "Sentinelle DQ Réseau" in notes[0]
    assert s["display"][-1]["agent"] == "SQL Assistant"


def test_mention_button_prefix_is_applied(mention_panel):
    cp, fake, log = mention_panel("combien d'anomalies ?", {"dq": "6198"})
    fake.session_state["chat_m4"] = {"conversation_id": "c", "history": [], "display": [], "pending": None,
                                     "next_index": 0, "mention_prefix": "Data Quality Advisor"}
    with pytest.raises(Rerun):
        cp.render_chat(CFG, key="m4")
    s = fake.session_state["chat_m4"]
    assert s["display"][0]["content"] == "@Data Quality Advisor combien d'anomalies ?"
    assert s["display"][-1]["agent"] == "Data Quality Advisor" and "mention_prefix" not in s



def test_three_successive_questions_are_all_answered(mention_panel):
    """Non-régression : chaque nouvelle question saisie est traitée, pas seulement la première."""
    cp, fake, log = mention_panel("question 1", {"a1": "réponse"})
    for i in (1, 2, 3):
        fake._prompt = f"question {i}"
        with pytest.raises(Rerun):
            cp.render_chat(CFG, key="multi")
    s = fake.session_state["chat_multi"]
    users = [d["content"] for d in s["display"] if d["kind"] == "msg" and d["role"] == "user"]
    answers = [d for d in s["display"] if d["kind"] == "msg" and d["role"] == "assistant"]
    assert users == ["question 1", "question 2", "question 3"] and len(answers) == 3
    assert [m["role"] for m in s["history"]] == ["user", "assistant"] * 3
