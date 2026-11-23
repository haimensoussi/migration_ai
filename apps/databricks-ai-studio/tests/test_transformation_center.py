"""EIA Transformation Center, incrément 1 : périmètre choisi, données sensibles, synthèse AS-IS, cartographie,
informations métier, validation d'architecture invalidée par toute modification. Aucune ressource métier créée."""
import json

import pytest

from backend import transformation as T
from tests.test_transformation import CAT, FREQ, GARES, ME, OTHER, SCH, Sql, lister


@pytest.fixture
def svc():
    return T.TransformationService(T.MemoryTransformationStore())


@pytest.fixture
def pid(svc):
    return svc.create("Plan EIA", ME)["plan_id"]


# --- Périmètre ------------------------------------------------------------------------------------------
def test_explicit_selection_overrides_prefix():
    sql = Sql()
    d = T.discover(lister, sql, CAT, SCH, prefix=None, tables=["data_gares"])
    assert [t["table"] for t in d["tables"]] == [GARES["full_name"]]
    assert d["selection"] == {"catalogue": CAT, "schema": SCH, "tables": ["data_gares"], "prefixe": None}
    assert d["perimetre"] == f"{CAT}.{SCH}, 1 table(s) sélectionnée(s)"
    assert not any("data_frequentation" in q for q in sql.queries)          # table non choisie : jamais lue


def test_default_scope_unchanged():
    d = T.discover(lister, Sql(), CAT, SCH)
    assert d["perimetre"] == f"{CAT}.{SCH}, tables data_*" and d["selection"]["prefixe"] == "data_"


def test_too_many_tables_refused_before_any_query():
    sql = Sql()
    with pytest.raises(T.TransformationError, match="au maximum"):
        T.discover(lister, sql, CAT, SCH, max_tables=1)
    assert sql.queries == []


def test_perimeter_saved_and_reused(svc, pid):
    assert T.perimeter_args(svc.get(pid, ME, False)["context"], CAT, SCH) == {
        "catalog": CAT, "schema": SCH, "tables": [], "prefix": "data_"}
    svc.set_perimeter(pid, ME, "maintenance_prd", "gold", ["t1", "t2", "t1"])
    assert T.perimeter_args(svc.get(pid, ME, False)["context"], CAT, SCH) == {
        "catalog": "maintenance_prd", "schema": "gold", "tables": ["t1", "t2"], "prefix": None}


@pytest.mark.parametrize("cat,sch,tables,msg", [("c;drop", "s", ["t"], "invalide"), ("c", "s", ["t`x"], "invalide"),
                                                 ("c", "s", [], "au moins une table"),
                                                 ("c", "s", [f"t{i}" for i in range(T.MAX_TABLES + 1)], "maximum")])
def test_perimeter_rules(svc, pid, cat, sch, tables, msg):
    with pytest.raises(T.TransformationError, match=msg):
        svc.set_perimeter(pid, ME, cat, sch, tables)


def test_perimeter_owner_only(svc, pid):
    with pytest.raises(T.TransformationError, match="propriétaire"):
        svc.set_perimeter(pid, OTHER, CAT, SCH, ["data_gares"])


# --- Données sensibles ----------------------------------------------------------------------------------
def test_sensitive_by_name_and_tag():
    t = {"table": "c.s.agents_rh", "colonnes": [{"nom": n} for n in ("nom_gare", "Email", "date_naissance", "code_uic",
                                                                       "matricule", "telephone_pro")]}
    tags = [{"table_name": "agents_rh", "column_name": "code_uic", "tag_name": "pii", "tag_value": "oui"},
            {"table_name": "autre", "column_name": "x", "tag_name": "pii"}]                  # hors périmètre : ignorée
    got = {s["colonne"]: (s["categorie"], s["source"]) for s in T.sensitive_columns([t], tags)}
    assert "nom_gare" not in got                                                           # « nom » seul : pas un indice
    assert got["Email"] == ("Coordonnées", "nom de colonne")
    assert got["date_naissance"][0] == "Date de naissance" and got["matricule"][0] == "Identifiant personnel"
    assert got["telephone_pro"][0] == "Coordonnées"
    assert got["code_uic"] == ("Étiquette pii = oui", "étiquette Unity Catalog")
    assert all(s["statut"] == "à confirmer" for s in T.sensitive_columns([t], tags))


