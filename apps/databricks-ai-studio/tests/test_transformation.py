"""HakimAI Transformation, lot A : droits, statuts, preuves, découverte sans lecture de lignes, outils HakimAI."""
import itertools
import re
import types

import pytest

from backend import hakim
from backend import transformation as T
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.hakim_tools import Platform

ME, OTHER, ADMIN = "a@sncf.fr", "b@sncf.fr", "admin@sncf.fr"
CAT, SCH = "dataops_dev", "ai_studio"
GARES = {"name": "data_gares", "full_name": f"{CAT}.{SCH}.data_gares", "comment": "Référentiel des gares",
         "columns": [{"name": "code_uic", "type": "string", "comment": "Code UIC"},
                     {"name": "nom_gare", "type": "string", "comment": ""},
                     {"name": "latitude", "type": "double", "comment": "Latitude"}]}
FREQ = {"name": "data_frequentation", "full_name": f"{CAT}.{SCH}.data_frequentation", "comment": "",
        "columns": [{"name": "Code UIC", "type": "string", "comment": ""},
                    {"name": "date_releve", "type": "date", "comment": "Date"},
                    {"name": "voyageurs", "type": "bigint", "comment": "Voyageurs"}]}
EXACT = {"data_gares": {"x_0": "100", "x_1": "97"}}   # code_uic unique ; nom_gare : l'approximation était optimiste
CONFIG = {"name": "agents", "full_name": f"{CAT}.{SCH}.agents", "comment": "configuration", "columns": []}
STATS = {"data_gares": {"n__": "100", "nn_0": "100", "d_0": "100", "nn_1": "100", "d_1": "97", "nn_2": "90",
                        "d_2": "90", "mn_2": "41.3", "mx_2": "51.0"},
         "data_frequentation": {"n__": "300", "nn_0": "300", "d_0": "100", "nn_1": "300", "d_1": "3",
                                "mn_1": "2025-01-01", "mx_1": "2025-03-01", "nn_2": "295", "d_2": "280",
                                "mn_2": "0", "mx_2": "90000"}}


class Sql:
    """SqlClient factice de l'utilisateur : agrégats par table, journal des requêtes."""

    def __init__(self, fail: str = ""):
        self.queries, self.fail, self.done = [], fail, []

    def query(self, statement, params=None, row_limit=None):
        self.queries.append(statement)
        if "LEFT JOIN" in statement:                        # correspondance d'un lien
            return {"rows": [{"n": "300", "found": "294"}]}
        table = re.search(r"FROM `[^`]+`\.`[^`]+`\.`([^`]+)`", statement).group(1)
        if table == self.fail:
            raise RuntimeError("PERMISSION_DENIED: SELECT")
        if "count(DISTINCT" in statement:                   # confirmation exacte des clés
            return {"rows": [dict(EXACT[table])]}
        return {"columns": list(STATS[table]), "rows": [dict(STATS[table])]}

    def execute(self, statement, params=None):   # journal copilot_actions (compte de l'App)
        self.done.append((statement, params))


def lister(c, s):
    assert (c, s) == (CAT, SCH)
    return [GARES, FREQ, CONFIG]


clock = itertools.count()


@pytest.fixture
def svc():
    return T.TransformationService(T.MemoryTransformationStore(), now=lambda: f"2026-11-19T10:{next(clock) % 60:02d}:00")


def _discovered(svc, user=ME):
    plan = svc.create("Plan IA Gares", user)
    svc.set_discovery(plan["plan_id"], user, T.discover(lister, Sql(), CAT, SCH))
    return plan["plan_id"]


# --- Découverte -----------------------------------------------------------------------------------------
def test_profile_query_only_aggregates():
    q = T.profile_query("c.s.t", [{"name": "a`b", "type": "string"}, {"name": "d", "type": "date"}])
    items = re.match(r"SELECT (.*) FROM `c`\.`s`\.`t`$", q).group(1).split(", ")
    assert all(re.match(r"(count|approx_count_distinct|CAST\((min|max))\(", i) for i in items), items
    assert "`a``b`" in q                                   # nom de colonne échappé
    assert "min(`a``b`)" not in q and "min(`d`)" in q       # pas de min/max sur le texte


