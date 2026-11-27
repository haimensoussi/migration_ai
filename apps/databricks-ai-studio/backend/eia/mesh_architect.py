"""Enterprise Architect (AG10) : Data Mesh Architect, Agent Mesh Architect, Enterprise Architecture Optimizer.

Démarche : Data Discovery -> Data Mesh Architecture -> EIA Architecture -> Deployment.

- insights() : lecture AG10 de la découverte (entités, processus, KPI, opportunités IA et d'automatisation).
- propose_mesh() / build_mesh() : domaines métier en nombre optimal (aucun nombre imposé), sous-domaines, data
  products, dépendances et justification. Un seul domaine si les données forment un ensemble relié.
- move_table() / rename_domain() / merge_domains() : modifications de l'utilisateur avant validation.
- design_eia() : une EIA par domaine (cycle CAPTER -> APPRENDRE, autonomie, validations humaines), puis optimisation
  globale (mutualisation des capacités transverses, réutilisation d'agents publiés, rapport avant / après).
  Le résultat est compatible avec org_designer.deploy (construction AG09 après validation humaine).
- mesh_dot() / eia_dot() : organigrammes Graphviz au style DISCOVERY (vues entreprise, domaine, équipe).
- verify() : contrôle des interactions après déploiement (chefs -> membres, agents présents).

Aucune fonction de ce module ne lit ni n'écrit de table : tout part de la découverte et des KPI candidats. Les
découpages, noms et responsables sont des propositions « à valider » ; aucun seuil n'est inventé.
"""
from __future__ import annotations

import re
from typing import Any

from backend import teams as T
from backend.eia import agent_models as am
from backend.eia import org_designer as od


class MeshError(ValueError):
    pass


PREFIX = 5          # deux mots égaux sur leurs 5 premières lettres sont considérés identiques (order / orders)
STOP = {"data", "demo", "dim", "fact", "fct", "stg", "raw", "bronze", "silver", "gold", "tbl", "vw", "v", "t"}
GENERIC = {"id", "item", "items", "result", "results", "daily", "monthly", "mensuel", "mensuelle", "history",
           "historique", "log", "logs", "detail", "details", "line", "lines", "ligne", "lignes", "pred"}
LABELS = {"sales": "Ventes", "sale": "Ventes", "vente": "Ventes", "ventes": "Ventes", "order": "Commandes",
          "orders": "Commandes", "commandes": "Commandes", "opportunities": "Opportunités",
          "opportunity": "Opportunités", "representatives": "Force de vente", "representative": "Force de vente",
          "reps": "Force de vente", "targets": "Objectifs", "target": "Objectifs", "customers": "Clients",
          "customer": "Clients", "clients": "Clients", "products": "Produits", "product": "Produits",
          "marketing": "Marketing", "campaign": "Campagnes", "campaigns": "Campagnes",
          "interactions": "Interactions clients", "suppliers": "Fournisseurs", "fournisseurs": "Fournisseurs",
          "sc": "Supply Chain", "gares": "Gares", "frequentation": "Fréquentation", "maintenance": "Maintenance",
          "rames": "Matériel roulant", "ponctualite": "Ponctualité", "regularite": "Régularité"}
STATUS_COLS = ("status", "statut", "stage", "etat", "state", "etape")
DATE_TYPES = ("date", "timestamp")

SHAREABLE = ("AG02", "AG03", "AG04", "AG05", "AG08")          # AG01 reste spécifique à chaque domaine
CYCLE = (("CAPTER", "AG01"), ("COMPRENDRE", "AG01"), ("PRÉDIRE", "AG02"), ("ARBITRER", "AG03"),
         ("DÉCIDER", "HUMAIN"), ("EXÉCUTER", "AG04"), ("APPRENDRE", "AG05"))
AUTONOMIE = {
    "AG01": "Autonome en lecture : capte, analyse, détecte les ruptures et alerte",
    "AG02": "Autonome en calcul : prévisions publiées avec fiabilité mesurée (backtest)",
    "AG03": "Propose et priorise ; la décision reste humaine",
    "AG04": "Exécute uniquement des missions validées par un humain",
    "AG05": "Mesure l'efficacité et propose des améliorations ; validation humaine",
    "AG06": "Coordonne et délègue ; aucune décision métier",
    "AG08": "Contrôles de passage bloquants (qualité, conformité, traçabilité)",
}
VALIDATIONS = ("Validation du découpage Data Mesh (domaines, data products, responsables)",
               "Validation de l'architecture EIA avant toute construction",
               "Décision sur chaque recommandation d'AG03 (DÉCIDER)",
               "Validation de chaque mission avant exécution par AG04",
               "Validation des règles, seuils et améliorations proposés par AG05",
               "Publication des agents et équipes par un administrateur")