def test_tags_failure_is_not_blocking():
    def boom(c, s):
        raise RuntimeError("PERMISSION_DENIED information_schema")
    d = T.discover(lister, Sql(), CAT, SCH, tags=boom)
    assert "PERMISSION_DENIED" in d["avertissement_etiquettes"] and len(d["tables"]) == 2


def test_tags_query_is_metadata_only():
    q = T.column_tags_query("maintenance_prd")
    assert q.startswith("SELECT table_name, column_name, tag_name, tag_value FROM `maintenance_prd`.information_schema")
    assert ":schema" in q


# --- Synthèse et cartographie ---------------------------------------------------------------------------
def test_asis_summary_counts():
    d = T.discover(lister, Sql(fail="data_frequentation"), CAT, SCH)
    items = [{"item_type": "domaine", "status": "valide"}, {"item_type": "domaine", "status": "propose"},
             {"item_type": "objectif", "status": "propose"}]
    s = T.asis_summary(d, items)
    assert (s["tables"], s["tables_en_erreur"], s["lignes"], s["colonnes"]) == (1, 1, 100, 3)
    assert s["colonnes_sans_description"] == 1 and s["tables_avec_cle"] == 1 and s["liens"] == 0
    assert (s["domaines_valides"], s["domaines_proposes"], s["objectifs_valides"], s["objectifs_proposes"]) == (1, 1, 0, 1)
    assert T.asis_summary(None) is None


def test_heritage_map_nodes_and_edges():
    dot = T.heritage_dot(T.discover(lister, Sql(), CAT, SCH))
    assert f'"{GARES["full_name"]}"' in dot and f'"{FREQ["full_name"]}"' in dot
    assert f'"{FREQ["full_name"]}" -> "{GARES["full_name"]}"' in dot and "98.0 %" in dot and "style=dashed" in dot


# --- Informations métier -------------------------------------------------------------------------------
def test_business_notes_saved_and_cleared(svc, pid):
    assert svc.set_business_notes(pid, ME, {"c.s.t": "  Référentiel   achats ", "c.s.u": ""}) == {"c.s.t": "Référentiel achats"}
    assert svc.set_business_notes(pid, ME, {}) == {}
    assert "_notes_metier" not in svc.get(pid, ME, False)["context"]


def test_internal_keys_survive_cadrage(svc, pid):
    svc.set_perimeter(pid, ME, CAT, SCH, ["data_gares"])
    svc.set_context(pid, ME, {"secteur": "Supply Chain"})
    ctx = svc.get(pid, ME, False)["context"]
    assert ctx["secteur"] == "Supply Chain" and ctx["_perimetre"]["tables"] == ["data_gares"]


# --- Validation d'architecture --------------------------------------------------------------------------
def _item(pid, iid, kind, name, status, payload=None, at="2026-11-22T10:00:00"):
    return {"plan_id": pid, "item_id": iid, "item_type": kind, "name": name, "status": status, "origin": "hakim",
            "payload": json.dumps(payload or {}), "evidence": json.dumps({}), "created_at": at}