def test_discover_scope_stats_and_links():
    sql = Sql()
    d = T.discover(lister, sql, CAT, SCH)
    assert [t["table"] for t in d["tables"]] == [FREQ["full_name"], GARES["full_name"]]   # hors data_ exclu
    assert len(sql.queries) == 4 and not any("agents" in q for q in sql.queries)   # 2 profils, 1 exact, 1 lien
    g = next(t for t in d["tables"] if t["table"] == GARES["full_name"])
    cols = {c["nom"]: c for c in g["colonnes"]}
    assert g["lignes"] == 100 and cols["code_uic"]["cle_candidate"] and not cols["latitude"]["cle_candidate"]
    assert cols["nom_gare"]["distinct_exact"] and cols["nom_gare"]["valeurs_distinctes"] == 97
    assert not cols["nom_gare"]["cle_candidate"]                     # réfutée par le comptage exact
    assert cols["latitude"]["remplissage_pct"] == 90.0 and cols["latitude"]["min"] == "41.3"
    assert "min" not in cols["nom_gare"]
    assert d["liens_probables"] == [{"de": f"{FREQ['full_name']}.Code UIC", "vers": f"{GARES['full_name']}.code_uic",
                                     "cardinalite": "n-1", "base": d["liens_probables"][0]["base"],
                                     "couverture_pct": 98.0, "valeurs_sans_correspondance": 6}]
    assert all("LEFT JOIN" not in q or ("count(*)" in q and "count(b.k)" in q) for q in sql.queries)
    assert f"{GARES['full_name']}.latitude : rempli à 90.0 %." in d["constats"]
    assert any("6 valeur(s) sans correspondance (98.0 % retrouvées)" in c for c in d["constats"])
    assert f"{FREQ['full_name']} : table sans description." in d["constats"]
    s = T.discovery_summary(d)
    assert s["tables"][0]["periodes"] == {"date_releve": ["2025-01-01", "2025-03-01"]}
    assert [t["colonnes_sans_description"] for t in s["tables"]] == [1, 1]


def test_measures_are_never_keys():
    info = {"full_name": "c.s.t", "columns": [{"name": "Total Voyageurs", "type": "double"},
                                              {"name": "id", "type": "bigint"}]}
    p = T.table_profile(info, {"n__": "10", "nn_0": "10", "d_0": "11", "nn_1": "10", "d_1": "11"})
    assert [c["cle_candidate"] for c in p["colonnes"]] == [False, True]   # id reste à confirmer en exact


def test_discover_technical_error_is_separate():
    d = T.discover(lister, Sql(fail="data_gares"), CAT, SCH)
    err = next(t for t in d["tables"] if t["table"] == GARES["full_name"])
    assert "PERMISSION_DENIED" in err["erreur"] and "colonnes" not in err
    assert any("profil impossible" in c for c in d["constats"]) and d["liens_probables"] == []


def test_one_to_one_link_listed_once():
    a = {"table": "x.a", "colonnes": [{"nom": "id_gare", "cle_candidate": True}]}
    b = {"table": "x.b", "colonnes": [{"nom": "ID gare", "cle_candidate": True}]}
    assert [(l["de"], l["cardinalite"]) for l in T.infer_links([a, b])] == [("x.a.id_gare", "1-1")]


# --- Règles du plan -------------------------------------------------------------------------------------
def test_visibility_and_owner_only(svc):
    pid = _discovered(svc)
    assert [p["plan_id"] for p in svc.list_plans(ME, False)] == [pid]
    assert svc.list_plans(OTHER, False) == [] and len(svc.list_plans(ADMIN, True)) == 1
    with pytest.raises(T.TransformationError, match="introuvable"):
        svc.get(pid, OTHER, False)
    assert svc.get(pid, ADMIN, True)["owner"] == ME                     # l'administrateur consulte
    for call in (lambda: svc.set_context(pid, ADMIN, {"secteur": "x"}),
                 lambda: svc.propose(pid, ADMIN, [{"type": "objectif", "nom": "x"}]),
                 lambda: svc.set_context(pid, OTHER, {"secteur": "x"})):
        with pytest.raises(T.TransformationError):
            call()


def test_context_merge_and_unknown_field(svc):
    pid = svc.create("P", ME)["plan_id"]
    svc.set_context(pid, ME, {"secteur": "Gares et Connexions", "objectifs": ""})
    ctx = svc.set_context(pid, ME, {"objectifs": "Réduire   les retards"})
    assert ctx == {"secteur": "Gares et Connexions", "objectifs": "Réduire les retards"}
    with pytest.raises(T.TransformationError, match="inconnus"):
        svc.set_context(pid, ME, {"budget": "1 M"})


