"""Organigramme d'agents d'entreprise (EIA Factory : AG10 conception, AG09 déploiement) en agents IA.

Après la découverte des données, propose une organisation d'agents IA par domaine de données :
- HAKIM supervise ; chaque équipe a un chef Team Manager (AG06) ;
- un agent Data Intelligence (AG01) par objet de données (table découverte ayant des KPI candidats) ;
- des agents transverses : Predictive Intelligence (AG02, si des KPI sont prévisibles), Strategic Intelligence (AG03),
  Execution & Automation (AG04), Learning & Improvement (AG05), Monitoring & Governance (AG08) ;
- Knowledge & Context (AG07) affiché « à venir » tant que son modèle est un squelette ;
- Engineering & Builder (AG09) et Enterprise Architect (AG10) restent dans l'EIA Factory (hors équipes métier).

Contraintes de la plateforme (backend.teams) : un seul niveau de délégation, MAX_MEMBERS membres par équipe.
Au-delà, le domaine reçoit des équipes sœurs (objets liés regroupés) ; les agents transverses sont partagés
(un membre peut appartenir à plusieurs équipes, un chef n'en dirige qu'une).

propose() et dot() ne lisent ni n'écrivent aucune table. deploy() crée, sur décision de l'utilisateur, les agents
et les équipes en brouillon avec les dépôts de la plateforme ; la publication reste réservée aux administrateurs.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from backend import personas
from backend import teams as T
from backend.eia import agent_models as am
from backend.mentions import slug as _key

TRANSVERSE = ("AG02", "AG03", "AG04", "AG05", "AG08")
FACTORY_ONLY = ("AG10", "AG09")
DEPLOYABLE_STATUSES = ("disponible", "partiel")
SUFFIX = {"AG02": "prevision", "AG03": "strategie", "AG04": "execution", "AG05": "amelioration",
          "AG07": "connaissance", "AG08": "gouvernance"}
SHORT = {"AG05": "progres", "AG08": "gouv", "AG07": "savoir"}     # si le nom d'appel complet dépasse 20 caractères
LABEL = {"AG02": "Prévision", "AG03": "Stratégie", "AG04": "Exécution", "AG05": "Amélioration",
         "AG07": "Connaissance", "AG08": "Gouvernance"}
ICON = {"AG01": "query_stats", "AG02": "trending_up", "AG03": "lightbulb", "AG04": "play_circle",
        "AG05": "school", "AG07": "menu_book", "AG08": "verified"}
TOOLS = {   # outils de la plateforme ; les outils qui écrivent demandent une confirmation à l'exécution
    "AG01": ["describe_table", "get_table_profile", "execute_sql", "eia_kpi", "eia_apercu_cycle"],
    "AG02": ["eia_kpi", "eia_forecast", "execute_sql"],
    "AG03": ["eia_apercu_cycle", "eia_kpi"],
    "AG04": ["eia_preparer_mission", "eia_suivi_mission", "eia_personnel", "eia_affectation"],
    "AG05": ["eia_bilan_mission", "eia_kpi"],
    "AG08": ["eia_apercu_cycle", "get_table_lineage", "describe_table", "get_table_profile"],
}
MISSION = {
    "AG01": "Analyser l'objet {objet} : KPI, évolutions, ruptures et qualité des données",
    "AG02": "Prévoir les KPI prévisibles avec une fiabilité mesurée",
    "AG03": "Proposer et prioriser des actions à partir des alertes et des prévisions",
    "AG04": "Préparer et suivre les missions validées, sans rien exécuter seul",
    "AG05": "Évaluer les missions terminées et proposer des améliorations",
    "AG07": "Rechercher et citer les documents et le glossaire du domaine",
    "AG08": "Surveiller la qualité, la fraîcheur, les garde-fous et la traçabilité",
}
RULES = {
    "AG01": "Chaque chiffre vient d'une requête ou d'un outil : cite la requête ; signale les données manquantes.",
    "AG02": "Donne la méthode, l'erreur de backtest et la fiabilité ; une prévision non fiable est présentée comme telle.",
    "AG03": "Sans règle ni plan d'action validés, ne propose aucun seuil : indique ce qui manque et qui doit valider.",
    "AG04": "Les outils qui écrivent demandent une confirmation ; aucune action sans décision humaine.",
    "AG05": "Aucune conclusion causale : décris les variations observées après clôture, contre la référence figée.",
    "AG08": "Sépare toujours les erreurs techniques des anomalies métier ; cite la preuve de chaque constat.",
}


class OrgError(ValueError):
    pass


def _ascii(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _slug(s: Any, limit: int) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _ascii(s)).strip("-")[:limit].rstrip("-_")


def _fit(name: str, limit: int) -> str:
    """Slug coupé entre deux mots (au moins le premier mot, tronqué si nécessaire)."""
    words, out = _slug(name, 80).split("-"), ""
    for w in words:
        nxt = f"{out}-{w}" if out else w
        if len(nxt) > limit:
            break
        out = nxt
    return out or words[0][:limit]


def _object_name(table: str, domain: str) -> str:
    words = [w for w in re.sub(r"^data_", "", table.split(".")[-1]).split("_") if w]
    dom = set(_slug(domain, 60).split("-"))
    keep = [w for w in words if _ascii(w) not in dom] or words
    return " ".join(keep).capitalize()


def _unique(base: str, used: set) -> str:
    """Nom d'appel valide (personas.HANDLE) et libre ; réservé dans `used` (clés normalisées)."""
    base = base if base[:1].isalpha() else ("a-" + base)
    h, i = base[:20].rstrip("-_"), 2
    while _key(h) in used or h in personas.RESERVED or not personas.HANDLE.match(h):
        sfx = f"-{i}"
        h = base[:20 - len(sfx)].rstrip("-_") + sfx
        i += 1
        if i > 99:
            raise OrgError(f"Aucun nom d'appel libre pour {base}.")
    used.add(_key(h))
    return h


