"""Enterprise Architect (AG10) : Data Mesh, Agent Mesh, optimisation, persistance et déploiement (AG09)."""
import importlib.util
import pathlib

import pytest

from backend.eia import mesh_architect as ma
from backend.eia import org_designer as od
from backend.eia import store as es
from backend.eia.contracts import ContractError
from backend import teams as T

_spec = importlib.util.spec_from_file_location("t_org", pathlib.Path(__file__).with_name("test_eia_org.py"))
t_org = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t_org)
USER = "marie.durand@sncf.fr"
S = "dataops_dev.ai_studio."


def table(name, status=True):
    cols = [{"nom": "id", "type": "string"}, {"nom": "created_at", "type": "date"}]
    if status:
        cols.append({"nom": "status", "type": "string"})
    return {"table": S + name, "lignes": 10, "colonnes": cols}


def link(a, b, col):
    return {"de": f"{S}{a}.{col}", "vers": f"{S}{b}.{col}"}


SALES = ["data_sales_opportunities", "data_sales_orders", "data_sales_order_items", "data_sales_representatives",
         "data_sales_targets", "data_customers", "data_products"]
MKT = ["data_marketing_campaigns", "data_campaign_results", "data_customer_interactions"]
SALES_LINKS = [link("data_sales_opportunities", "data_customers", "customer_id"),
               link("data_sales_opportunities", "data_sales_representatives", "rep_id"),
               link("data_sales_order_items", "data_products", "product_id"),
               link("data_sales_order_items", "data_sales_orders", "order_id"),
               link("data_sales_orders", "data_customers", "customer_id"),
               link("data_sales_orders", "data_sales_representatives", "rep_id"),
               link("data_sales_targets", "data_sales_representatives", "rep_id")]
MKT_LINKS = [link("data_campaign_results", "data_marketing_campaigns", "campaign_id"),
             link("data_customer_interactions", "data_customers", "customer_id"),
             link("data_customer_interactions", "data_sales_opportunities", "opportunity_id"),
             link("data_customer_interactions", "data_sales_representatives", "rep_id"),
             link("data_sales_opportunities", "data_marketing_campaigns", "campaign_id")]


def disc(tables, links):
    return {"tables": [table(t, status=t != "data_sales_targets") for t in tables], "liens_probables": links}


def cands(tables, previsible=True):
    return [{"id": f"nb_{t[5:]}", "table": S + t, "previsible": previsible} for t in tables]


def sales():
    d = disc(SALES, SALES_LINKS)
    return d, cands(SALES)


def enterprise():
    d = disc(SALES + MKT, SALES_LINKS + MKT_LINKS)
    return d, cands(SALES + MKT)


# ---------------------------------------------------------------- Data Mesh
def test_connected_sales_data_gives_a_single_justified_domain():
    d, c = sales()
    m = ma.propose_mesh(d, c, "Horizon")
    [dom] = m["domaines"]
    assert dom["nom"] == "Ventes" and sorted(dom["tables"]) == sorted(S + t for t in SALES)
    assert "Un seul domaine" in m["justification"][0] and not m["dependances"]
    subs = {s["nom"]: [ma._short(t) for t in s["tables"]] for s in dom["sous_domaines"]}
    assert subs["Commandes"] == ["data_sales_orders", "data_sales_order_items"]
    assert {"Clients", "Produits", "Opportunités", "Force de vente", "Objectifs"} <= set(subs)
    assert all(p["proprietaire"].startswith("à désigner") for p in dom["data_products"])
    assert len(dom["data_products"]) == len(dom["sous_domaines"])


def test_enterprise_splits_into_domains_with_dependencies():
    d, c = enterprise()
    m = ma.propose_mesh(d, c, "Horizon")
    by = {x["nom"]: {ma._short(t) for t in x["tables"]} for x in m["domaines"]}
    assert len(by) == 2 and by["Campagnes"] == {"data_campaign_results", "data_marketing_campaigns"}
    assert "data_customer_interactions" in by["Ventes"]
    [dep] = m["dependances"]
    assert (dep["de"], dep["vers"]) == ("ventes", "campagnes")
    prod = next(p for x in m["domaines"] for p in x["data_products"] if p["id"] == dep["data_product"])
    assert prod["consommateurs"] == ["ventes"]
    assert sum(len(x["tables"]) for x in m["domaines"]) == len(SALES + MKT)       # chaque table une seule fois


def test_small_table_without_kpi_is_not_a_domain_of_its_own():
    d = disc(["data_sales_orders", "data_sales_order_items", "data_meteo"], [link("data_sales_order_items", "data_sales_orders", "order_id")])
    m = ma.propose_mesh(d, cands(["data_sales_orders"]))
    assert len(m["domaines"]) == 1 and any("fragmentation" in j for j in m["justification"])