def test_propose_requires_evidence_and_lot_a_types(svc):
    pid = _discovered(svc)
    with pytest.raises(T.TransformationError, match="preuve"):
        svc.propose(pid, ME, [{"type": "domaine", "nom": "Gares"}])
    with pytest.raises(T.TransformationError, match="absente"):
        svc.propose(pid, ME, [{"type": "domaine", "nom": "Gares", "tables": ["data_inventee"]}])
    with pytest.raises(T.TransformationError, match="Type"):
        svc.propose(pid, ME, [{"type": "feuille_de_route", "nom": "Vague 1"}])
    with pytest.raises(T.TransformationError, match="15"):
        svc.propose(pid, ME, [{"type": "objectif", "nom": f"o{i}"} for i in range(16)])
    res = svc.propose(pid, ME, [{"type": "domaine", "nom": "Gares", "tables": ["data_gares"]},
                                {"type": "objectif", "nom": "Mieux informer"}])
    items = svc.items(pid, ME, False)
    assert len(res["ajoutes"]) == 2 and {i["status"] for i in items} == {"propose"}
    assert items[0]["evidence"]["tables"] == [GARES["full_name"]]          # nom court résolu en nom complet
    again = svc.propose(pid, ME, [{"type": "domaine", "nom": "gares", "tables": ["data_gares"]}])
    assert again == {"etape": 3, "ajoutes": [], "deja_presents": ["gares"]}


def test_propose_without_discovery_only_objectives(svc):
    pid = svc.create("P", ME)["plan_id"]
    assert svc.propose(pid, ME, [{"type": "objectif", "nom": "Réduire les retards"}])["ajoutes"]
    with pytest.raises(T.TransformationError, match="absente"):
        svc.propose(pid, ME, [{"type": "processus", "nom": "Suivi", "tables": ["data_gares"]}])


def test_decide_owner_only_and_progress(svc):
    pid = _discovered(svc)
    svc.set_context(pid, ME, {"secteur": "Gares", "objectifs": "Informer"})
    svc.propose(pid, ME, [{"type": "domaine", "nom": "Gares", "tables": ["data_gares"]},
                          {"type": "processus", "nom": "Suivi de fréquentation", "tables": ["data_frequentation"]}])
    dom, proc = svc.items(pid, ME, False)
    plan = svc.get(pid, ME, False)
    assert [s["statut"] for s in svc.progress(plan, svc.items(pid, ME, False))][:4] == ["fait", "fait", "en_cours", "a_faire"]
    with pytest.raises(T.TransformationError):
        svc.decide(pid, dom["item_id"], ADMIN, "valide")
    with pytest.raises(T.TransformationError, match="Statut"):
        svc.decide(pid, dom["item_id"], ME, "publie")
    svc.decide(pid, dom["item_id"], ME, "valide", "OK métier")
    svc.decide(pid, proc["item_id"], ME, "valide")
    items = svc.items(pid, ME, False)
    assert items[0]["decided_by"] == ME and items[0]["decision_note"] == "OK métier"
    assert svc.progress(plan, items)[2]["statut"] == "fait"
    svc.decide(pid, proc["item_id"], ME, "propose")                          # rouvrir
    items = svc.items(pid, ME, False)
    assert items[1]["decided_by"] is None and svc.progress(plan, items)[2]["statut"] == "en_cours"


# --- Outils HakimAI -------------------------------------------------------------------------------------
TRANSFO = {t.tool_id: t for t in hakim.TOOLS if t.executor.startswith("tools.hakim_transformation_tools:")}


def test_tool_catalog_cannot_decide():
    assert set(TRANSFO) == {"transformation_plans", "transformation_etat", "transformation_creer_plan",
                            "transformation_cadrage", "transformation_decouvrir", "transformation_proposer",
                            "transformation_feuille_route", "transformation_suivre", "transformation_relier",
                            "hakim_plan_travail"}
    assert not any("statut" in t.input_schema["properties"] or "status" in t.input_schema["properties"]
                   for t in TRANSFO.values())
    kinds = TRANSFO["transformation_proposer"].input_schema["properties"]["elements"]["items"]["properties"]["type"]
    assert kinds["enum"] == list(T.PROPOSABLE_TYPES) and "processus" not in kinds["enum"]   # processus reportés
    assert {t.tool_id for t in TRANSFO.values() if t.read_only} == {"transformation_plans", "transformation_etat",
                                                                     "transformation_suivre"}
    assert all(t.tool_id in hakim.config("m").tool_ids for t in TRANSFO.values())