CAPACITES = (
    ("Data Intelligence", "AG01", "Spécifique à chaque domaine : connaissance des données et du métier du domaine."),
    ("Predictive Intelligence", "AG02", "Mutualisable : méthodes de prévision génériques, fiabilité mesurée par KPI."),
    ("Strategic Intelligence", "AG03", "Mutualisable : un seul arbitrage entre domaines, pas de recommandations "
                                       "contradictoires."),
    ("Simulation & What-if", "AG03", "Portée par Strategic Intelligence (Simulation & Scenario, ancien AG11, "
                                     "retiré) ; pas d'agent dédié."),
    ("Alerting & Notification", "AG01", "Rôle alerting d'AG01 et page Notifications ; pas d'agent dédié."),
    ("Execution & Automation", "AG04", "Mutualisable : exécution des seules missions validées."),
    ("Knowledge & Context", "AG07", "Modèle squelette : à venir, mutualisé dès sa disponibilité."),
    ("Learning & Improvement", "AG05", "Mutualisable : mesure d'efficacité commune à tous les domaines."),
    ("Governance & Control", "AG08", "Mutualisable : contrôles et traçabilité globaux sous HAKIM."),
)


# ---------------------------------------------------------------- outils
def _short(table: str) -> str:
    return str(table).rsplit(".", 1)[-1]


def tokens(table: str) -> list[str]:
    """Mots métier d'un nom de table (préfixes techniques et mots génériques retirés)."""
    out = [w for w in re.split(r"[^a-z0-9]+", _short(table).lower()) if w and not w.isdigit()]
    return [w for w in out if w not in STOP and w not in GENERIC]


def _same(a: str, b: str) -> bool:
    return a[:PREFIX] == b[:PREFIX]


def _overlap(a: list[str], b: list[str]) -> bool:
    return any(_same(x, y) for x in a for y in b)


def label(word: str) -> str:
    for k, v in LABELS.items():
        if _same(k, word):
            return v
    return word.replace("_", " ").capitalize()


def _link_tables(link: dict) -> tuple[str, str]:
    a, b = (str(link.get(k) or "").rsplit(".", 1)[0] for k in ("de", "vers"))
    return a, b


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", od._ascii(name).lower()).strip("-")[:30] or "domaine"


# ---------------------------------------------------------------- Data Discovery (lecture AG10)
def insights(discovery: dict, candidates: list[dict]) -> dict:
    """Entités, processus, KPI et opportunités déduits de la structure (indices « à valider », aucune lecture)."""
    tables = [t for t in discovery.get("tables") or [] if "erreur" not in t]
    links = discovery.get("liens_probables") or []
    inbound: dict[str, int] = {}
    for l in links:
        a, b = _link_tables(l)
        if a != b:
            inbound[b] = inbound.get(b, 0) + 1
    by_table: dict[str, list[dict]] = {}
    for k in candidates or []:
        by_table.setdefault(k["table"], []).append(k)
    entites, processus, ia, auto = [], [], [], []
    for t in tables:
        name, cols = t["table"], t.get("colonnes") or []
        ent = label(tokens(name)[-1]) if tokens(name) else _short(name)
        dates = [c["nom"] for c in cols if str(c.get("type", "")).lower().startswith(DATE_TYPES)]
        status = [c["nom"] for c in cols if any(c["nom"].lower() == s or c["nom"].lower().endswith("_" + s)
                                                for s in STATUS_COLS)]
        kind = "référentiel" if inbound.get(name, 0) >= 1 and not status else "transaction" if dates else "référentiel"
        entites.append({"table": name, "entite": ent, "nature": kind, "references_entrantes": inbound.get(name, 0)})
        if dates and status:
            processus.append({"table": name, "processus": f"Cycle de vie : {ent}", "etapes": status, "dates": dates})
            auto.append({"table": name, "opportunite": f"Suivi et relances automatiques ({ent}) selon {status[0]}",
                         "type": "automatisation", "statut": "à valider"})
        prev = [k["id"] for k in by_table.get(name, []) if k.get("previsible")]
        if prev:
            ia.append({"table": name, "opportunite": f"Prévoir {len(prev)} KPI ({ent})", "type": "prédiction",
                       "kpis": prev, "statut": "à valider"})
        if any(_same(w, "target") or _same(w, "objectif") for w in tokens(name)) and by_table.get(name):
            ia.append({"table": name, "opportunite": "Détecter le risque de non-atteinte des objectifs (réalisé et "
                                                     "prévu comparés aux objectifs)", "type": "alerte prédictive",
                       "kpis": [k["id"] for k in by_table[name]], "statut": "à valider"})
    return {"entites": entites, "processus": processus, "kpis": len(candidates or []),
            "kpis_previsibles": sum(1 for k in candidates or [] if k.get("previsible")), "opportunites_ia": ia,
            "opportunites_automatisation": auto,
            "avertissement": "Indices déduits des noms, types et liens de colonnes : à valider par le métier."}


