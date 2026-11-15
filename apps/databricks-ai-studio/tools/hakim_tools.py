"""Outils de HakimAI, lot 1 : lecture seule, toujours filtrés par ce que l'utilisateur a le droit de voir.

Les tables de configuration sont lues avec le compte de l'application ; la visibilité est donc appliquée ici :
- agents : publiés, ou dont l'utilisateur est propriétaire, ou tous pour un administrateur ;
- équipes : publiées, ou dont il est propriétaire, ou toutes pour un administrateur ;
- détails des erreurs (arguments, messages) : ses propres appels, ses agents, ou tous pour un administrateur.
Les données métier (explorer_donnees) sont lues avec le jeton de l'utilisateur : Unity Catalog s'applique.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from backend import personas
from backend.mentions import slug
from backend.tool_registry import ToolContext, ToolError

PAGES = {
    "accueil": ("views/accueil.py", "Accueil", "Vue d'ensemble et raccourcis"),
    "hakimai": ("views/hakim.py", "HakimAI", "Poser une question à l'architecte de la plateforme"),
    "mes_agents": ("views/mes_agents.py", "Mes agents", "Rechercher, ouvrir, archiver ses agents"),
    "equipes": ("views/equipes.py", "Équipes", "Organigramme, création et gestion des équipes d'agents"),
    "agent_builder": ("views/agent_builder.py", "Agent Builder", "Créer ou modifier un agent, avec l'assistant de conception"),
    "chat": ("views/chat.py", "Chat & Test", "Discuter avec un agent, mentionner @agent ou @équipe"),
    "catalogue_outils": ("views/tool_catalog.py", "Catalogue d'outils", "Outils disponibles, création d'outils SQL, fonction UC ou HTTP"),
    "knowledge_studio": ("views/knowledge_studio.py", "Knowledge Studio", "Sources de connaissance"),
    "marketplace": ("views/marketplace.py", "Marketplace", "Agents partagés"),
    "assessment": ("views/assessment.py", "Assessment Center", "Évaluation des agents"),
    "monitoring": ("views/monitoring.py", "Monitoring", "Appels d'outils, erreurs, latences"),
    "parametres": ("views/parametres.py", "Paramètres", "Configuration de l'application"),
}

ACTIONS = {   # actions réellement disponibles sur chaque page (référence pour HakimAI ; ne rien ajouter d'autre)
    "Accueil": ["voir les indicateurs et les agents récents", "ouvrir les raccourcis vers les autres pages"],
    "Mes agents": ["rechercher un agent (nom, @nom d'appel, rôle, accroche)", "ouvrir un agent dans Agent Builder ou le chat",
                   "archiver un de ses agents"],
    "Équipes": ["Organigramme : voir les équipes par filière, chef, membres, responsable humain, activité 30 jours",
                "Créer une équipe : nom, @nom d'appel, filière, mission, responsable humain, icône, membres, chef "
                "(aucun, coordinateur existant, ou chef créé en brouillon)",
                "Mes équipes : modifier, retirer en brouillon, archiver, voir l'historique",
                "publier une équipe : administrateurs uniquement"],
    "Agent Builder": ["décrire le besoin à l'assistant de conception qui propose un agent", "renseigner identité, "
                      "instructions, modèle, outils, tables autorisées", "rejoindre une équipe", "enregistrer en brouillon ou publier"],
    "Chat & Test": ["choisir un agent et discuter", "mentionner @agent ou @équipe", "valider ou refuser une action en attente",
                    "voir les outils appelés sous chaque réponse"],
    "Catalogue d'outils": ["consulter les outils et leurs statuts", "créer un outil SQL paramétré, une fonction UC ou un "
                           "appel HTTP via connexion UC, avec l'assistant", "tester puis enregistrer un outil, voir ses versions"],
    "Monitoring": ["voir les appels d'outils récents, les taux d'erreur et les latences"],
    "HakimAI": ["poser une question sur la plateforme", "obtenir un diagnostic ou une visite guidée",
                "ouvrir la page proposée via le bouton « Ouvrir … »", "recommencer une conversation"],
}

GUIDE = {
    "agents": "Un agent = des instructions, un modèle, des outils et éventuellement des tables autorisées. Il a une identité "
              "(prénom, rôle, nom d'appel @). Création dans Agent Builder, en brouillon ; chaque enregistrement crée une version.",
    "outils": "Un outil est une action que l'agent peut appeler : lecture Unity Catalog, SQL en lecture seule, carte, "
              "Smart Office, HTTP. On peut créer des outils SQL paramétrés, des fonctions UC ou des appels HTTP via une "
              "connexion UC dans le Catalogue d'outils. Les outils qui écrivent ou envoient exigent une confirmation.",
    "equipes": "Une équipe regroupe des agents autour d'une mission. @équipe envoie la question au chef (agent coordinateur) "
               "qui consulte les membres et rend une synthèse. Un chef ne dirige qu'une équipe ; un membre peut appartenir à plusieurs.",
    "mentions": "Dans le chat, tapez @ pour adresser un message à un agent ou une équipe. Tab complète, plusieurs mentions "
                "possibles : chaque agent répond, puis l'agent principal fait la synthèse.",
    "statuts": "brouillon : visible par son propriétaire ; publie : visible par tous ; archive : retiré. Un outil peut aussi "
               "être planifie ou indisponible.",
    "publication": "Les agents et outils en lecture seule sont publiés par leur propriétaire. Les outils qui écrivent ou "
                   "envoient et les équipes sont publiés par un administrateur.",
    "securite": "Les données sont lues avec vos droits Unity Catalog. Le SQL est limité à la lecture. Les actions sensibles "
                "demandent votre confirmation et sont journalisées.",
    "monitoring": "Le Monitoring montre les appels d'outils, les taux d'erreur et les latences par agent et par outil.",
    "chat": "Chat & Test permet d'essayer un agent, y compris en brouillon pour son propriétaire. Les appels d'outils sont "
            "visibles sous chaque réponse.",
}

TOURS = {
    "decouverte": ["accueil", "chat", "mes_agents", "equipes"],
    "createur_agent": ["agent_builder", "catalogue_outils", "chat", "mes_agents"],
    "createur_outil": ["catalogue_outils", "agent_builder", "chat", "monitoring"],
    "administrateur": ["catalogue_outils", "equipes", "monitoring", "parametres"],
}


@dataclass
class Platform:
    repo: Any
    teams: Any
    user: str
    is_admin: bool = False
    page: dict = field(default_factory=dict)

    def t(self, name: str) -> str:
        return self.repo.s.table(name)


def _p(ctx: ToolContext) -> Platform:
    if not isinstance(ctx.platform, Platform):
        raise ToolError("Outil réservé à HakimAI.")
    return ctx.platform


def _visible_agents(p: Platform) -> list[dict]:
    return [a for a in p.repo.list_agents() if a.get("status") != "archive" and
            (p.is_admin or a.get("status") == "publie" or a.get("owner") == p.user)]


def _find_agent(p: Platform, ref: str) -> dict:
    key = slug(str(ref).lstrip("@"))
    for a in _visible_agents(p):
        names = [a.get("handle") or "", a.get("name") or ""] + list(a.get("aliases") or [])
        if str(ref) == a["agent_id"] or any(key and key == slug(n) for n in names if n):
            return a
    raise ToolError(f"Agent « {ref} » introuvable ou non visible pour vous.")


def _can_detail(p: Platform, agent: dict | None, call_user: str | None) -> bool:
    return p.is_admin or call_user == p.user or bool(agent and agent.get("owner") == p.user)


# --- Navigation et contexte -------------------------------------------------------------------------
def contexte_page(ctx: ToolContext) -> dict:
    p = _p(ctx)
    page = p.page.get("page", "")
    return {"utilisateur": p.user, "administrateur": p.is_admin, "page": page,
            "objet_affiche": {k: v for k, v in p.page.items() if k != "page" and v},
            "actions_disponibles": ACTIONS.get(page, ["(pas de description détaillée pour cette page)"]),
            "pages": {k: v[1] for k, v in PAGES.items()}}


def ouvrir_page(ctx: ToolContext, page: str, raison: str = "") -> dict:
    _p(ctx)
    if page not in PAGES:
        raise ToolError("Page inconnue. Pages possibles : " + ", ".join(PAGES))
    path, title, desc = PAGES[page]
    return {"navigation": path, "titre": title, "description": desc, "raison": raison,
            "note": "Un bouton d'ouverture est affiché à l'utilisateur ; la navigation n'est pas automatique."}


def aide_plateforme(ctx: ToolContext, sujet: str) -> dict:
    _p(ctx)
    if sujet not in GUIDE:
        raise ToolError("Sujet inconnu. Sujets : " + ", ".join(GUIDE))
    return {"sujet": sujet, "explication": GUIDE[sujet]}


def visite_guidee(ctx: ToolContext, profil: str = "decouverte") -> dict:
    _p(ctx)
    if profil not in TOURS:
        raise ToolError("Profil inconnu. Profils : " + ", ".join(TOURS))
    return {"profil": profil, "etapes": [{"ordre": i + 1, "page": k, "titre": PAGES[k][1], "objectif": PAGES[k][2]}
                                         for i, k in enumerate(TOURS[profil])]}


# --- Inventaire ---------------------------------------------------------------------------------------
def lister_agents(ctx: ToolContext, recherche: str = "", statut: str = "") -> dict:
    p = _p(ctx)
    q = recherche.lower().strip()
    rows = []
    for a in _visible_agents(p):
        text = " ".join(str(a.get(k) or "") for k in ("name", "handle", "persona", "tagline", "category", "description"))
        if q and q not in text.lower():
            continue
        if statut and a.get("status") != statut:
            continue
        rows.append({"agent_id": a["agent_id"], "nom": a.get("name"), "appel": "@" + (a.get("handle") or ""),
                     "role": a.get("persona"), "statut": a.get("status"), "version": a.get("current_version"),
                     "categorie": a.get("category"), "proprietaire": a.get("owner"),
                     "a_moi": a.get("owner") == p.user})
    return {"nombre": len(rows), "agents": rows}


def decrire_agent(ctx: ToolContext, agent: str) -> dict:
    p = _p(ctx)
    a = _find_agent(p, agent)
    cfg = p.repo.get_config(a["agent_id"])
    teams = [t["name"] for t in p.teams.list_teams()
             if a["agent_id"] in t["members"] or a["agent_id"] == t.get("lead_agent_id")]
    return {"agent_id": a["agent_id"], "nom": a.get("name"), "appel": "@" + (a.get("handle") or ""),
            "role": a.get("persona"), "accroche": a.get("tagline"), "statut": a.get("status"),
            "proprietaire": a.get("owner"), "version": cfg.version if cfg else None,
            "modele": cfg.model_endpoint if cfg else None, "outils": cfg.tool_ids if cfg else [],
            "tables_autorisees": cfg.knowledge_tables if cfg else [], "equipes": teams,
            "instructions": (cfg.instructions[:3000] if cfg else "")}


def comparer_versions(ctx: ToolContext, agent: str, version_a: int = 0, version_b: int = 0) -> dict:
    p = _p(ctx)
    a = _find_agent(p, agent)
    cur = p.repo.get_config(a["agent_id"])
    if not cur:
        raise ToolError("Configuration introuvable.")
    vb = version_b or cur.version
    va = version_a or max(1, vb - 1)
    A, B = p.repo.get_config(a["agent_id"], va), p.repo.get_config(a["agent_id"], vb)
    if not A or not B:
        raise ToolError(f"Version introuvable (versions 1 à {cur.version}).")
    diff = list(difflib.unified_diff(A.instructions.splitlines(), B.instructions.splitlines(), f"v{va}", f"v{vb}", lineterm="", n=1))
    return {"agent": a.get("name"), "versions": [va, vb],
            "outils_ajoutes": sorted(set(B.tool_ids) - set(A.tool_ids)),
            "outils_retires": sorted(set(A.tool_ids) - set(B.tool_ids)),
            "tables_ajoutees": sorted(set(B.knowledge_tables) - set(A.knowledge_tables)),
            "tables_retirees": sorted(set(A.knowledge_tables) - set(B.knowledge_tables)),
            "modele": [A.model_endpoint, B.model_endpoint] if A.model_endpoint != B.model_endpoint else A.model_endpoint,
            "instructions_modifiees": bool(diff), "diff_instructions": "\n".join(diff)[:4000]}


def lister_outils(ctx: ToolContext, recherche: str = "", statut: str = "") -> dict:
    p = _p(ctx)
    q = recherche.lower().strip()
    rows = []
    for s in p.repo.list_tools():
        if s.status == "archive" and not p.is_admin:
            continue
        if q and q not in f"{s.tool_id} {s.name} {s.category} {s.description}".lower():
            continue
        if statut and s.status != statut:
            continue
        rows.append({"outil": s.tool_id, "nom": s.name, "categorie": s.category, "statut": s.status,
                     "lecture_seule": s.read_only, "confirmation": s.requires_confirmation,
                     "type": "créé" if s.owner else "intégré", "proprietaire": s.owner or None,
                     "description": s.description[:200]})
    return {"nombre": len(rows), "outils": rows}


def lister_equipes(ctx: ToolContext) -> dict:
    p = _p(ctx)
    names = {a["agent_id"]: a for a in p.repo.list_agents()}
    show = lambda i: personas.display(names[i]) if i in names else i  # noqa: E731
    rows = [{"equipe": t["name"], "appel": "@" + t["handle"], "statut": t["status"], "filiere": t.get("filiere"),
             "mission": t.get("mission"), "chef": show(t["lead_agent_id"]) if t.get("lead_agent_id") else None,
             "membres": [show(m) for m in t["members"]], "responsable_humain": t.get("human_owner") or "à désigner"}
            for t in p.teams.list_teams()
            if p.is_admin or t["status"] == "publie" or t.get("owner") == p.user]
    return {"nombre": len(rows), "equipes": rows}


# --- Diagnostic ---------------------------------------------------------------------------------------
def activite(ctx: ToolContext, agent: str = "", jours: int = 30) -> dict:
    p = _p(ctx)
    agents = [_find_agent(p, agent)] if agent else _visible_agents(p)
    ids = [a["agent_id"] for a in agents]
    if not ids:
        return {"periode_jours": jours, "agents": []}
    params = {f"a{i}": x for i, x in enumerate(ids)} | {"d": int(jours), "u": p.user}
    inlist = ", ".join(f":a{i}" for i in range(len(ids)))
    r = p.repo.sql.query(f"""
        SELECT agent_id, count(DISTINCT conversation_id) AS conversations, count(*) AS appels,
               sum(CASE WHEN status = 'succes' THEN 1 ELSE 0 END) AS succes,
               sum(CASE WHEN user_name = :u THEN 1 ELSE 0 END) AS mes_appels, max(created_at) AS dernier_appel
        FROM {p.t('tool_calls')}
        WHERE agent_id IN ({inlist}) AND created_at >= current_timestamp() - make_interval(0, 0, 0, :d)
        GROUP BY agent_id""", params)
    by = {x["agent_id"]: x for x in r["rows"]}
    out = []
    for a in agents:
        x = by.get(a["agent_id"], {})
        n, ok = int(x.get("appels") or 0), int(x.get("succes") or 0)
        out.append({"agent": a.get("name"), "conversations": int(x.get("conversations") or 0), "appels": n,
                    "taux_succes": round(100 * ok / n, 1) if n else None, "mes_appels": int(x.get("mes_appels") or 0),
                    "dernier_appel": str(x.get("dernier_appel") or "") or None})
    return {"periode_jours": int(jours), "agents": out, "source": "journal des appels d'outils"}


def diagnostiquer_echec(ctx: ToolContext, agent: str = "", outil: str = "", jours: int = 7) -> dict:
    p = _p(ctx)
    visible = {a["agent_id"]: a for a in _visible_agents(p)}
    if agent:
        ids = [_find_agent(p, agent)["agent_id"]]
    else:
        ids = list(visible)
    if not ids:
        return {"erreurs": []}
    params = {f"a{i}": x for i, x in enumerate(ids)} | {"d": int(jours)}
    inlist = ", ".join(f":a{i}" for i in range(len(ids)))
    cond = ""
    if outil:
        cond, params["t"] = " AND tool_id = :t", outil
    r = p.repo.sql.query(f"""
        SELECT agent_id, tool_id, status, error, arguments, user_name, created_at FROM {p.t('tool_calls')}
        WHERE agent_id IN ({inlist}) AND status <> 'succes'{cond}
          AND created_at >= current_timestamp() - make_interval(0, 0, 0, :d)
        ORDER BY created_at DESC LIMIT 200""", params)
    groups: dict = {}
    hidden = 0
    for x in r["rows"]:
        a = visible.get(x["agent_id"])
        detail = _can_detail(p, a, x.get("user_name"))
        msg = (x.get("error") or "(sans message)")[:300] if detail else "(détail réservé à l'auteur de l'appel et au propriétaire de l'agent)"
        hidden += 0 if detail else 1
        k = (x["agent_id"], x["tool_id"], x["status"], msg)
        g = groups.setdefault(k, {"agent": (a or {}).get("name", x["agent_id"]),
                                  "appel": "@" + ((a or {}).get("handle") or ""), "outil": x["tool_id"],
                                  "statut": x["status"], "message": msg, "occurrences": 0,
                                  "dernier": str(x["created_at"]), "exemple_arguments": None})
        g["occurrences"] += 1
        if detail and g["exemple_arguments"] is None:
            g["exemple_arguments"] = (x.get("arguments") or "")[:500]
    rows = sorted(groups.values(), key=lambda g: -g["occurrences"])[:20]
    totals: dict = {}
    for x in r["rows"]:
        name = visible.get(x["agent_id"], {}).get("name", x["agent_id"])
        totals[(name, x["tool_id"])] = totals.get((name, x["tool_id"]), 0) + 1
    return {"periode_jours": int(jours), "nombre_echecs": len(r["rows"]),
            "totaux_par_agent_et_outil": [{"agent": a, "outil": t, "echecs": n}
                                          for (a, t), n in sorted(totals.items(), key=lambda kv: -kv[1])],
            "groupes": rows, "details_masques": hidden,
            "note": "Utiliser les totaux fournis tels quels ; ne pas additionner les groupes à la main."}


# --- Données (droits Unity Catalog de l'utilisateur) --------------------------------------------------
def explorer_donnees(ctx: ToolContext, action: str, table: str = "", catalog: str = "", schema: str = "",
                     limite: int = 10) -> dict:
    _p(ctx)
    from tools import sql_tools, uc_tools
    from tools.common import split_name, quote
    if action == "lister_tables":
        if not (catalog and schema):
            raise ToolError("catalog et schema requis pour lister les tables.")
        return uc_tools.list_tables(ctx, catalog, schema)
    if not table:
        raise ToolError("table requise (catalog.schema.table).")
    if action == "decrire":
        return uc_tools.describe_table(ctx, table)
    if action == "profiler":
        return uc_tools.get_table_profile(ctx, table, 30)
    if action == "apercu":
        return sql_tools.execute_sql(ctx, f"SELECT * FROM {quote(split_name(table, 3))}", max(1, min(int(limite), 50)))
    raise ToolError("Action inconnue : lister_tables, decrire, profiler ou apercu.")