def _lead_handle(team_handle: str) -> str:
    return ("chef-" + team_handle)[:20].rstrip("-_")          # calcul identique à TeamRepository.create_lead


def _team_handle(base: str, used: set) -> tuple[str, str]:
    """Nom d'appel d'équipe dont le nom d'appel du chef (créé par la plateforme) est aussi libre."""
    for i in range(1, 100):
        h = base if i == 1 else f"{base[:17]}-{i}"
        if _key(h) in used or not personas.HANDLE.match(h) or h in personas.RESERVED:
            continue
        lead = _lead_handle(h)
        if _key(lead) in used or not personas.HANDLE.match(lead):
            continue
        used.update({_key(h), _key(lead)})
        return h, lead
    raise OrgError(f"Aucun nom d'appel d'équipe libre pour {base}.")


def _groups(objects: list[str], links: list[dict], slots: int) -> list[list[str]]:
    """Objets liés (liens probables de la découverte) dans la même équipe ; au plus `slots` objets par équipe."""
    parent = {t: t for t in objects}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for link in links:
        a, b = (str(link.get(k) or "").rsplit(".", 1)[0] for k in ("de", "vers"))
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    comps: dict[str, list[str]] = {}
    for t in objects:
        comps.setdefault(find(t), []).append(t)
    groups: list[list[str]] = []
    for comp in sorted(comps.values(), key=lambda c: (-len(c), objects.index(c[0]))):
        chunks = [comp[i:i + slots] for i in range(0, len(comp), slots)]
        room = next((g for g in groups if len(g) + len(comp) <= slots), None) if len(chunks) == 1 else None
        if room is not None:
            room.extend(comp)
        else:
            groups.extend(list(c) for c in chunks)
    return groups


def _node(key: str, code: str, name: str, handle: str, mission: str, tables: list[str], kpis: list[str]) -> dict:
    model = am.MODELS.get(code)
    status = model.status if model else "inconnu"
    ok = status in DEPLOYABLE_STATUSES
    return {"cle": key, "categorie": code, "categorie_nom": am.CATEGORIES[code]["nom"], "statut_modele": status,
            "nom": name[:80], "handle": handle, "mission": mission[:140], "tables": tables, "kpis": kpis,
            "outils": list(TOOLS.get(code, [])) if ok else [], "deployable": ok,
            "raison": "" if ok else f"Modèle {code} {status} : à venir, non déployé", "equipes": []}