# ---------------------------------------------------------------- Data Mesh Architect
def propose_mesh(discovery: dict, candidates: list[dict], enterprise: str = "Entreprise") -> dict:
    """Découpage proposé : liens de données, puis vocabulaire métier commun, référentiels rattachés à leur principal
    utilisateur, petits ensembles rattachés (pas de fragmentation). Le nombre de domaines n'est pas imposé."""
    tables = [t["table"] for t in discovery.get("tables") or [] if "erreur" not in t]
    if not tables:
        raise MeshError("Aucune table découverte : découpage impossible.")
    links = [(a, b) for a, b in (_link_tables(l) for l in discovery.get("liens_probables") or [])
             if a in tables and b in tables and a != b]
    why: list[str] = []
    inbound = {t: {a for a, b in links if b == t} for t in tables}
    outbound = {t: {b for a, b in links if a == t} for t in tables}
    hubs = [t for t in tables if len(inbound[t]) >= 2 and not outbound[t]]
    core = [t for t in tables if t not in hubs] or list(tables)
    hubs = [t for t in hubs if t not in core]

    parent = {t: t for t in core}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in links:
        if a in parent and b in parent and find(a) != find(b):
            parent[find(a)] = find(b)
    if any(a in parent and b in parent for a, b in links):
        why.append("Tables reliées par des liens de données (clés communes) regroupées dans le même domaine.")
    comps = lambda: {r: [t for t in core if find(t) == r] for r in {find(t) for t in core}}  # noqa: E731
    merged = True
    while merged:                                   # vocabulaire métier commun (ex. sales_*)
        merged = False
        groups = list(comps().values())
        for i, g1 in enumerate(groups):
            for g2 in groups[i + 1:]:
                w1 = [w for t in g1 for w in tokens(t)[:1]]
                w2 = [w for t in g2 for w in tokens(t)[:1]]
                if _overlap(w1, w2):
                    parent[find(g2[0])] = find(g1[0])
                    common = next(x for x in w1 if any(_same(x, y) for y in w2))
                    why.append(f"{', '.join(_short(t) for t in g2)} rejoint {', '.join(_short(t) for t in g1)} : "
                               f"vocabulaire métier commun « {common} ».")
                    merged = True
                    break
            if merged:
                break
    assign = {t: find(t) for t in core}
    for h in hubs:                                   # référentiels partagés : rattachés à leur principal utilisateur
        counts: dict[str, int] = {}
        for a in inbound[h]:
            if a in assign:
                counts[assign[a]] = counts.get(assign[a], 0) + 1
        size = {r: sum(1 for v in assign.values() if v == r) for r in set(assign.values())}
        vocab = [r for r in counts if _overlap(tokens(h), [w for t, v in assign.items() if v == r for w in tokens(t)])]
        pool = vocab or list(counts)
        owner = max(pool, key=lambda r: (counts[r], -size[r])) if pool else next(iter(size))
        assign[h] = owner
        users = len(counts)
        why.append(f"Référentiel {_short(h)} ({len(inbound[h])} références) rattaché au domaine "
                   + ("de même vocabulaire métier" if vocab else "qui l'utilise le plus")
                   + (" ; les autres domaines en dépendent." if users > 1 else "."))
    while True:                                      # pas de domaine d'une seule table sans KPI
        size = {r: [t for t, v in assign.items() if v == r] for r in set(assign.values())}
        kp = {k["table"] for k in candidates or []}
        small = next((r for r, ts in size.items() if len(size) > 1 and len(ts) == 1 and ts[0] not in kp), None)
        if not small:
            break
        t = size[small][0]
        near = [assign[b] for a, b in links if a == t and assign[b] != small] + \
               [assign[a] for a, b in links if b == t and assign[a] != small]
        target = max(set(near), key=near.count) if near else max((r for r in size if r != small),
                                                                 key=lambda r: len(size[r]))
        assign[t] = target
        why.append(f"{_short(t)} (une table, sans KPI) rattachée à un domaine existant : éviter la fragmentation.")
    roots = sorted(set(assign.values()), key=lambda r: tables.index(min((t for t in tables if assign[t] == r),
                                                                        key=tables.index)))
    names, keys = {}, {}
    for r in roots:
        members = [t for t in tables if assign[t] == r and t not in hubs] or [t for t in tables if assign[t] == r]
        words = [w for t in members for w in tokens(t)[:1]]
        top = max(words, key=lambda w: sum(_same(w, x) for x in words)) if words else _short(members[0])
        name = label(top)
        base, i = _key(name), 2
        k = base
        while k in keys.values():
            k, i = f"{base}-{i}", i + 1
        keys[r], names[k] = k, name
    n = len(roots)
    why.insert(0, "Un seul domaine : les données forment un ensemble relié ; plusieurs domaines seraient une "
                  "fragmentation sans bénéfice." if n == 1 else
               f"{n} domaines : ensembles de données sans liens directs ni vocabulaire métier commun.")
    return build_mesh(discovery, candidates, {t: keys[assign[t]] for t in tables}, names, why, enterprise, auto=True)