def test_user_edits_move_rename_merge():
    d, c = enterprise()
    m = ma.propose_mesh(d, c, "Horizon")
    m2 = ma.move_table(m, d, c, S + "data_customer_interactions", "campagnes")
    assert S + "data_customer_interactions" in next(x for x in m2["domaines"] if x["cle"] == "campagnes")["tables"]
    m3 = ma.rename_domain(m2, d, c, "campagnes", "Marketing")
    assert {x["nom"] for x in m3["domaines"]} == {"Marketing", "Ventes"}
    with pytest.raises(ma.MeshError):
        ma.rename_domain(m3, d, c, "campagnes", "ventes")
    m4 = ma.move_table(m3, d, c, S + "data_products", "Catalogue produits")
    assert len(m4["domaines"]) == 3 and any(x["nom"] == "Catalogue produits" for x in m4["domaines"])
    m5 = ma.merge_domains(m4, d, c, "ventes", "campagnes")
    assert [x["cle"] for x in m5["domaines"]].count("campagnes") == 0 and len(m5["domaines"]) == 2
    assert any("utilisateur" in j for j in m5["justification"])
    with pytest.raises(ma.MeshError):
        ma.build_mesh(d, c, {S + "data_sales_orders": "x"}, {"x": "X"}, [])       # tables sans domaine


def test_insights_detect_entities_processes_and_opportunities():
    d, c = sales()
    i = ma.insights(d, c)
    assert len(i["entites"]) == len(SALES) and i["kpis_previsibles"] == len(SALES)
    assert any("non-atteinte des objectifs" in x["opportunite"] for x in i["opportunites_ia"])
    assert all(x["statut"] == "à valider" for x in i["opportunites_ia"] + i["opportunites_automatisation"])
    assert not any(x["table"] == S + "data_sales_targets" for x in i["opportunites_automatisation"])  # pas de statut


# ---------------------------------------------------------------- Agent Mesh + optimisation
def test_single_domain_eia_covers_cycle_without_duplicates():
    d, c = sales()
    a = ma.design_eia(ma.propose_mesh(d, c, "Horizon"))
    [e] = a["equipes"]
    cats = [a["agents"][k]["categorie"] for k in e["membres"]]
    assert cats == ["AG01", "AG02", "AG03", "AG04", "AG05", "AG08"] and len(set(cats)) == len(cats)
    assert not a["optimisation"]["mutualises"] and a["optimisation"]["economie_agents"] == 0
    [v] = a["domaines"]
    assert [s["etape"] for s in v["cycle"]][-3:] == ["DÉCIDER", "EXÉCUTER", "APPRENDRE"] and all(s["couvert"] for s in v["cycle"])
    assert {"de": a["agents"][e["membres"][3]]["cle"], "vers": a["agents"][e["membres"][4]]["cle"],
            "objet": "résultats"} in v["flux"]
    assert all(a["agents"][k]["autonomie"] for k in e["membres"]) and a["validations_humaines"]


def test_multi_domain_mutualises_transverse_capabilities():
    d, c = enterprise()
    a = ma.design_eia(ma.propose_mesh(d, c, "Horizon"))
    o = a["optimisation"]
    assert len(a["equipes"]) == 2 and o["agents_sans_optimisation"] == 12 and o["agents_optimises"] == 7
    assert sorted(o["mutualises"]) == ["ag02", "ag03", "ag04", "ag05", "ag08"]
    for k in o["mutualises"]:
        assert a["agents"][k]["mutualise"] and len(a["agents"][k]["equipes"]) == 2
    ag01 = [k for k, x in a["agents"].items() if x["categorie"] == "AG01"]
    assert len(ag01) == 2 and all(not a["agents"][k]["mutualise"] for k in ag01)       # spécifique par domaine
    assert all(len(e["membres"]) <= T.MAX_MEMBERS for e in a["equipes"])
    assert [(x["de"], x["vers"]) for x in a["interactions"]] == [("equipe-ventes", "equipe-campagnes")]
    caps = {x["capacite"]: x["decision"] for x in o["capacites"]}
    assert caps["Simulation & What-if"] == "portée par AG03" and caps["Knowledge & Context"] == "à venir"
    handles = [x["handle"] for x in a["agents"].values()] + [h for e in a["equipes"] for h in (e["handle"], e["chef_handle"])]
    assert len(set(handles)) == len(handles) and all(len(h) <= 20 for h in handles)


def test_mutualisation_can_be_disabled_and_needs_drive_instantiation():
    d, c = enterprise()
    m = ma.propose_mesh(d, c, "Horizon")
    a = ma.design_eia(m, mutualiser=[])
    assert a["optimisation"]["agents_optimises"] == 12 and not a["optimisation"]["mutualises"]
    d2, _ = sales()
    a2 = ma.design_eia(ma.propose_mesh(d2, []))                     # aucun KPI : seulement capter et contrôler
    assert sorted(x["categorie"] for x in a2["agents"].values()) == ["AG01", "AG08"]
    assert any(not s["couvert"] and s["motif"] for s in a2["domaines"][0]["cycle"])
    with pytest.raises(ma.MeshError):
        ma.design_eia(m, filiere="Inconnue")