def propose(discovery: dict, candidates: list[dict], *, domain: str, filiere: str = "Transverse", owner: str = "",
            eia_team_id: str = "", taken: Any = ()) -> dict:
    """Organigramme proposé à partir de la découverte et des KPI candidats (aucune lecture ni écriture).

    taken : noms d'appel déjà utilisés (agents et équipes de la plateforme), pour proposer des noms libres.
    """
    domain = re.sub(r"\s+", " ", str(domain or "")).strip()[:40]
    if not domain:
        raise OrgError("Nom du domaine obligatoire.")
    if filiere not in T.FILIERES:
        raise OrgError(f"Filière inconnue : {filiere} (attendu : {', '.join(T.FILIERES)}).")
    by_table: dict[str, list[dict]] = {}
    for k in candidates or []:
        by_table.setdefault(k["table"], []).append(k)
    objects = [t["table"] for t in discovery.get("tables") or [] if t.get("table") in by_table]
    if not objects:
        raise OrgError("Aucun objet de données avec KPI candidat : organigramme impossible.")
    used = {_key(h) for h in taken if h}
    dom = _fit(domain, 10) or "eia"
    previsibles = [k["id"] for k in candidates if k.get("previsible")]
    all_kpis = [k["id"] for k in candidates]
    groups = _groups(objects, discovery.get("liens_probables") or [],
                     T.MAX_MEMBERS - len([c for c in TRANSVERSE if c != "AG02" or previsibles]))
    multi = len(groups) > 1

    agents: dict[str, dict] = {}
    equipes = []
    for i, group in enumerate(groups, 1):
        th, lead = _team_handle(dom if not multi else f"{dom}-{i}", used)
        name = f"Équipe {domain}" + (f" {i}" if multi else "")
        names = [_object_name(t, domain) for t in group]
        keys = []
        for t, n in zip(group, names):
            key = f"ag01-{len([k for k in agents if k.startswith('ag01-')]) + 1}"
            kp = [k["id"] for k in by_table[t]]
            agents[key] = _node(key, "AG01", f"Analyse {n}", _unique(f"{dom}-{_fit(n, max(3, 19 - len(dom)))}", used),
                                MISSION["AG01"].format(objet=n), [t], kp)
            keys.append(key)
        equipes.append({"cle": f"equipe-{i}", "nom": name[:T.MAX_NAME], "handle": th, "chef_handle": lead,
                        "chef": {"categorie": "AG06", "categorie_nom": am.CATEGORIES["AG06"]["nom"],
                                 "nom": f"Chef {name}"[:80], "handle": lead},
                        "mission": f"Piloter les données {domain} : {', '.join(names)}"[:T.MAX_MISSION],
                        "membres": keys})
    for code in TRANSVERSE:
        if code == "AG02" and not previsibles:
            continue
        key = code.lower()
        agents[key] = _node(key, code, f"{LABEL[code]} {domain}", _unique(f"{dom}-{SUFFIX[code]}" if len(dom) + 1 + len(SUFFIX[code]) <= 20
                                    else f"{dom}-{SHORT.get(code, SUFFIX[code])}", used),
                            MISSION[code], list(objects), previsibles if code == "AG02" else all_kpis)
        for e in equipes:
            e["membres"].append(key)
    for e in equipes:
        for k in e["membres"]:
            agents[k]["equipes"].append(e["cle"])
    a_venir = [_node("ag07", "AG07", f"{LABEL['AG07']} {domain}", "", MISSION["AG07"], [], [])]
    usine = [{"categorie": c, "categorie_nom": am.CATEGORIES[c]["nom"], "statut_modele": am.MODELS[c].status,
              "role": "Conçoit (AG10) et déploie (AG09) les équipes : EIA Factory, hors équipes métier"}
             for c in FACTORY_ONLY]
    warn = ["KPI et périmètres déduits de la structure des données : à valider par le responsable métier.",
            "Agents et équipes créés en brouillon ; publication par un administrateur depuis la page Équipes."]
    if multi:
        warn.append(f"{len(equipes)} équipes sœurs : un seul niveau de délégation et {T.MAX_MEMBERS} membres au plus "
                    "par équipe ; agents transverses partagés.")
    if not previsibles:
        warn.append("Aucun KPI prévisible (historique insuffisant) : pas d'agent Prévision (AG02).")
    warn.append("Stratégie : recommandations possibles seulement après validation de règles et de plans d'action.")
    partial = sorted({a["categorie"] for a in agents.values() if a["statut_modele"] == "partiel"})
    if partial:
        warn.append("Modèles partiels (fonctions limitées) : " + ", ".join(partial) + ".")
    return {"domaine": domain, "filiere": filiere, "superviseur": "HAKIM", "owner": owner,
            "eia_team_id": eia_team_id, "objets": objects, "equipes": equipes, "agents": agents,
            "a_venir": a_venir, "usine": usine, "avertissements": warn}