def build_mesh(discovery: dict, candidates: list[dict], assignment: dict, names: dict, justification: list[str],
               enterprise: str = "Entreprise", auto: bool = False) -> dict:
    """Domaines, sous-domaines, data products et dépendances à partir d'une affectation table -> domaine."""
    tables = [t["table"] for t in discovery.get("tables") or [] if "erreur" not in t]
    unknown = sorted(set(assignment) - set(tables))
    if unknown:
        raise MeshError("Tables hors découverte : " + ", ".join(unknown))
    missing = [t for t in tables if t not in assignment]
    if missing:
        raise MeshError("Tables sans domaine : " + ", ".join(_short(t) for t in missing))
    links = [(a, b, l) for l in discovery.get("liens_probables") or [] for a, b in [_link_tables(l)]
             if a in assignment and b in assignment and a != b]
    kp: dict[str, list[dict]] = {}
    for k in candidates or []:
        kp.setdefault(k["table"], []).append(k)
    inbound = {t: sum(1 for a, b, _ in links if b == t) for t in tables}
    order = []
    for t in tables:
        if assignment[t] not in order:
            order.append(assignment[t])
    domaines, product_of = [], {}
    for key in order:
        mine = [t for t in tables if assignment[t] == key]
        dom_words = [w for t in mine for w in tokens(t)[:1]]
        main = max(dom_words, key=lambda w: sum(_same(w, x) for x in dom_words)) if dom_words else ""
        subs: dict[str, list[str]] = {}
        for t in mine:
            words = [w for w in tokens(t) if not (main and _same(w, main) and len(tokens(t)) > 1)] or tokens(t) or [_short(t)]
            ent = words[0]
            sk = next((s for s in subs if _same(s, ent)), ent)
            subs.setdefault(sk, []).append(t)
        sous, products = [], []
        for sk, ts in subs.items():
            ref = all(inbound[t] >= 1 and not kp.get(t) or inbound[t] >= 2 for t in ts)
            pid = f"{key}.{_key(label(sk))}"
            kpis = [k["id"] for t in ts for k in kp.get(t, [])]
            products.append({"id": pid, "nom": label(sk), "domaine": key, "tables": ts, "kpis": kpis,
                             "type": "référentiel" if ref else "opérationnel", "proprietaire": "à désigner (Data Owner)",
                             "consommateurs": []})
            sous.append({"nom": label(sk), "tables": ts, "data_product": pid})
            for t in ts:
                product_of[t] = pid
        domaines.append({"cle": key, "nom": names.get(key) or key, "tables": mine, "sous_domaines": sous,
                         "data_products": products, "kpis": [k["id"] for t in mine for k in kp.get(t, [])],
                         "kpis_previsibles": [k["id"] for t in mine for k in kp.get(t, []) if k.get("previsible")],
                         "responsabilites": f"Produire, documenter et garantir la qualité de : "
                                            f"{', '.join(s['nom'] for s in sous)}.",
                         "proprietaire": "à désigner (Data Owner)"})
    deps: dict[tuple[str, str, str], int] = {}
    for a, b, _ in links:
        if assignment[a] != assignment[b]:
            k = (assignment[a], assignment[b], product_of[b])
            deps[k] = deps.get(k, 0) + 1
    dependances = [{"de": a, "vers": b, "data_product": p, "liens": n} for (a, b, p), n in deps.items()]
    for d in domaines:
        for p in d["data_products"]:
            p["consommateurs"] = sorted({x["de"] for x in dependances if x["data_product"] == p["id"]})
    return {"entreprise": enterprise, "domaines": domaines, "dependances": dependances,
            "affectation": dict(assignment), "noms": {d["cle"]: d["nom"] for d in domaines},
            "justification": list(justification), "automatique": auto,
            "avertissement": "Découpage proposé par AG10 à partir de la structure des données : domaines, data "
                             "products et responsables à valider par le métier."}


def move_table(mesh: dict, discovery: dict, candidates: list[dict], table: str, domain: str) -> dict:
    """Déplace une table vers un domaine existant (clé) ou nouveau (nom libre)."""
    if table not in mesh["affectation"]:
        raise MeshError(f"Table inconnue : {table}")
    names = dict(mesh["noms"])
    key = domain if domain in names else _key(domain)
    if key not in names:
        if not str(domain or "").strip():
            raise MeshError("Nom du nouveau domaine obligatoire.")
        names[key] = str(domain).strip()[:40]
    aff = {**mesh["affectation"], table: key}
    names = {k: v for k, v in names.items() if k in aff.values()}
    return build_mesh(discovery, candidates, aff, names, mesh["justification"] + [
        f"Modifié par l'utilisateur : {_short(table)} -> {names[key]}."], mesh["entreprise"])


def rename_domain(mesh: dict, discovery: dict, candidates: list[dict], key: str, name: str) -> dict:
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:40]
    if key not in mesh["noms"] or not name:
        raise MeshError("Domaine inconnu ou nom vide.")
    if any(v.lower() == name.lower() for k, v in mesh["noms"].items() if k != key):
        raise MeshError(f"Un autre domaine s'appelle déjà « {name} ».")
    return build_mesh(discovery, candidates, mesh["affectation"], {**mesh["noms"], key: name},
                      mesh["justification"] + [f"Domaine renommé par l'utilisateur : {name}."], mesh["entreprise"])


def merge_domains(mesh: dict, discovery: dict, candidates: list[dict], keep: str, absorb: str) -> dict:
    if keep == absorb or keep not in mesh["noms"] or absorb not in mesh["noms"]:
        raise MeshError("Choisissez deux domaines différents.")
    aff = {t: keep if k == absorb else k for t, k in mesh["affectation"].items()}
    names = {k: v for k, v in mesh["noms"].items() if k != absorb}
    return build_mesh(discovery, candidates, aff, names, mesh["justification"] + [
        f"Fusion par l'utilisateur : {mesh['noms'][absorb]} -> {mesh['noms'][keep]}."], mesh["entreprise"])


