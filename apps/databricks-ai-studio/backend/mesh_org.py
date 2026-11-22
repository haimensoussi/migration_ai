"""Agent Mesh par domaine (AM-02, AM-03) : annuaire domaine -> équipes -> agents et recherche par capacité.

Fonctions pures (aucune lecture de table) : les appelants fournissent agents, équipes, fiches contrat et domaines.
Règles (aperçu validé le 22/11/2026, docs/maquette/DISCOVERY_agent_mesh_domaines_apercu.html) :
- un domaine a plusieurs équipes ; une équipe appartient à un domaine (sa filière) et a plusieurs agents ;
- le domaine d'un agent est celui de sa fiche contrat ; un agent peut être membre de plusieurs équipes ;
- seules les équipes publiées dont le destinataire (chef, ou membre unique) est publié sont joignables par HakimAI.
"""
from __future__ import annotations

import json
import re
import unicodedata

from backend import teams as T
from backend.agent_contracts import DOMAINES

PUBLISHED = "publie"
STOP = {"les", "des", "une", "pour", "par", "sur", "dans", "avec", "aux", "est", "sont", "que", "qui", "quoi",
        "quel", "quels", "quelle", "quelles", "leur", "leurs", "ses", "son", "sa", "mon", "mes", "nos", "vos",
        "cette", "ces", "cet", "tout", "tous", "toutes", "plus", "moins", "comment", "combien", "faire", "donne",
        "donner", "agent", "agents", "equipe", "equipes", "the", "and", "entre", "chaque", "elle", "ils", "nous",
        "vous", "pas", "ont", "avoir", "etre", "fait", "via", "selon", "afin", "lors", "depuis", "dont"}
PREFIX = 5   # deux mots égaux sur leurs 5 premières lettres sont considérés identiques (anomalie / anomalies)


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def tokens(text) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", norm(text)) if len(w) >= 3 and w not in STOP}


def _same(a: str, b: str) -> bool:
    return a == b or (len(a) >= PREFIX and len(b) >= PREFIX and a[:PREFIX] == b[:PREFIX])


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, default=str)


def order_domains(names: list[str] | None) -> list[str]:
    """Domaines dans l'ordre de référence (Supply Chain, PTE, UDR, Transverse), autres ensuite ; défaut : DOMAINES."""
    names = [n for n in dict.fromkeys(names or []) if n] or list(DOMAINES)
    rank = {d: i for i, d in enumerate(DOMAINES)}
    return sorted(names, key=lambda n: (rank.get(n, len(rank)), n))


def domain_names(sql, table: str) -> list[str]:
    """Domaines actifs de la table domains (T201) ; liste de référence si la table est illisible."""
    try:
        rows = sql.query(f"SELECT name FROM {table} WHERE status = 'actif'")["rows"]
    except Exception:  # noqa: BLE001
        rows = []
    return order_domains([r["name"] for r in rows])


def agent_domain(contracts: dict, agent_id: str, domains: list[str]) -> str:
    d = (contracts.get(agent_id) or {}).get("domaine") or ""
    return d if d in domains else ""


def reachable(team: dict, by_id: dict) -> str | None:
    """Agent destinataire de l'équipe s'il est publié (chef, ou membre unique), sinon None."""
    if team.get("status") != PUBLISHED:
        return None
    target = T.target_agent(team)
    return target if target and (by_id.get(target) or {}).get("status") == PUBLISHED else None