def instructions(node: dict, org: dict) -> str:
    lines = [f"Tu es « {node['nom']} », agent IA {node['categorie_nom']} ({node['categorie']}) du domaine "
             f"« {org['domaine']} » dans DISCOVERY (EIA, supervision HAKIM).", f"Mission : {node['mission']}.", ""]
    if node["tables"]:
        lines += ["## Données", *[f"- {t}" for t in node["tables"]], ""]
    if node["kpis"]:
        lines += ["## KPI candidats (à valider par le métier)", *[f"- {k}" for k in node["kpis"]], ""]
    if org.get("eia_team_id"):
        lines += [f"Équipe EIA de référence pour les outils eia_* : team_id = {org['eia_team_id']}.", ""]
    lines += ["## Règles", *[f"- {g}." for g in am.GUARDRAILS]]
    if node["categorie"] in RULES:
        lines.append(f"- {RULES[node['categorie']]}")
    lines.append("- Réponds en français, court, en citant tes sources.")
    return "\n".join(lines)


def _label(*parts: str) -> str:
    return '"' + "\\n".join(str(p).replace('"', "'") for p in parts if p) + '"'


def dot(org: dict, selected: Any = None) -> str:
    """Organigramme au format Graphviz (st.graphviz_chart). Hors sélection ou à venir : pointillés."""
    sel = set(org["agents"]) if selected is None else set(selected)
    out = ["digraph EIA {", 'rankdir=TB; nodesep=0.25; ranksep=0.5;',
           'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, fillcolor="#eef3f9"];',
           f'hakim [label={_label("HAKIM", "superviseur IA")}, fillcolor="#1f3a5f", fontcolor="white"];',
           'subgraph cluster_factory { label="EIA Factory (conception)"; style=dashed; fontsize=9;']
    for u in org["usine"]:
        out.append(f'{u["categorie"].lower()}f [label={_label(u["categorie_nom"], u["categorie"])}, fillcolor="#f4f4f4"];')
    out.append("}")
    out.append(f'{org["usine"][0]["categorie"].lower()}f -> hakim [style=dashed, label="conçoit", fontsize=8];')
    for e in org["equipes"]:
        cid = e["cle"].replace("-", "_") + "_chef"
        active = any(k in sel for k in e["membres"])
        style = "" if active else ', style="rounded,dashed", fillcolor="white"'
        out.append(f'{cid} [label={_label(e["chef"]["nom"], "Team Manager (AG06)", "@" + e["chef_handle"])}, '
                   f'fillcolor="#d6e4f5"{style}];')
        out.append(f"hakim -> {cid};")
        for k in e["membres"]:
            out.append(f'{cid} -> {k.replace("-", "_")}' + ("" if k in sel else " [style=dashed]") + ";")
        out.append(f'{cid} -> ag07 [style=dotted];')
    for k, a in org["agents"].items():
        style = "" if k in sel else ', style="rounded,dashed", fillcolor="white"'
        out.append(f'{k.replace("-", "_")} [label={_label(a["nom"], a["categorie_nom"] + " (" + a["categorie"] + ")", "@" + a["handle"])}{style}];')
    for a in org["a_venir"]:
        out.append(f'{a["cle"]} [label={_label(a["nom"], a["categorie_nom"], "à venir")}, style="rounded,dashed", '
                   'fillcolor="white", fontcolor="#777777"];')
    out.append("}")
    return "\n".join(out)