# ---------------------------------------------------------------- Agent Mesh Architect + Optimizer
def _needs(d: dict) -> list[str]:
    """Catégories justifiées par les besoins du domaine (pas d'instanciation systématique)."""
    codes = ["AG01"]
    if d["kpis_previsibles"]:
        codes.append("AG02")
    if d["kpis"]:
        codes += ["AG03", "AG04", "AG05"]
    codes.append("AG08")
    return codes


def _why(code: str, d: dict) -> str:
    return {"AG01": f"Capter et comprendre les {len(d['tables'])} table(s) du domaine",
            "AG02": f"{len(d['kpis_previsibles'])} KPI prévisible(s)",
            "AG03": f"{len(d['kpis'])} KPI à arbitrer", "AG04": "Exécuter les missions validées",
            "AG05": "Mesurer l'efficacité des actions", "AG08": "Contrôles de qualité et de conformité"}[code]


def _reusable(code: str, tables: list[str], existing: list[dict]) -> dict | None:
    cat = am.CATEGORIES[code]["nom"]
    for a in existing or []:
        if a.get("status") == "publie" and a.get("category") == cat and set(tables) <= set(a.get("knowledge_tables") or []):
            return {"agent_id": a["agent_id"], "nom": a.get("name"), "handle": a.get("handle"), "statut": a["status"]}
    return None


