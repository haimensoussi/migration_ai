"""Outils HakimAI Agent Mesh : trouver les équipes et agents d'un domaine, transmettre une question à une équipe.

Deux niveaux de délégation au plus : HakimAI -> chef de l'équipe -> agents membres (orchestrateur existant, qui
refuse qu'un membre délègue à son tour). Données lues avec les droits de l'utilisateur ; une action soumise à
validation humaine n'est jamais exécutée par ce relais.
"""
from __future__ import annotations

import json

from backend import mesh_org as M
from backend.tool_registry import ToolContext, ToolError
from tools.hakim_tools import _p

MAX_QUESTION = 4000


def _contracts(p) -> dict:
    if callable(p.contracts):
        return p.contracts() or {}
    if isinstance(p.contracts, dict):
        return p.contracts
    from backend.agent_contracts import ContractRepository
    return ContractRepository(p.repo.sql, p.repo.s).latest_all()


def load_mesh(p) -> tuple[dict, list[dict], dict]:
    agents = p.repo.list_agents()
    contracts = _contracts(p)
    mesh = M.build_mesh(agents, p.teams.list_teams(), contracts, M.domain_names(p.repo.sql, p.t("domains")))
    return mesh, agents, contracts


def trouver_agents(ctx: ToolContext, capacite: str = "", domaine: str = "") -> dict:
    p = _p(ctx)
    mesh, agents, contracts = load_mesh(p)
    names = [d["domaine"] for d in mesh["domaines"]]
    if domaine and M.norm(domaine) not in {M.norm(n) for n in names}:
        raise ToolError(f"Domaine inconnu : « {domaine} ». Domaines : {', '.join(names)}.")
    found = M.search(mesh, agents, contracts, capacite, domaine)
    return {**found, "domaines": M.summary(mesh),
            "agents_hors_equipe": mesh["hors_equipe"], "agents_sans_domaine": mesh["sans_domaine"],
            "regle": ("Seules les équipes joignables peuvent être interrogées avec demander_a_equipe. Un agent hors "
                      "équipe s'utilise dans Chat & Test. Si a_departager n'est pas vide, demande à l'utilisateur.")}


def _plain(ev) -> dict:
    return {"tool_id": ev.tool_id, "arguments": ev.arguments, "status": ev.status,
            "result": json.loads(json.dumps(ev.result, default=str)) if ev.result is not None else None,
            "error": ev.error, "duration_ms": ev.duration_ms}


def demander_a_equipe(ctx: ToolContext, equipe: str, question: str) -> dict:
    p = _p(ctx)
    question = (question or "").strip()
    if not question:
        raise ToolError("Question vide : formulez une question autonome pour l'équipe.")
    mesh, _, _ = load_mesh(p)
    team = M.find_team(mesh, equipe)
    if not team:
        avail = [f"{t['equipe']} ({t['domaine']})" for t in M.teams_of(mesh) if t["joignable"]]
        raise ToolError(f"Équipe publiée introuvable : « {equipe} ». Équipes joignables : "
                        f"{', '.join(avail) or 'aucune'}.")
    if not team["joignable"]:
        raise ToolError(f"L'équipe « {team['equipe']} » n'a pas de chef publié : elle ne peut pas être interrogée.")
    if p.team_runner is None:
        raise ToolError("La délégation à une équipe n'est disponible que sur la page HakimAI.")
    cfg = p.repo.get_config(team["destinataire"])
    if cfg is None:
        raise ToolError(f"Configuration du chef de l'équipe « {team['equipe']} » introuvable.")
    rt, exec_cfg, warnings = p.team_runner(cfg)
    res = rt.run(exec_cfg, [{"role": "user", "content": question[:MAX_QUESTION]}])
    consulted = list(dict.fromkeys(
        (e.result or {}).get("agent_affiche") or (e.result or {}).get("agent")
        for e in res.events if e.tool_id == "ask_agent" and e.status == "succes" and isinstance(e.result, dict)))
    route = ["HakimAI", team["domaine"], team["equipe"], f"{cfg.name} (chef)"] + [c for c in consulted if c]
    base = {"equipe": team["equipe"], "domaine": team["domaine"], "chef": cfg.name, "acheminement": " → ".join(route),
            "agents_consultes": [c for c in consulted if c], "avertissements": warnings,
            "_ui_mesh": {"acheminement": " → ".join(route), "events": [_plain(e) for e in res.events]}}
    if res.pending:
        return {**base, "statut": "validation_requise",
                "message": (f"Le chef de l'équipe demande une validation humaine pour l'outil {res.pending['tool']} : "
                            "l'action n'est pas exécutée par délégation. Utilisez l'équipe dans Chat & Test.")}
    return {**base, "statut": "succes", "reponse": res.final_text or "", "latence_ms": res.latency_ms}
