"""Persistance des équipes (tables teams, team_members, team_history) et synchronisation du chef."""
from __future__ import annotations

import json
import uuid

from backend import teams as T
from backend.agent_repository import AgentRepository

LIVE_STATUSES = ("publie", "en_validation")
SYNC_NOTES = {"version": ", outils du chef mis à jour",
              "revalidation": ", outils du chef mis à jour : chef resoumis à validation",
              "brouillon": ", outils du chef mis à jour : chef repassé en brouillon (à resoumettre par son propriétaire)"}


class TeamRepository:
    def __init__(self, agents: AgentRepository, publication=None):
        """publication : PublicationService (resoumission du chef publié dont les outils changent)."""
        self.agents, self.sql, self.s = agents, agents.sql, agents.s
        self.publication = publication

    def admins(self) -> set[str]:
        return set(getattr(self.s, "team_admins", ()) or ()) or set(getattr(self.s, "tool_admins", ()) or ())

    def is_admin(self, user: str) -> bool:
        return user.lower() in self.admins()

    # -- lecture ----------------------------------------------------------------
    def list_teams(self, include_archived: bool = False) -> list[dict]:
        rows = self.sql.query(f"SELECT * FROM {self.s.table('teams')} ORDER BY name")["rows"]
        mem = self.sql.query(f"SELECT team_id, agent_id, role, is_primary, position FROM "
                             f"{self.s.table('team_members')} ORDER BY team_id, position")["rows"]
        out = []
        for r in rows:
            if r["status"] == "archive" and not include_archived:
                continue
            ms = [m for m in mem if m["team_id"] == r["team_id"] and m["role"] == "membre"]
            r["members"] = [m["agent_id"] for m in ms]
            r["primary"] = [m["agent_id"] for m in ms if str(m.get("is_primary")).lower() == "true"]
            out.append(r)
        return out

    def history(self, team_id: str) -> list[dict]:
        return self.sql.query(f"SELECT changed_at, changed_by, action, detail FROM {self.s.table('team_history')} "
                              "WHERE team_id = :t ORDER BY changed_at DESC LIMIT 50", {"t": team_id})["rows"]

    def activity(self, agent_ids: list[str], days: int = 30) -> dict:
        if not agent_ids:
            return {"conversations": 0, "appels": 0, "succes": 0}
        marks = ", ".join(f":a{i}" for i in range(len(agent_ids)))
        r = self.sql.query(f"""
            SELECT count(DISTINCT conversation_id) AS conversations, count(*) AS appels,
                   sum(CASE WHEN status = 'succes' THEN 1 ELSE 0 END) AS succes
            FROM {self.s.table('tool_calls')}
            WHERE agent_id IN ({marks}) AND created_at >= current_timestamp() - make_interval(0, 0, 0, {int(days)})""",
            {f"a{i}": a for i, a in enumerate(agent_ids)})["rows"]
        row = r[0] if r else {}
        return {k: int(row.get(k) or 0) for k in ("conversations", "appels", "succes")}

    # -- écriture ---------------------------------------------------------------
    def _can_edit(self, team: dict | None, user: str) -> bool:
        return team is None or team.get("owner") == user or self.is_admin(user)

    def save(self, data: dict, user: str, note: str = "") -> str:
        """Crée ou modifie une équipe. Une modification par un non-administrateur repasse l'équipe en brouillon."""
        t = T.normalize(data)
        teams = self.list_teams(include_archived=False)
        current = next((x for x in teams if x["team_id"] == t["team_id"]), None) if t["team_id"] else None
        if t["team_id"] and current is None:
            raise PermissionError("Équipe introuvable ou archivée.")
        if not self._can_edit(current, user):
            raise PermissionError("Seuls le créateur de l'équipe et les administrateurs peuvent la modifier.")
        agents = self.agents.list_agents()
        errs = T.validate(t, agents, teams)
        if errs:
            raise ValueError(" ".join(errs))
        status = "brouillon" if current is None else (current["status"] if self.is_admin(user) else "brouillon")
        if status == "publie":
            perr = T.publish_errors(t, agents)
            if perr:
                raise ValueError(" ".join(perr))
        tid = t["team_id"] or uuid.uuid4().hex
        params = {"id": tid, "name": t["name"], "handle": t["handle"], "mission": t["mission"], "filiere": t["filiere"],
                  "icon": t["icon"], "lead": t["lead_agent_id"], "owner_h": t["human_owner"] or None,
                  "status": status, "owner": current["owner"] if current else user}
        self.sql.execute(f"""
            MERGE INTO {self.s.table('teams')} d
            USING (SELECT :id AS team_id) s ON d.team_id = s.team_id
            WHEN MATCHED THEN UPDATE SET name = :name, handle = :handle, mission = :mission, filiere = :filiere,
                 icon = :icon, lead_agent_id = :lead, human_owner = :owner_h, status = :status,
                 updated_at = current_timestamp()
            WHEN NOT MATCHED THEN INSERT (team_id, name, handle, mission, filiere, icon, lead_agent_id, human_owner,
                 status, owner, created_at, updated_at)
                 VALUES (:id, :name, :handle, :mission, :filiere, :icon, :lead, :owner_h, :status, :owner,
                         current_timestamp(), current_timestamp())""", params)
        self.sql.execute(f"DELETE FROM {self.s.table('team_members')} WHERE team_id = :t", {"t": tid})
        rows = ([(t["lead_agent_id"], "chef", False, 0)] if t["lead_agent_id"] else []) + \
               [(m, "membre", m in t["primary"], i + 1) for i, m in enumerate(t["members"])]
        for aid, role, prim, pos in rows:
            self.sql.execute(f"INSERT INTO {self.s.table('team_members')} (team_id, agent_id, role, is_primary, "
                             "position, added_by, added_at) VALUES (:t, :a, :r, :p, :pos, :u, current_timestamp())",
                             {"t": tid, "a": aid, "r": role, "p": prim, "pos": pos, "u": user})
        synced = self._sync_lead(t, user)
        detail = note or ("Création" if current is None else "Modification") + \
            f" : {len(t['members'])} membre(s)" + SYNC_NOTES.get(synced, "")
        self._log(tid, user, "creation" if current is None else "modification", detail, {**t, "team_id": tid,
                                                                                           "status": status})
        return tid

    def _sync_lead(self, t: dict, user: str) -> str:
        """Le chef consulte exactement les membres de l'équipe (nouvelle version si la liste change).

        Renvoie "" (inchangé), "version" (chef en brouillon mis à jour), "revalidation" (chef publié resoumis
        à validation) ou "brouillon" (chef publié repassé en brouillon : son propriétaire doit le resoumettre).
        Une nouvelle version d'un chef publié n'est jamais publiée sans demande de validation (T102).
        """
        lead = t["lead_agent_id"]
        if not lead:
            return ""
        cfg, meta = self.agents.get_config(lead), self.agents.get_agent(lead)
        want = T.lead_tool_ids(cfg.tool_ids, t["members"])
        if want == cfg.tool_ids:
            return ""
        live = (meta or {}).get("status") in LIVE_STATUSES
        self.agents.save_version(lead, {k: meta.get(k) for k in ("name", "description", "icon", "category")},
                                 {"model_endpoint": cfg.model_endpoint, "instructions": cfg.instructions,
                                  "tool_ids": want, "knowledge_tables": cfg.knowledge_tables,
                                  "temperature": cfg.temperature, "max_iterations": cfg.max_iterations}, user)
        if not live:
            return "version"
        if self.publication is not None and (meta.get("owner") or "").lower() == user.lower():
            try:
                self.publication.submit(lead, user)
                return "revalidation"
            except ValueError:      # PublicationError (fiche contrat sans domaine...) : repli brouillon
                pass
        self.agents.set_status(lead, "brouillon")
        return "brouillon"

    def create_lead(self, data: dict, user: str) -> str:
        """Chef d'équipe prérempli, en brouillon, à relire avant publication."""
        t = T.normalize(data)
        agents = self.agents.list_agents()
        members = [a for a in agents if a["agent_id"] in t["members"]]
        handle = ("chef-" + t["handle"])[:20].rstrip("-_")
        meta = {"name": f"Chef {t['name']}"[:80], "description": f"Coordonne l'équipe {t['name']}.",
                "icon": "support_agent", "category": "Orchestration", "handle": handle, "persona": "chef d'équipe",
                "tagline": f"Je répartis vos questions entre {', '.join(m['name'] for m in members)}."[:90]}
        cfg = {"model_endpoint": self.s.default_model, "instructions": T.lead_instructions(t, members),
               "tool_ids": [T.AGENT_PREFIX + m["agent_id"] for m in members], "knowledge_tables": [],
               "temperature": 0.1, "max_iterations": 6}
        return self.agents.create_agent(meta, cfg, user, status="brouillon")

    def set_status(self, team_id: str, status: str, user: str) -> None:
        if status not in T.STATUSES:
            raise ValueError(status)
        team = next((x for x in self.list_teams(include_archived=True) if x["team_id"] == team_id), None)
        if team is None:
            raise PermissionError("Équipe introuvable.")
        if status == "publie":
            if not self.is_admin(user):
                raise PermissionError("Seul un administrateur des équipes peut publier une équipe.")
            perr = T.publish_errors(T.normalize(team), self.agents.list_agents())
            if perr:
                raise ValueError(" ".join(perr))
        elif not self._can_edit(team, user):
            raise PermissionError("Seuls le créateur de l'équipe et les administrateurs peuvent changer son statut.")
        self.sql.execute(f"UPDATE {self.s.table('teams')} SET status = :s, updated_at = current_timestamp() "
                         "WHERE team_id = :t", {"s": status, "t": team_id})
        action = {"publie": "publication", "brouillon": "retrait", "archive": "archivage"}[status]
        self._log(team_id, user, action, {"publie": "Équipe publiée", "brouillon": "Retour en brouillon",
                                          "archive": "Équipe archivée (agents conservés)"}[status],
                  {**T.normalize(team), "status": status})

    def _log(self, tid: str, user: str, action: str, detail: str, snap: dict) -> None:
        self.sql.execute(f"INSERT INTO {self.s.table('team_history')} (team_id, changed_at, changed_by, action, detail, "
                         "snapshot) VALUES (:t, current_timestamp(), :u, :a, :d, :s)",
                         {"t": tid, "u": user, "a": action, "d": detail[:500],
                          "s": json.dumps(snap, ensure_ascii=False, default=str)})