def design_eia(mesh: dict, *, mutualiser: Any = SHAREABLE, filiere: str = "Transverse", owner: str = "",
               taken: Any = (), existing: Any = (), reuse: bool = True) -> dict:
    """Une EIA par domaine, puis optimisation globale. Résultat compatible avec org_designer.deploy."""
    if filiere not in T.FILIERES:
        raise MeshError(f"Filière inconnue : {filiere} (attendu : {', '.join(T.FILIERES)}).")
    if not mesh.get("domaines"):
        raise MeshError("Aucun domaine : validez d'abord le découpage Data Mesh.")
    shared_codes = {c for c in (mutualiser or ()) if c in SHAREABLE}
    used = {od._key(h) for h in taken if h}
    multi = len(mesh["domaines"]) > 1
    ent = od._fit(mesh.get("entreprise") or "eia", 10) or "eia"
    needs = {d["cle"]: _needs(d) for d in mesh["domaines"]}
    demand = {c: [d for d in mesh["domaines"] if c in needs[d["cle"]]] for c in am.CATEGORIES}
    agents: dict[str, dict] = {}
    equipes, vues, mutualises = [], [], []

    def handle(prefix: str, code: str) -> str:
        suffix = "analyse" if code == "AG01" else od.SUFFIX[code]
        base = f"{prefix}-{suffix}" if len(prefix) + 1 + len(suffix) <= 20 else f"{prefix}-{od.SHORT.get(code, suffix)}"
        return od._unique(base, used)

    def node(key: str, code: str, name: str, h: str, mission: str, ds: list[dict]) -> dict:
        tables = [t for d in ds for t in d["tables"]]
        kpis = [k for d in ds for k in (d["kpis_previsibles"] if code == "AG02" else d["kpis"])]
        n = od._node(key, code, name, h, mission, tables, kpis)
        n.update({"domaines": [d["cle"] for d in ds], "mutualise": len(ds) > 1, "autonomie": AUTONOMIE[code],
                  "justification": " ; ".join(f"{d['nom']} : {_why(code, d)}" for d in ds),
                  "reutilise": _reusable(code, tables, existing) if reuse else None})
        return n

    for code in SHAREABLE:                          # capacités transverses mutualisées (au moins 2 domaines)
        ds = demand[code]
        if code in shared_codes and len(ds) > 1:
            key = code.lower()
            agents[key] = node(key, code, f"{od.LABEL[code]} {mesh.get('entreprise') or 'EIA'}"[:80], handle(ent, code),
                               od.MISSION[code], ds)
            mutualises.append(key)
    for d in mesh["domaines"]:
        dom = od._fit(d["nom"], 10) or "eia"
        members = []
        for code in needs[d["cle"]]:
            key = code.lower() if code.lower() in mutualises else f"{code.lower()}-{d['cle']}"
            if key not in agents:
                mission = od.MISSION[code].format(objet=", ".join(s["nom"] for s in d["sous_domaines"])) \
                    if code == "AG01" else od.MISSION[code]
                agents[key] = node(key, code, f"{'Analyse' if code == 'AG01' else od.LABEL[code]} {d['nom']}"[:80],
                                   handle(dom, code), mission, [d])
            members.append(key)
        th, lead = od._team_handle(dom, used)
        name = f"Équipe {d['nom']}"
        if len(members) > T.MAX_MEMBERS:
            raise MeshError(f"{name} : {len(members)} membres, au plus {T.MAX_MEMBERS}.")
        eq = {"cle": f"equipe-{d['cle']}", "domaine": d["cle"], "nom": name[:T.MAX_NAME], "handle": th,
              "chef_handle": lead, "chef": {"categorie": "AG06", "categorie_nom": am.CATEGORIES["AG06"]["nom"],
                                            "nom": f"Chef {name}"[:80], "handle": lead, "autonomie": AUTONOMIE["AG06"]},
              "mission": f"Piloter le domaine {d['nom']} : {', '.join(s['nom'] for s in d['sous_domaines'])}"[:T.MAX_MISSION],
              "membres": members}
        equipes.append(eq)
        present = {agents[k]["categorie"]: k for k in members}
        cycle = [{"etape": st, "porteur": "Humain (validation)" if c == "HUMAIN" else present.get(c),
                  "couvert": c == "HUMAIN" or c in present,
                  "motif": "" if c == "HUMAIN" or c in present else
                  ("aucun KPI prévisible" if c == "AG02" else "aucun KPI candidat")} for st, c in CYCLE]
        flux = [(a, b, lab) for a, b, lab in (("AG01", "AG02", "séries de KPI"), ("AG01", "AG03", "alertes, constats"),
                                              ("AG02", "AG03", "prévisions"), ("AG03", "HUMAIN", "recommandations"),
                                              ("HUMAIN", "AG04", "missions validées"), ("AG04", "AG05", "résultats"),
                                              ("AG05", "AG01", "apprentissages à valider"))
                if (a == "HUMAIN" or a in present) and (b == "HUMAIN" or b in present)]
        vues.append({"domaine": d["cle"], "nom": d["nom"], "equipe": eq["cle"], "cycle": cycle,
                     "flux": [{"de": present.get(a, a), "vers": present.get(b, b), "objet": lab} for a, b, lab in flux]})
    for e in equipes:
        for k in e["membres"]:
            agents[k]["equipes"].append(e["cle"])
    team_of = {e["domaine"]: e["cle"] for e in equipes}
    inter = [{"de": team_of[x["de"]], "vers": team_of[x["vers"]], "objet": f"data product {x['data_product']}"}
             for x in mesh.get("dependances") or []]
    naive = sum(len(v) for v in needs.values())
    reused = [k for k, a in agents.items() if a.get("reutilise")]
    report = {"agents_sans_optimisation": naive, "agents_optimises": len(agents), "chefs": len(equipes),
              "economie_agents": naive - len(agents), "mutualises": mutualises, "reutilises": reused,
              "a_creer": len(agents) - len(reused) + len(equipes),
              "capacites": [{"capacite": c, "categorie": code, "decision": (
                  "portée par " + code if c in ("Simulation & What-if", "Alerting & Notification") else
                  "mutualisée" if code.lower() in mutualises else
                  "spécifique par domaine" if code == "AG01" else
                  "à venir" if code == "AG07" else
                  "non requise" if not demand.get(code) else "par domaine"), "justification": why}
                  for c, code, why in CAPACITES],
              "notes": ["Coût d'exécution proportionnel au nombre d'agents appelés par cycle : "
                        f"{len(agents)} au lieu de {naive}." if naive > len(agents) else
                        "Aucune mutualisation possible : un seul domaine, aucun doublon.",
                        "Un seul niveau de délégation : HAKIM -> chefs -> agents ; les agents mutualisés sont membres "
                        "de plusieurs équipes (un chef par équipe)."]}
    warn = [mesh.get("avertissement", ""), "Architecture proposée par AG10 : à valider avant toute construction.",
            "Agents et équipes créés en brouillon par AG09 après validation ; publication par un administrateur."]
    partial = sorted({a["categorie"] for a in agents.values() if a["statut_modele"] == "partiel"})
    if partial:
        warn.append("Modèles partiels (fonctions limitées) : " + ", ".join(partial) + ".")
    return {"domaine": mesh.get("entreprise") or "Entreprise", "entreprise": mesh.get("entreprise") or "Entreprise",
            "filiere": filiere, "superviseur": "HAKIM", "owner": owner, "eia_team_id": "",
            "objets": [t for d in mesh["domaines"] for t in d["tables"]], "equipes": equipes, "agents": agents,
            "domaines": vues, "interactions": inter, "validations_humaines": list(VALIDATIONS),
            "a_venir": [od._node("ag07", "AG07", f"{od.LABEL['AG07']} {mesh.get('entreprise') or 'EIA'}", "",
                                 od.MISSION["AG07"], [], [])],
            "usine": [{"categorie": c, "categorie_nom": am.CATEGORIES[c]["nom"], "statut_modele": am.MODELS[c].status,
                       "role": r} for c, r in (("AG10", "Data Mesh, Agent Mesh et optimisation globale"),
                                               ("AG09", "Construction, configuration et déploiement"))],
            "optimisation": report, "mutualisation": sorted(shared_codes), "avertissements": [w for w in warn if w]}


# ---------------------------------------------------------------- organigrammes (style DISCOVERY)
ORG, DOMAIN, TEAM, AGENT, LIGHT = "#4A1942", "#B0124F", "#7A3E9D", "#efe7f2", "#F3E9F7"
STATUS = {"a_deployer": "à déployer", "brouillon": "brouillon créé", "reutilise": "réutilisé", "echec": "échec",
          "exclu": "non retenu"}


def _q(*parts: Any) -> str:
    return '"' + "\\n".join(str(p).replace("\\", "\\\\").replace('"', "'")[:60] for p in parts if p) + '"'