def build_mesh(agents: list[dict], teams: list[dict], contracts: dict, domains: list[str] | None = None) -> dict:
    """Annuaire : domaines -> équipes publiées -> agents, et les écarts à corriger."""
    names = list(domains or DOMAINES)
    by_id = {a["agent_id"]: a for a in agents}
    name = lambda i: (by_id.get(i) or {}).get("name") or i  # noqa: E731
    published = [a for a in agents if a.get("status") == PUBLISHED]
    live = [t for t in teams if t.get("status") != "archive"]
    in_team: dict[str, list[str]] = {}
    out_domains, incoherent = [], []
    for d in names:
        entries = []
        for t in (x for x in live if x.get("status") == PUBLISHED and x.get("filiere") == d):
            ids = ([t["lead_agent_id"]] if t.get("lead_agent_id") else []) + list(t.get("members") or [])
            for i in ids:
                in_team.setdefault(i, []).append(t["name"])
                dom = agent_domain(contracts, i, names)
                if dom != d:
                    incoherent.append({"agent_id": i, "agent": name(i), "equipe": t["name"], "domaine_equipe": d,
                                       "domaine_agent": dom or "(aucun)"})
            entries.append({
                "team_id": t["team_id"], "equipe": t["name"], "appel": "@" + (t.get("handle") or ""),
                "mission": t.get("mission") or "", "domaine": d,
                "chef": {"agent_id": t["lead_agent_id"], "nom": name(t["lead_agent_id"])} if t.get("lead_agent_id") else None,
                "membres": [{"agent_id": m, "nom": name(m), "statut": (by_id.get(m) or {}).get("status", "inconnu")}
                            for m in t.get("members") or []],
                "destinataire": reachable(t, by_id), "joignable": bool(reachable(t, by_id))})
        out_domains.append({
            "domaine": d, "equipes": entries,
            "equipes_en_preparation": [t["name"] for t in live if t.get("status") != PUBLISHED and t.get("filiere") == d],
            "agents_publies": sorted(a["name"] for a in published if agent_domain(contracts, a["agent_id"], names) == d)})
    return {
        "domaines": out_domains,
        "sans_domaine": sorted(a["name"] for a in published if not agent_domain(contracts, a["agent_id"], names)),
        "hors_equipe": sorted(a["name"] for a in published if a["agent_id"] not in in_team),
        "equipes_hors_domaine": sorted(t["name"] for t in live if t.get("status") == PUBLISHED
                                       and t.get("filiere") not in names),
        "incoherences": incoherent,
        "equipes_par_agent": in_team,
    }


def teams_of(mesh: dict, domaine: str = "") -> list[dict]:
    return [t for d in mesh["domaines"] if not domaine or norm(d["domaine"]) == norm(domaine) for t in d["equipes"]]


def find_team(mesh: dict, ref: str) -> dict | None:
    """Équipe publiée par identifiant, nom (sans accents ni casse) ou appel @handle."""
    r = norm(ref).lstrip("@").removeprefix("equipe ").strip()
    for t in teams_of(mesh):
        if r in (norm(t["team_id"]), norm(t["equipe"]), norm(t["appel"]).lstrip("@")):
            return t
    return None


def _agent_text(a: dict, contract: dict | None) -> str:
    c = contract or {}
    return " ".join(_text(x) for x in (a.get("name"), a.get("tagline"), a.get("description"), a.get("call_examples"),
                                       a.get("category"), c.get("perimetre"), c.get("donnees"),
                                       [x.get("id") for x in c.get("actions") or [] if isinstance(x, dict)]))


def _match(query: set[str], text: str) -> list[str]:
    words = tokens(text)
    return sorted(q for q in query if any(_same(q, w) for w in words))