def _ctx(svc, user=ME, admin=False, sql=None):
    sql = sql or Sql()
    repo = types.SimpleNamespace(sql=sql, s=types.SimpleNamespace(table=lambda n: f"t.{n}", catalog=CAT, schema=SCH))
    ws = types.SimpleNamespace(tables=types.SimpleNamespace(list=lambda catalog_name, schema_name: lister(catalog_name,
                                                                                                          schema_name)))
    plat = Platform(repo, None, user, admin, transformation=svc)
    return ToolContext(sql=sql, workspace=ws, user_email=user, platform=plat), sql


def test_hakim_flow_steps_1_to_3(svc):
    reg, sql = ToolRegistry(hakim.TOOLS), Sql()
    run = lambda tid, **a: reg.run(TRANSFO[tid], _ctx(svc, sql=sql)[0], a)  # noqa: E731  un échange par appel
    pid = run("transformation_creer_plan", nom="IA Gares")["plan_id"]
    assert run("transformation_cadrage", plan=pid, secteur="Gares", objectifs="Informer")["manquant"] == [
        "irritants", "contraintes", "perimetre"]
    d = run("transformation_decouvrir", plan=pid)
    assert [t["table"] for t in d["tables"]] == [FREQ["full_name"], GARES["full_name"]] and d["liens_probables"]
    res = run("transformation_proposer", plan=pid, elements=[{"type": "domaine", "nom": "Gares", "tables": ["data_gares"]}])
    assert len(res["ajoutes"]) == 1
    etat = run("transformation_etat", plan=pid)
    assert etat["elements"]["domaine"][0]["statut"] == "propose" and etat["a_decider"] == 1
    assert [s["statut"] for s in etat["etapes"][:3]] == ["fait", "fait", "en_cours"]
    audits = [p["t"] for s, p in sql.done if "copilot_actions" in s]
    assert audits == ["transformation_creer_plan", "transformation_cadrage", "transformation_decouvrir",
                      "transformation_proposer"]
    assert run("transformation_plans")["plans"][0]["etape_en_cours"] == "Existant (AS-IS)"


def test_one_step_per_exchange(svc):
    reg = ToolRegistry(hakim.TOOLS)
    ctx, sql = _ctx(svc)
    pid = reg.run(TRANSFO["transformation_creer_plan"], ctx, {"nom": "P"})["plan_id"]   # pas une étape
    reg.run(TRANSFO["transformation_cadrage"], ctx, {"plan": pid, "secteur": "Gares"})
    reg.run(TRANSFO["transformation_cadrage"], ctx, {"plan": pid, "objectifs": "Informer"})  # même étape : permis
    with pytest.raises(ToolError, match="une étape par échange"):
        reg.run(TRANSFO["transformation_decouvrir"], ctx, {"plan": pid})
    assert sql.queries == []                                               # découverte non lancée
    nxt, _ = _ctx(svc, sql=sql)                                            # échange suivant
    reg.run(TRANSFO["transformation_decouvrir"], nxt, {"plan": pid})
    with pytest.raises(ToolError, match="Étape 2"):
        reg.run(TRANSFO["transformation_proposer"], nxt, {"plan": pid, "elements": [{"type": "objectif", "nom": "x"}]})
    assert svc.items(pid, ME, False) == []


def test_hakim_tools_respect_ownership(svc):
    pid = svc.create("Plan de A", ME)["plan_id"]
    reg = ToolRegistry(hakim.TOOLS)
    other, _ = _ctx(svc, OTHER)
    with pytest.raises(ToolError, match="introuvable"):
        reg.run(TRANSFO["transformation_etat"], other, {"plan": pid})
    admin, asql = _ctx(svc, ADMIN, admin=True)
    assert reg.run(TRANSFO["transformation_etat"], admin, {"plan": pid})["modifiable"] is False
    with pytest.raises(ToolError, match="propriétaire"):
        reg.run(TRANSFO["transformation_decouvrir"], admin, {"plan": pid})
    assert asql.queries == []                                              # aucune requête lancée