def _id(s: str) -> str:
    return "n_" + re.sub(r"\W", "_", s)


def _head() -> list[str]:
    return ["digraph G {", "rankdir=TB; bgcolor=transparent; nodesep=0.3; ranksep=0.55;",
            f'node [fontname="Helvetica", fontsize=11, style="rounded,filled", shape=box, color="{ORG}"];',
            f'edge [color="{TEAM}"];']


def mesh_dot(mesh: dict, focus: str | None = None) -> str:
    """Organigramme Data Mesh : entreprise -> domaines -> sous-domaines -> data products ; dépendances en pointillé."""
    out = _head() + [f'ent [label={_q(mesh["entreprise"], "Entreprise")}, fillcolor="{ORG}", fontcolor="white"];']
    for d in mesh["domaines"]:
        if focus and d["cle"] != focus:
            continue
        did = _id("d_" + d["cle"])
        out.append(f'{did} [label={_q(d["nom"], "Domaine · " + str(len(d["tables"])) + " table(s)")}, '
                   f'fillcolor="{DOMAIN}", fontcolor="white"];')
        out.append(f"ent -> {did};")
        for s in d["sous_domaines"]:
            sid = _id("s_" + s["data_product"])
            p = next(x for x in d["data_products"] if x["id"] == s["data_product"])
            out.append(f'{sid} [label={_q(s["nom"], "Sous-domaine")}, fillcolor="{TEAM}", fontcolor="white"];')
            out.append(f"{did} -> {sid};")
            pid = _id("p_" + p["id"])
            out.append(f'{pid} [label={_q("Data product " + p["nom"], p["type"], str(len(p["kpis"])) + " KPI", "tables : " + ", ".join(_short(t) for t in p["tables"]))}, '
                       f'shape=note, fillcolor="{LIGHT}", fontcolor="{ORG}"];')
            out.append(f"{sid} -> {pid};")
    for x in mesh.get("dependances") or []:
        if focus and focus not in (x["de"], x["vers"]):
            continue
        if focus and (x["de"] != focus or x["vers"] != focus):
            for k in (x["de"], x["vers"]):
                if k != focus:
                    nm = mesh["noms"].get(k, k)
                    out.append(f'{_id("d_" + k)} [label={_q(nm, "Domaine")}, style="rounded,dashed,filled", '
                               f'fillcolor="white", fontcolor="{DOMAIN}"];')
        out.append(f'{_id("d_" + x["de"])} -> {_id("p_" + x["data_product"])} [style=dashed, color="#E07B00", '
                   f'label={_q("consomme")}, fontsize=9, constraint=false];')
    out.append("}")
    return "\n".join(out)


def eia_dot(arch: dict, view: str = "global", statuses: dict | None = None) -> str:
    """Organigramme EIA : HAKIM au sommet, EIA Factory séparée (conception), domaines, équipes (chef), agents
    spécifiques et capacités mutualisées. view : « global », clé de domaine ou clé d'équipe."""
    st = statuses or {}
    teams = [e for e in arch["equipes"] if view in ("global", e["domaine"], e["cle"])]
    keys = {k for e in teams for k in e["membres"]}
    names = {v["domaine"]: v["nom"] for v in arch["domaines"]}

    def look(k: str) -> str:
        s = st.get(k, "a_deployer")
        return ', style="rounded,dashed,filled", fillcolor="white"' if s in ("a_deployer", "exclu") else \
            ', fillcolor="#FDE2E2"' if s == "echec" else ""

    def tag(k: str) -> str:
        return STATUS.get(st.get(k, "a_deployer"), "")

    out = _head() + [f'hakim [label={_q("HAKIM", "Superviseur de l\'entreprise intelligente")}, fillcolor="{ORG}", '
                     'fontcolor="white"];',
                     'subgraph cluster_factory { label="EIA Factory (conception, hors opérations)"; style=dashed; '
                     f'color="{TEAM}"; fontsize=10;']
    for u in arch["usine"]:
        out.append(f'{u["categorie"].lower()}f [label={_q(u["categorie_nom"], u["role"])}, fillcolor="{LIGHT}", '
                   f'fontcolor="{ORG}"];')
    out += ["}", f'ag10f -> hakim [style=dashed, label={_q("conçoit")}, fontsize=9];',
            f'ag09f -> hakim [style=dashed, label={_q("déploie")}, fontsize=9];']
    for e in teams:
        did, cid = _id("d_" + e["domaine"]), _id("c_" + e["cle"])
        out.append(f'{did} [label={_q(names.get(e["domaine"], e["domaine"]), "Domaine")}, fillcolor="{DOMAIN}", '
                   'fontcolor="white"];')
        out.append(f"hakim -> {did};")
        out.append(f'{cid} [label={_q(e["chef"]["nom"], "Team Manager (AG06)", "@" + e["chef_handle"], tag(e["cle"]))}, '
                   f'fillcolor="{TEAM}", fontcolor="white"{look(e["cle"])}];')
        out.append(f"{did} -> {cid};")
        for k in e["membres"]:
            if not arch["agents"][k].get("mutualise"):
                out.append(f"{cid} -> {_id(k)};")
    def agent_node(k: str) -> str:
        a = arch["agents"][k]
        reuse = "réutilisé : @" + a["reutilise"]["handle"] if a.get("reutilise") else "@" + a["handle"]
        fill = LIGHT if a.get("mutualise") else AGENT
        return (f'{_id(k)} [label={_q(a["nom"], a["categorie_nom"] + " (" + a["categorie"] + ")", reuse, tag(k))}, '
                f'fillcolor="{fill}", fontcolor="{ORG}"{look(k)}];')

    shared = sorted(k for k in keys if arch["agents"][k].get("mutualise"))
    if shared:
        out.append('subgraph cluster_shared { label="Capacités transverses mutualisées"; style="rounded"; '
                   f'color="{DOMAIN}"; fontsize=10;')
        out += [agent_node(k) for k in shared]
        out.append("}")
    out += [agent_node(k) for k in sorted(keys) if k not in shared]
    for e in teams:
        for k in e["membres"]:
            if arch["agents"][k].get("mutualise"):
                out.append(f'{_id("c_" + e["cle"])} -> {_id(k)} [style=dotted];')
    if view == "global":
        for x in arch.get("interactions") or []:
            out.append(f'{_id("c_" + x["de"])} -> {_id("c_" + x["vers"])} [style=dashed, color="#E07B00", '
                       f'label={_q("dépend de")}, fontsize=9, constraint=false];')
    out.append(f'ag07 [label={_q(arch["a_venir"][0]["nom"], "Knowledge & Context (AG07)", "à venir")}, '
               'style="rounded,dashed,filled", fillcolor="white", fontcolor="#777777"];')
    out.append("hakim -> ag07 [style=dotted];")
    out.append("}")
    return "\n".join(out)