def test_validation_lifecycle(svc, pid):
    with pytest.raises(T.TransformationError, match="Aucun élément de cible"):
        svc.validate_architecture(pid, ME)
    svc.store.insert_items([_item(pid, "ti_1", "cas_usage", "Contrôle commandes", "valide"),
                            _item(pid, "ti_2", "agent", "Agent contrôle", "valide", {"cas_usage": ["Contrôle commandes"]})])
    assert T.validation_state(svc.get(pid, ME, False), svc.items(pid, ME, False))["statut"] == "non_validee"
    with pytest.raises(T.TransformationError, match="propriétaire"):
        svc.validate_architecture(pid, OTHER)
    v = svc.validate_architecture(pid, ME)
    assert v["par"] == ME and T.validation_state(svc.get(pid, ME, False), svc.items(pid, ME, False))["statut"] == "validee"
    # Lier un objet réel (étape 7) ne modifie pas l'architecture
    svc.store.update_payload(pid, "ti_2", json.dumps({"cas_usage": ["Contrôle commandes"],
                                                      "realisation": {"objet_id": "a1"}}))
    assert T.validation_state(svc.get(pid, ME, False), svc.items(pid, ME, False))["statut"] == "validee"
    # Toute modification de l'architecture rend la validation obsolète
    svc.store.insert_items([_item(pid, "ti_3", "outil", "Profiler", "propose", {"cas_usage": ["Contrôle commandes"]},
                                  at="2026-11-22T10:05:00")])
    assert T.validation_state(svc.get(pid, ME, False), svc.items(pid, ME, False))["statut"] == "obsolete"


# --- AI Opportunities (incrément 2) --------------------------------------------------------------------
@pytest.fixture
def opid(svc):
    p = svc.create("Plan opportunités", ME)["plan_id"]
    svc.set_discovery(p, ME, T.discover(lister, Sql(), CAT, SCH))
    svc.propose(p, ME, [{"type": "domaine", "nom": "Gares", "tables": ["data_gares"]}])
    svc.decide(p, svc.items(p, ME, False)[0]["item_id"], ME, "valide")
    return p


def _opp(**kw):
    return {"type": "cas_usage", "nom": "Prévision fréquentation", "tables": ["data_frequentation"], **kw}


@pytest.mark.parametrize("v,f,c,expected", [("fort", "fort", "faible", "haute"), ("fort", "moyen", "moyen", "haute"),
                                             ("fort", "fort", "fort", "moyenne"), ("moyen", "fort", "faible", "moyenne"),
                                             ("faible", "fort", "faible", "basse"), ("fort", "faible", "faible", "basse"),
                                             ("fort", None, "faible", None)])
def test_priority_rule(v, f, c, expected):
    assert T.opportunity_priority(v, f, c) == expected


def test_opportunity_fields_stored_and_listed(svc, opid):
    svc.propose(opid, ME, [_opp(domaine="gares", categorie="assistant", solution_ia="Assistant de prévision",
                                gain_attendu="Anticiper l'affluence", valeur="fort", faisabilite="moyen",
                                complexite="faible")])
    [o] = T.opportunities(svc.items(opid, ME, False))
    assert o["domaine"] == "Gares"                                   # nom du domaine validé
    assert (o["categorie"], o["solution_ia"], o["valeur_metier"]) == ("assistant", "Assistant de prévision",
                                                                       "Anticiper l'affluence")
    assert (o["priorite"], o["priorite_source"], o["statut"]) == ("haute", "calculée", "propose")
    assert o["tables"] == [FREQ["full_name"]]


def test_unrated_opportunity_has_no_guessed_priority(svc, opid):
    svc.propose(opid, ME, [_opp()])
    [o] = T.opportunities(svc.items(opid, ME, False))
    assert o["priorite"] is None and o["priorite_source"] is None and o["categorie"] is None


@pytest.mark.parametrize("kw,msg", [({"domaine": "Fret"}, "non validé"), ({"categorie": "robot"}, "categorie"),
                                    ({"faisabilite": "élevée"}, "faisabilite"), ({"priorite": "urgente"}, "priorite")])
def test_opportunity_values_controlled(svc, opid, kw, msg):
    with pytest.raises(T.TransformationError, match=msg):
        svc.propose(opid, ME, [_opp(**kw)])