def search(mesh: dict, agents: list[dict], contracts: dict, query: str = "", domaine: str = "", limit: int = 5) -> dict:
    """Équipes et agents publiés classés selon les mots de la demande retrouvés dans leur description.

    Score d'une équipe : mots trouvés dans son nom et sa mission (x2) + mots trouvés chez ses agents (x1).
    Sans mots utiles, toutes les équipes du domaine sont renvoyées (score 0).
    """
    q = tokens(query)
    by_id = {a["agent_id"]: a for a in agents}
    team_rows = []
    for t in teams_of(mesh, domaine):
        own = _match(q, f"{t['equipe']} {t['mission']}")
        ids = ([t["chef"]["agent_id"]] if t["chef"] else []) + [m["agent_id"] for m in t["membres"]]
        member_words = _match(q, " ".join(_agent_text(by_id.get(i) or {}, contracts.get(i)) for i in ids))
        score = 2 * len(own) + len(member_words)
        if q and not score:
            continue
        team_rows.append({"equipe": t["equipe"], "team_id": t["team_id"], "domaine": t["domaine"], "score": score,
                          "motif": sorted(set(own) | set(member_words)), "joignable": t["joignable"],
                          "mission": t["mission"], "chef": (t["chef"] or {}).get("nom"),
                          "membres": [m["nom"] for m in t["membres"]]})
    names = [d["domaine"] for d in mesh["domaines"]]
    agent_rows = []
    for a in agents:
        if a.get("status") != PUBLISHED:
            continue
        dom = agent_domain(contracts, a["agent_id"], names)
        if domaine and norm(dom) != norm(domaine):
            continue
        words = _match(q, _agent_text(a, contracts.get(a["agent_id"])))
        if q and not words:
            continue
        teams_in = mesh["equipes_par_agent"].get(a["agent_id"], [])
        agent_rows.append({"agent": a["name"], "domaine": dom or "(aucun)", "score": len(words), "motif": words,
                           "equipes": teams_in, "joignable_par_hakim": bool(teams_in),
                           "presentation": a.get("tagline") or a.get("description") or ""})
    team_rows.sort(key=lambda r: (-r["score"], r["equipe"]))
    agent_rows.sort(key=lambda r: (-r["score"], r["agent"]))
    top = [r for r in team_rows if r["joignable"]] if q else []    # sans mots utiles : aucune recommandation
    tie = len(top) >= 2 and top[0]["score"] == top[1]["score"]
    return {"mots_recherches": sorted(q), "domaine": domaine or "tous", "equipes": team_rows[:limit],
            "agents": agent_rows[:limit], "equipe_recommandee": None if tie or not top else top[0]["equipe"],
            "a_departager": [r["equipe"] for r in top if r["score"] == top[0]["score"]] if tie else []}


DASHED = 'style="rounded,dashed,filled"'


def _q(s) -> str:
    """Libellé DOT entre guillemets ; retour à la ligne conservé (\\n), 60 caractères par ligne au plus."""
    parts = [p.replace("\\", "\\\\").replace('"', '\\"')[:60] for p in str(s or "").split("\n")]
    return '"' + "\\n".join(parts) + '"'


def mesh_dot(mesh: dict, org: str = "SNCF Réseau") -> str:
    """Carte Graphviz : organisation -> domaines -> équipes (chef) -> agents membres."""
    lines = ["digraph G {", "rankdir=LR; bgcolor=transparent; nodesep=0.25; ranksep=0.6;",
             'node [fontname="Helvetica", fontsize=11, style="rounded,filled", shape=box, color="#4A1942"];',
             'edge [color="#7A3E9D"];', f'org [label={_q(org)}, fillcolor="#4A1942", fontcolor="white"];']
    agents_done = set()
    for i, d in enumerate(mesh["domaines"]):
        empty = not d["equipes"]
        label = _q(d["domaine"] + ("\n" + "aucune équipe" if empty else ""))
        look = (DASHED + ', fillcolor="#F6F6F8", fontcolor="#6b6b78"') if empty else 'fillcolor="#B0124F", fontcolor="white"'
        lines.append(f"d{i} [label={label}, {look}];")
        lines.append(f"org -> d{i};")
        for j, t in enumerate(d["equipes"]):
            tid = f"t{i}_{j}"
            chef = (t["chef"] or {}).get("nom")
            label = _q(t["equipe"] + ("\n" + "chef : " + chef if chef else ""))
            lines.append(f'{tid} [label={label}, fillcolor="#7A3E9D", fontcolor="white"];')
            lines.append(f"d{i} -> {tid};")
            for m in t["membres"]:
                aid = "a_" + re.sub(r"\W", "_", m["agent_id"])
                if aid not in agents_done:
                    look = 'fillcolor="#efe7f2"' if m["statut"] == PUBLISHED else DASHED + ', fillcolor="#F6F6F8"'
                    lines.append(f'{aid} [label={_q(m["nom"])}, {look}, fontcolor="#4A1942"];')
                    agents_done.add(aid)
                lines.append(f"{tid} -> {aid};")
    lines.append("}")
    return "\n".join(lines)


def summary(mesh: dict) -> list[dict]:
    """Une ligne par domaine : nombre d'équipes publiées, joignables, agents publiés."""
    return [{"domaine": d["domaine"], "equipes": len(d["equipes"]),
             "joignables": sum(1 for t in d["equipes"] if t["joignable"]), "agents_publies": len(d["agents_publies"]),
             "en_preparation": len(d["equipes_en_preparation"])} for d in mesh["domaines"]]