def statuses(arch: dict, selected: Any, result: dict | None = None) -> dict:
    """Statut de chaque composant pour l'organigramme : à déployer, non retenu, brouillon, réutilisé, échec."""
    sel = set(arch["agents"]) if selected is None else set(selected)
    out = {k: ("reutilise" if a.get("reutilise") else "a_deployer") if k in sel else "exclu"
           for k, a in arch["agents"].items()}
    out.update({e["cle"]: "a_deployer" if any(k in sel for k in e["membres"]) else "exclu" for e in arch["equipes"]})
    if result:
        done = {x["cle"]: x for x in result.get("agents") or []}
        for k in out:
            if k in done:
                out[k] = "reutilise" if done[k].get("reutilise") else "brouillon"
            elif out[k] == "a_deployer" and result.get("statut") == "echec_partiel":
                out[k] = "echec"
        for e in result.get("equipes") or []:
            out[e["cle"]] = "brouillon"
    return out


# ---------------------------------------------------------------- contrôle après déploiement
def verify(arch: dict, result: dict, agents_rows: list[dict], teams_rows: list[dict]) -> list[dict]:
    """Interactions prêtes : chaque équipe créée existe, son chef appelle exactement ses membres, tous présents."""
    by_id = {a["agent_id"]: a for a in agents_rows}
    teams_by_id = {t.get("team_id"): t for t in teams_rows}
    checks = []
    for x in result.get("agents") or []:
        checks.append({"controle": f"Agent @{x['handle']} présent", "ok": x["agent_id"] in by_id,
                       "detail": (by_id.get(x["agent_id"]) or {}).get("status", "introuvable")})
    for e in result.get("equipes") or []:
        t = teams_by_id.get(e["team_id"])
        checks.append({"controle": f"Équipe @{e['handle']} enregistrée", "ok": t is not None,
                       "detail": (t or {}).get("status", "introuvable")})
        if not t:
            continue
        members = [m for m in (t.get("members") or [])]
        chef = next((x["agent_id"] for x in result.get("agents") or [] if x["cle"] == e["cle"] + "-chef"), None)
        lead = by_id.get(t.get("lead_agent_id") or chef)
        expected = [T.AGENT_PREFIX + m for m in members]
        checks.append({"controle": f"Chef de @{e['handle']} relie ses {len(members)} membres",
                       "ok": bool(lead) and sorted(lead.get("tool_ids") or []) == sorted(expected),
                       "detail": "délégation prête" if lead else "chef introuvable"})
        miss = [m for m in members if m not in by_id]
        checks.append({"controle": f"Membres de @{e['handle']} joignables", "ok": not miss,
                       "detail": "tous présents" if not miss else "absents : " + ", ".join(miss)})
    return checks


def stages(plan: dict, arch: dict | None) -> list[dict]:
    """Avancement des quatre étapes de la démarche (Transformation Center)."""
    s = (arch or {}).get("status")
    rank = {"brouillon": 1, "mesh_valide": 2, "eia_valide": 3, "deployee": 4}.get(s or "", 0)
    done = [bool(plan.get("discovery")), rank >= 2, rank >= 3, rank >= 4]
    started = [bool(plan.get("discovery")), rank >= 1, rank >= 2, rank >= 3]
    labels = ("Data Discovery", "Data Mesh Architecture", "EIA Architecture", "Deployment")
    return [{"libelle": l, "statut": "fait" if d else "en_cours" if st_ else "a_faire"}
            for l, d, st_ in zip(labels, done, started)]