def test_edit_keeps_status_traces_and_invalidates_architecture(svc, opid):
    svc.propose(opid, ME, [_opp(valeur="moyen", faisabilite="fort", complexite="faible")])
    oid = next(i["item_id"] for i in svc.items(opid, ME, False) if i["item_type"] == "cas_usage")
    svc.decide(opid, oid, ME, "valide")
    svc.store.insert_items([_item(opid, "ti_ag", "agent", "Agent prévision", "valide",
                                  {"cas_usage": ["Prévision fréquentation"]}, at="2026-11-22T11:00:00")])
    svc.validate_architecture(opid, ME)
    svc.update_opportunity(opid, ME, oid, {"priorite": "basse", "tables": ["data_gares", "data_frequentation"],
                                           "categorie": "workflow"})
    items = svc.items(opid, ME, False)
    o = next(x for x in T.opportunities(items) if x["item_id"] == oid)
    assert (o["statut"], o["priorite"], o["priorite_source"], o["modifie_par"]) == ("valide", "basse", "forcée", ME)
    assert o["tables"] == [GARES["full_name"], FREQ["full_name"]] and o["categorie"] == "workflow"
    assert T.validation_state(svc.get(opid, ME, False), items)["statut"] == "obsolete"
    svc.update_opportunity(opid, ME, oid, {"priorite": ""})                 # retour à la priorité calculée
    o = next(x for x in T.opportunities(svc.items(opid, ME, False)) if x["item_id"] == oid)
    assert (o["priorite"], o["priorite_source"]) == ("moyenne", "calculée")


@pytest.mark.parametrize("fields,msg", [({"tables": []}, "au moins une table"), ({"tables": ["inconnue"]}, "absente"),
                                        ({"nom": "x"}, "non modifiables"), ({"domaine": "Fret"}, "non validé")])
def test_edit_rules(svc, opid, fields, msg):
    svc.propose(opid, ME, [_opp()])
    oid = next(i["item_id"] for i in svc.items(opid, ME, False) if i["item_type"] == "cas_usage")
    with pytest.raises(T.TransformationError, match=msg):
        svc.update_opportunity(opid, ME, oid, fields)


def test_edit_owner_only_and_only_use_cases(svc, opid):
    dom_id = svc.items(opid, ME, False)[0]["item_id"]
    with pytest.raises(T.TransformationError, match="introuvable"):
        svc.update_opportunity(opid, ME, dom_id, {"description": "x"})
    svc.propose(opid, ME, [_opp()])
    oid = next(i["item_id"] for i in svc.items(opid, ME, False) if i["item_type"] == "cas_usage")
    with pytest.raises(T.TransformationError, match="propriétaire"):
        svc.update_opportunity(opid, OTHER, oid, {"description": "x"})


def test_user_added_opportunity_and_bulk_reject(svc, opid):
    svc.propose(opid, ME, [_opp(), _opp(nom="Qualité référentiel gares", tables=["data_gares"])], origin="utilisateur")
    ops = T.opportunities(svc.items(opid, ME, False))
    assert {o["origine"] for o in ops} == {"utilisateur"} and all(o["statut"] == "propose" for o in ops)
    assert svc.decide_many(opid, ME, [o["item_id"] for o in ops], "rejete") == 2
    assert all(o["statut"] == "rejete" for o in T.opportunities(svc.items(opid, ME, False)))


def test_hakim_schema_exposes_opportunity_fields():
    from backend import hakim
    spec = next(t for t in hakim.TOOLS if t.tool_id == "transformation_proposer")
    props = spec.input_schema["properties"]["elements"]["items"]["properties"]
    assert props["categorie"]["enum"] == list(T.OPPORTUNITY_CATEGORIES)
    assert all(props[k]["enum"] == list(T.LEVELS) for k in ("valeur", "faisabilite", "complexite"))
    assert "priorite" not in props                                        # calculée par la page, forcée par l'humain


def test_incoherent_architecture_not_validated(svc, pid):
    svc.store.insert_items([_item(pid, "ti_1", "cas_usage", "Cas", "rejete"),
                            _item(pid, "ti_2", "agent", "Agent", "valide", {"cas_usage": ["Cas"]})])
    with pytest.raises(T.TransformationError, match="incohérente"):
        svc.validate_architecture(pid, ME)