def deploy(org: dict, selected: Any, agents_repo: Any, teams_repo: Any, user: str) -> dict:
    """Crée en brouillon les agents sélectionnés, leurs chefs et leurs équipes (décision de l'utilisateur).

    Contrôles avant toute écriture : utilisateur identifié, agents déployables, noms d'appel libres, équipes non
    vides. Les écritures ne sont pas transactionnelles : en cas d'échec, ce qui a été créé est listé (à archiver).
    """
    user = str(user or "").strip().lower()
    if not user or user.startswith("agent:") or not T.EMAIL.match(user):
        raise OrgError("Déploiement réservé à un utilisateur identifié (adresse e-mail).")
    sel = set(selected or [])
    unknown = sorted(sel - set(org["agents"]))
    if unknown:
        raise OrgError("Agents inconnus : " + ", ".join(unknown))
    blocked = sorted(k for k in sel if not org["agents"][k]["deployable"])
    if blocked:
        raise OrgError("Agents non déployables : " + ", ".join(blocked))
    plan = [(e, [k for k in e["membres"] if k in sel]) for e in org["equipes"]]
    plan = [(e, m) for e, m in plan if m]
    if not plan:
        raise OrgError("Sélectionnez au moins un agent membre d'une équipe.")
    needed = [k for k in org["agents"] if any(k in m for _, m in plan)]
    agents, teams = agents_repo.list_agents(), teams_repo.list_teams()
    taken = set(personas.taken_keys(agents)) | {_key(t.get("handle") or "") for t in teams
                                                 if t.get("status") != "archive" and t.get("handle")}
    handles = [org["agents"][k]["handle"] for k in needed] + [h for e, _ in plan for h in (e["handle"], e["chef_handle"])]
    clash = sorted({h for h in handles if _key(h) in taken})
    if clash or len({_key(h) for h in handles}) != len(handles):
        raise OrgError("Noms d'appel déjà utilisés : " + ", ".join("@" + h for h in clash)
                       + ". Proposez de nouveau l'organigramme.")
    created: list[dict] = []
    teams_out: list[dict] = []
    ids: dict[str, str] = {}
    try:
        for k in needed:
            n = org["agents"][k]
            meta = {"name": n["nom"], "icon": ICON.get(n["categorie"], "smart_toy"), "category": n["categorie_nom"],
                    "description": (f"{n['mission']}. Généré par le Team Builder (EIA Factory) : {n['categorie']} "
                                    f"{n['categorie_nom']}, domaine {org['domaine']}.")[:300],
                    "handle": n["handle"], "persona": n["categorie_nom"][:personas.MAX_PERSONA],
                    "tagline": n["mission"][:personas.MAX_TAGLINE]}
            cfg = {"model_endpoint": agents_repo.s.default_model, "instructions": instructions(n, org),
                   "tool_ids": list(n["outils"]), "knowledge_tables": list(n["tables"]), "temperature": 0.1,
                   "max_iterations": 6}
            ids[k] = agents_repo.create_agent(meta, cfg, user, status="brouillon")
            created.append({"cle": k, "agent_id": ids[k], "nom": n["nom"], "handle": n["handle"]})
        for e, members in plan:
            data = {"name": e["nom"], "handle": e["handle"], "mission": e["mission"], "filiere": org["filiere"],
                    "icon": "groups", "members": [ids[k] for k in members], "primary": [ids[k] for k in members],
                    "human_owner": user}
            errs = [x for x in T.validate(T.normalize({**data, "lead_agent_id": "en-creation"}),
                                          agents_repo.list_agents(), teams_repo.list_teams())
                    if "Chef d'équipe introuvable" not in x]
            if errs:
                raise OrgError(" ".join(errs))
            data["lead_agent_id"] = teams_repo.create_lead(data, user)
            created.append({"cle": e["cle"] + "-chef", "agent_id": data["lead_agent_id"], "nom": e["chef"]["nom"],
                            "handle": e["chef_handle"]})
            tid = teams_repo.save(data, user, note="Créée par le Team Builder (EIA Factory)")
            teams_out.append({"cle": e["cle"], "team_id": tid, "nom": e["nom"], "handle": e["handle"],
                              "membres": len(members)})
    except Exception as ex:  # noqa: BLE001 - échec partiel restitué tel quel, rien n'est masqué
        return {"statut": "echec_partiel", "erreur": f"{type(ex).__name__} : {ex}", "agents": created,
                "equipes": teams_out, "suite": "Archivez les brouillons créés depuis Mes agents / Équipes, puis relancez."}
    return {"statut": "brouillon", "agents": created, "equipes": teams_out,
            "suite": "Relisez les agents dans Mes agents ; publication des équipes par un administrateur (page Équipes)."}