def test_published_agent_is_reused_not_recreated():
    d, c = sales()
    m = ma.propose_mesh(d, c, "Horizon")
    existing = [{"agent_id": "pub1", "name": "Gouvernance", "handle": "gouv-ventes", "status": "publie",
                 "category": "Monitoring & Governance Agent", "knowledge_tables": [S + t for t in SALES]},
                {"agent_id": "brou", "name": "Analyse", "handle": "x", "status": "brouillon",
                 "category": "Data Intelligence Agent", "knowledge_tables": [S + t for t in SALES]}]
    a = ma.design_eia(m, existing=existing)
    assert a["optimisation"]["reutilises"] == ["ag08-ventes"]
    fa = t_org.FakeAgents([{"agent_id": "pub1", "name": "Gouvernance", "handle": "gouv-ventes", "status": "publie",
                            "tool_ids": []}])
    ft = t_org.FakeTeams(fa)
    r = od.deploy(a, list(a["agents"]), fa, ft, USER)
    assert r["statut"] == "brouillon" and len(fa.created) == 6                   # 5 agents + 1 chef, AG08 réutilisé
    [(team, _, _)] = ft.saved
    assert "pub1" in team["members"]


# ---------------------------------------------------------------- organigrammes
def test_org_charts_views_and_statuses():
    d, c = enterprise()
    m = ma.propose_mesh(d, c, "Horizon")
    a = ma.design_eia(m)
    g = ma.mesh_dot(m)
    assert g.count("{") == g.count("}") and "consomme" in g and "Data product" in g
    assert "Campagnes" not in ma.mesh_dot(m, focus="ventes").split("consomme")[0].split("n_d_ventes")[0]
    glob = ma.eia_dot(a)
    assert "cluster_factory" in glob and "cluster_shared" in glob and "hakim -> n_d_ventes;" in glob
    assert "dépend de" in glob and glob.count("{") == glob.count("}")
    team = ma.eia_dot(a, "equipe-campagnes")
    assert "n_c_equipe-campagnes".replace("-", "_") in team and "n_c_equipe_ventes" not in team
    st = ma.statuses(a, ["ag01-ventes"])
    assert st["ag01-ventes"] == "a_deployer" and st["ag02"] == "exclu" and st["equipe-campagnes"] == "exclu"


# ---------------------------------------------------------------- persistance et déploiement
def test_architecture_lifecycle_requires_human_validation_in_order():
    d, c = enterprise()
    m = ma.propose_mesh(d, c, "Horizon")
    repo = es.EiaRepository(es.MemoryEiaStore())
    aid = repo.save_architecture("p1", "Horizon", m, USER)
    with pytest.raises(ContractError):
        repo.set_architecture_status(aid, "eia_valide", USER)                    # pas de saut d'étape
    with pytest.raises(ContractError):
        repo.save_architecture("p1", "x", m, "agent:hakim")
    repo.set_architecture_status(aid, "mesh_valide", USER)
    with pytest.raises(ContractError):
        repo.update_architecture(aid, "mesh", m, USER)                          # découpage figé après validation
    with pytest.raises(ContractError):
        repo.set_architecture_status(aid, "eia_valide", USER)                    # EIA vide
    a = ma.design_eia(m)
    repo.update_architecture(aid, "eia", a, USER)
    repo.set_architecture_status(aid, "eia_valide", USER)
    with pytest.raises(ContractError):
        repo.set_architecture_status(aid, "deployee", USER)                      # rien de déployé
    fa = t_org.FakeAgents()
    ft = t_org.FakeTeams(fa)
    r = od.deploy(a, list(a["agents"]), fa, ft, USER)
    checks = ma.verify(a, r, fa.rows, ft.rows)
    assert r["statut"] == "brouillon" and len(r["agents"]) == 9 and all(x["ok"] for x in checks)
    repo.update_architecture(aid, "deployment", {**r, "controles": checks}, USER)
    repo.set_architecture_status(aid, "deployee", USER)
    cur = repo.current_architecture("p1")
    assert cur["status"] == "deployee" and cur["eia"]["optimisation"]["agents_optimises"] == 7
    assert set(ma.statuses(cur["eia"], None, cur["deployment"]).values()) == {"brouillon"}
    assert [s["statut"] for s in ma.stages({"discovery": d}, cur)] == ["fait"] * 4


def test_verify_detects_broken_delegation():
    d, c = sales()
    a = ma.design_eia(ma.propose_mesh(d, c))
    fa = t_org.FakeAgents()
    ft = t_org.FakeTeams(fa)
    r = od.deploy(a, list(a["agents"]), fa, ft, USER)
    rows = [x for x in fa.rows if x["agent_id"] != r["agents"][0]["agent_id"]]          # un membre supprimé
    bad = [x for x in ma.verify(a, r, rows, ft.rows) if not x["ok"]]
    assert any("joignables" in x["controle"] for x in bad) and any("présent" in x["controle"] for x in bad)
