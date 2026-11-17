"""Persistance Unity Catalog (tables Delta) des agents, versions, outils et historiques.

Écritures réalisées par le service principal de l'App (MODIFY sur le schéma ai_studio uniquement).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from backend.agent_runtime import AgentConfig, ToolEvent
from backend.config import Settings
from backend.sql_client import SqlClient
from backend.tool_registry import ToolSpec


# Outils de restitution ajoutés à tout nouvel agent (Agent Builder, concepteur IA, HakimAI, équipes) :
# lecture seule, droits de l'utilisateur, chiffres calculés par l'application.
DEFAULT_TOOLS = ("render_chart", "render_kpi", "generate_report")


def with_default_tools(tool_ids: list | None) -> list:
    """Ajoute les outils par défaut absents, sans doublon ni changement de l'ordre existant."""
    ids = list(tool_ids or [])
    return ids + [t for t in DEFAULT_TOOLS if t not in ids]


def _loads(v: Any, default):
    try:
        return json.loads(v) if v else default
    except (TypeError, json.JSONDecodeError):
        return default


class AgentRepository:
    def __init__(self, sql: SqlClient, settings: Settings):
        self.sql, self.s = sql, settings

    # -- Agents ---------------------------------------------------------------
    def list_agents(self) -> list[dict]:
        r = self.sql.query(f"""
            SELECT a.agent_id, a.name, a.description, a.icon, a.category, a.status, a.current_version,
                   a.owner, a.updated_at, a.handle, a.persona, a.tagline, a.call_examples, a.aliases,
                   v.model_endpoint, v.tool_ids, v.knowledge_tables
            FROM {self.s.table('agents')} a
            LEFT JOIN {self.s.table('agent_versions')} v
              ON a.agent_id = v.agent_id AND a.current_version = v.version
            WHERE a.status <> 'archive'
            ORDER BY a.updated_at DESC""")
        for a in r["rows"]:
            a["current_version"] = int(a["current_version"])
            a["tool_ids"] = _loads(a["tool_ids"], [])
            a["knowledge_tables"] = _loads(a["knowledge_tables"], [])
            a["call_examples"] = _loads(a.get("call_examples"), [])
            a["aliases"] = _loads(a.get("aliases"), [])
        return r["rows"]

    def set_persona(self, agent_id: str, persona: dict) -> None:
        """Identité de l'agent (prénom = colonne name ; nom d'appel, rôle, accroche, exemples, anciens noms)."""
        from backend import personas
        p = personas.normalize(persona)
        errs = personas.validate(p, self.list_agents() + self._team_keys(), agent_id)
        if errs:
            raise ValueError(" ".join(errs))
        self.sql.execute(f"""
            UPDATE {self.s.table('agents')} SET handle = :handle, persona = :persona, tagline = :tagline,
                   call_examples = :call_examples, aliases = :aliases, updated_at = current_timestamp()
            WHERE agent_id = :agent_id""", {"agent_id": agent_id, **personas.to_row(p)})

    def get_agent(self, agent_id: str) -> dict | None:
        return next((a for a in self.list_agents() if a["agent_id"] == agent_id), None)

    def get_config(self, agent_id: str, version: int | None = None) -> AgentConfig | None:
        r = self.sql.query(f"""
            SELECT a.name, v.* FROM {self.s.table('agents')} a
            JOIN {self.s.table('agent_versions')} v ON a.agent_id = v.agent_id
            WHERE a.agent_id = :agent_id AND v.version = coalesce(CAST(:version AS INT), a.current_version)""",
            {"agent_id": agent_id, "version": version})
        if not r["rows"]:
            return None
        v = r["rows"][0]
        return AgentConfig(agent_id=agent_id, version=int(v["version"]), name=v["name"],
                           model_endpoint=v["model_endpoint"], instructions=v["instructions"],
                           tool_ids=_loads(v["tool_ids"], []), knowledge_tables=_loads(v["knowledge_tables"], []),
                           temperature=float(v["temperature"]) if v["temperature"] is not None else None,
                           max_iterations=int(v["max_iterations"] or self.s.max_iterations))

    def _insert_version(self, agent_id: str, version: int, cfg: dict, user: str) -> None:
        self.sql.execute(f"""
            INSERT INTO {self.s.table('agent_versions')}
            (agent_id, version, model_endpoint, instructions, tool_ids, knowledge_tables, temperature,
             max_iterations, created_by, created_at)
            VALUES (:agent_id, :version, :model, :instructions, :tools, :tables, :temperature, :max_it, :user,
                    current_timestamp())""",
            {"agent_id": agent_id, "version": version, "model": cfg["model_endpoint"],
             "instructions": cfg["instructions"], "tools": json.dumps(cfg.get("tool_ids", [])),
             "tables": json.dumps(cfg.get("knowledge_tables", [])),
             "temperature": float(cfg.get("temperature", 0.1)),
             "max_it": int(cfg.get("max_iterations", self.s.max_iterations)), "user": user})

    def create_agent(self, meta: dict, cfg: dict, user: str, status: str = "brouillon") -> str:
        """La version est écrite avant l'en-tête : un échec intermédiaire ne laisse qu'une version orpheline."""
        agent_id = uuid.uuid4().hex
        self._check_persona(meta, agent_id)
        cfg = {**cfg, "tool_ids": with_default_tools(cfg.get("tool_ids"))}
        self._insert_version(agent_id, 1, cfg, user)
        self.sql.execute(f"""
            INSERT INTO {self.s.table('agents')}
            (agent_id, name, description, icon, category, status, current_version, owner, created_at, updated_at)
            VALUES (:agent_id, :name, :description, :icon, :category, :status, 1, :owner,
                    current_timestamp(), current_timestamp())""",
            {"agent_id": agent_id, "name": meta["name"], "description": meta.get("description", ""),
             "icon": meta.get("icon", ""), "category": meta.get("category", "Général"),
             "status": status, "owner": user})
        if meta.get("handle"):
            self.set_persona(agent_id, meta)
        return agent_id

    def _team_keys(self) -> list[dict]:
        """Noms d'appel des équipes actives, réservés face aux agents (table absente : aucune équipe)."""
        try:
            rows = self.sql.query(f"SELECT team_id, name, handle FROM {self.s.table('teams')} "
                                  "WHERE status <> 'archive'")["rows"]
            return [{"agent_id": "team:" + r["team_id"], "name": f"Équipe {r['name']}", "handle": r["handle"]}
                    for r in rows if r.get("team_id") and r.get("handle")]
        except Exception:  # noqa: BLE001
            return []

    def _check_persona(self, meta: dict, agent_id: str) -> None:
        if meta.get("handle"):
            from backend import personas
            errs = personas.validate(personas.normalize(meta), self.list_agents() + self._team_keys(), agent_id)
            if errs:
                raise ValueError(" ".join(errs))

    def save_version(self, agent_id: str, meta: dict, cfg: dict, user: str, status: str | None = None) -> int:
        r = self.sql.query(f"SELECT coalesce(max(version), 0) + 1 AS v FROM {self.s.table('agent_versions')} "
                           "WHERE agent_id = :agent_id", {"agent_id": agent_id})
        version = int(r["rows"][0]["v"])
        self._check_persona(meta, agent_id)
        self._insert_version(agent_id, version, cfg, user)
        self.sql.execute(f"""
            UPDATE {self.s.table('agents')} SET name = :name, description = :description, icon = :icon,
                   category = :category, status = coalesce(:status, status), current_version = :version,
                   updated_at = current_timestamp()
            WHERE agent_id = :agent_id""",
            {"agent_id": agent_id, "name": meta["name"], "description": meta.get("description", ""),
             "icon": meta.get("icon", ""), "category": meta.get("category", "Général"),
             "status": status, "version": version})
        if meta.get("handle"):
            self.set_persona(agent_id, meta)
        return version

    def set_status(self, agent_id: str, status: str) -> None:
        if status not in ("brouillon", "publie", "archive"):
            raise ValueError(status)
        self.sql.execute(f"UPDATE {self.s.table('agents')} SET status = :status, updated_at = current_timestamp() "
                         "WHERE agent_id = :agent_id", {"agent_id": agent_id, "status": status})

    # -- Outils ---------------------------------------------------------------
    def list_tools(self) -> list[ToolSpec]:
        r = self.sql.query(f"SELECT * FROM {self.s.table('tools')} ORDER BY category, tool_id")
        return [ToolSpec.from_row(x) for x in r["rows"]]

    def upsert_tool(self, spec: ToolSpec) -> None:
        row = spec.to_row()
        cols = list(row.keys())
        src = ", ".join(f":{c} AS {c}" for c in cols)
        sets = ", ".join(f"t.{c} = s.{c}" for c in cols if c != "tool_id")
        self.sql.execute(f"""
            MERGE INTO {self.s.table('tools')} t
            USING (SELECT {src}, current_timestamp() AS updated_at) s ON t.tool_id = s.tool_id
            WHEN MATCHED THEN UPDATE SET {sets}, t.updated_at = s.updated_at
            WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}, updated_at)
              VALUES ({', '.join('s.' + c for c in cols)}, s.updated_at)""", row)

    # -- Outils créés -----------------------------------------------------------
    def tool_owner(self, tool_id: str) -> tuple[bool, str]:
        exists, owner, _ = self._tool_info(tool_id)
        return exists, owner

    def _tool_info(self, tool_id: str) -> tuple[bool, str, bool]:
        r = self.sql.query(f"SELECT executor, coalesce(owner, '') AS owner, read_only FROM {self.s.table('tools')} "
                           "WHERE tool_id = :t", {"t": tool_id})
        if not r["rows"]:
            return False, "", True
        row = r["rows"][0]
        ro = row["read_only"] if isinstance(row["read_only"], bool) else str(row["read_only"]).lower() == "true"
        if not str(row["executor"]).startswith("tools.custom_tools:"):
            return True, "__integre__", ro
        return True, row["owner"], ro

    def _check_publish(self, read_only: bool, user: str) -> None:
        """Un outil qui écrit ou envoie des données ne peut être publié que par un administrateur des outils."""
        if not read_only and user.lower() not in set(getattr(self.s, "tool_admins", ()) or ()):
            raise PermissionError("Cet outil écrit ou envoie des données : seul un administrateur des outils "
                                  "(AI_STUDIO_TOOL_ADMINS) peut le publier. Enregistrez-le en brouillon.")

    def save_custom_tool(self, spec: ToolSpec, user: str, test_result: dict, note: str = "") -> int:
        """Enregistre une nouvelle version d'un outil créé. Refuse d'écraser un outil intégré ou d'un autre utilisateur."""
        if not spec.executor.startswith("tools.custom_tools:"):
            raise ValueError("Seuls les outils créés (exécuteurs génériques) peuvent être enregistrés ici.")
        exists, owner = self.tool_owner(spec.tool_id)
        if exists and owner != user:
            raise PermissionError(f"L'identifiant « {spec.tool_id} » appartient à un autre outil.")
        if spec.status == "publie":
            self._check_publish(spec.read_only, user)
        r = self.sql.query(f"SELECT coalesce(max(version), 0) + 1 AS v FROM {self.s.table('tool_versions')} "
                           "WHERE tool_id = :t", {"t": spec.tool_id})
        v = int(r["rows"][0]["v"])
        from dataclasses import replace
        spec = replace(spec, version=str(v), owner=user)
        self.sql.execute(f"INSERT INTO {self.s.table('tool_versions')} "
                         "(tool_id, version, spec, test_result, note, created_by, created_at) "
                         "VALUES (:t, :v, :spec, :test, :note, :u, current_timestamp())",
                         {"t": spec.tool_id, "v": v, "spec": json.dumps(spec.to_row(), ensure_ascii=False),
                          "test": json.dumps(test_result, ensure_ascii=False, default=str)[:20000],
                          "note": note[:500], "u": user})
        self.upsert_tool(spec)
        return v

    def set_tool_status(self, tool_id: str, status: str, user: str) -> None:
        if status not in ("brouillon", "publie", "retire"):
            raise ValueError(f"Statut inconnu : {status}")
        exists, owner, read_only = self._tool_info(tool_id)
        if not exists or owner != user:
            raise PermissionError("Seul le propriétaire d'un outil créé peut changer son statut.")
        if status == "publie":
            self._check_publish(read_only, user)
        self.sql.execute(f"UPDATE {self.s.table('tools')} SET status = :s, updated_at = current_timestamp() "
                         "WHERE tool_id = :t AND owner = :u", {"s": status, "t": tool_id, "u": user})

    def tool_versions(self, tool_id: str) -> list[dict]:
        r = self.sql.query(f"SELECT version, spec, test_result, note, created_by, created_at "
                           f"FROM {self.s.table('tool_versions')} WHERE tool_id = :t ORDER BY version DESC",
                           {"t": tool_id})
        return r["rows"]

    # -- Historique -----------------------------------------------------------
    def next_message_index(self, conversation_id: str) -> int:
        r = self.sql.query(f"SELECT coalesce(max(message_index), -1) + 1 AS i FROM {self.s.table('conversations')} "
                           "WHERE conversation_id = :c", {"c": conversation_id})
        return int(r["rows"][0]["i"])

    def log_messages(self, conversation_id: str, cfg: AgentConfig, user: str, messages: list[dict],
                     start_index: int, latency_ms: int | None = None) -> int:
        rows, params = [], {"c": conversation_id, "a": cfg.agent_id, "v": cfg.version, "u": user}
        # La latence du tour n'est portée que par la réponse finale (dernier message assistant sans appel d'outil)
        final = max((i for i, m in enumerate(messages) if m["role"] == "assistant" and not m.get("tool_calls")),
                    default=None)
        for i, m in enumerate(messages):
            content = m.get("content") or ""
            if m.get("tool_calls"):
                content = json.dumps({"content": content, "tool_calls": m["tool_calls"]}, ensure_ascii=False)
            params.update({f"i{i}": start_index + i, f"r{i}": m["role"], f"t{i}": content[:20000],
                           f"l{i}": latency_ms if i == final else None})
            rows.append(f"(:c, CAST(:i{i} AS INT), :a, CAST(:v AS INT), :u, :r{i}, :t{i}, CAST(:l{i} AS BIGINT), current_timestamp())")
        if rows:
            self.sql.execute(f"INSERT INTO {self.s.table('conversations')} (conversation_id, message_index, agent_id, "
                             "agent_version, user_name, role, content, latency_ms, created_at) VALUES "
                             + ", ".join(rows), params)
        return start_index + len(rows)

    def log_tool_call(self, conversation_id: str, agent_id: str, user: str, ev: ToolEvent) -> None:
        res = ({k: v for k, v in ev.result.items() if not str(k).startswith("_ui")}   # points de carte non journalisés
               if isinstance(ev.result, dict) else ev.result)
        preview = json.dumps(res, ensure_ascii=False, default=str)[:4000] if res is not None else None
        args = ev.arguments
        if ev.tool_id == "http_call" and isinstance(args, dict) and args.get("url"):
            from tools.http_tools import mask_url        # signature / jeton de l'URL jamais journalisés
            args = {**args, "url": mask_url(str(args["url"]))}
        self.sql.execute(f"""
            INSERT INTO {self.s.table('tool_calls')} (call_id, conversation_id, agent_id, tool_id, arguments, status,
              result_preview, error, duration_ms, user_name, created_at)
            VALUES (:id, :c, :a, :t, :args, :st, CAST(:p AS STRING), CAST(:e AS STRING), CAST(:d AS BIGINT), :u, current_timestamp())""",
            {"id": ev.call_id, "c": conversation_id, "a": agent_id, "t": ev.tool_id,
             "args": json.dumps(args, ensure_ascii=False, default=str), "st": ev.status,
             "p": preview, "e": ev.error, "d": int(ev.duration_ms), "u": user})

    def recent_agent_errors(self, agent_id: str, limit: int = 15) -> list[dict]:
        r = self.sql.query(f"""
            SELECT tool_id, status, error, created_at FROM {self.s.table('tool_calls')}
            WHERE agent_id = :a AND status <> 'succes' ORDER BY created_at DESC LIMIT {int(limit)}""", {"a": agent_id})
        return r["rows"]

    def log_generation(self, kind: str, user: str, prompt: str, scope: str | None, model_endpoint: str,
                       proposal: dict | None = None, draft: dict | None = None, warnings: list | None = None,
                       status: str = "propose", error: str | None = None, latency_ms: int | None = None) -> str:
        gid = uuid.uuid4().hex
        self.sql.execute(f"""
            INSERT INTO {self.s.table('generation_log')} (generation_id, kind, user_name, prompt, scope,
              model_endpoint, proposal, draft, warnings, status, error, latency_ms, created_at)
            VALUES (:id, :k, :u, :p, CAST(:sc AS STRING), :m, CAST(:pr AS STRING), CAST(:d AS STRING),
                    CAST(:w AS STRING), :st, CAST(:e AS STRING), CAST(:l AS BIGINT), current_timestamp())""",
            {"id": gid, "k": kind, "u": user, "p": prompt[:20000], "sc": scope, "m": model_endpoint,
             "pr": json.dumps(proposal, ensure_ascii=False)[:20000] if proposal is not None else None,
             "d": json.dumps(draft, ensure_ascii=False)[:20000] if draft is not None else None,
             "w": json.dumps(warnings or [], ensure_ascii=False), "st": status,
             "e": (error or "")[:4000] or None, "l": latency_ms})
        return gid

    # -- Indicateurs ----------------------------------------------------------
    def dashboard_stats(self) -> dict:
        r = self.sql.query(f"""
            SELECT
              (SELECT count(*) FROM {self.s.table('agents')} WHERE status <> 'archive') AS agents,
              (SELECT count(*) FROM {self.s.table('agents')} WHERE status = 'publie') AS publies,
              (SELECT count(*) FROM {self.s.table('agents')} WHERE status = 'brouillon') AS brouillons,
              (SELECT count(*) FROM {self.s.table('tools')} WHERE status = 'publie') AS outils,
              (SELECT count(DISTINCT conversation_id) FROM {self.s.table('conversations')}) AS conversations""")
        return {k: int(v or 0) for k, v in r["rows"][0].items()}

    def recent_tool_calls(self, limit: int = 20) -> list[dict]:
        r = self.sql.query(f"""
            SELECT c.created_at, coalesce(a.name, c.agent_id) AS agent, c.tool_id, c.status, c.duration_ms,
                   c.user_name, c.error
            FROM {self.s.table('tool_calls')} c LEFT JOIN {self.s.table('agents')} a ON a.agent_id = c.agent_id
            ORDER BY c.created_at DESC LIMIT {int(limit)}""")
        return r["rows"]

    def tool_call_stats(self) -> list[dict]:
        r = self.sql.query(f"""
            SELECT tool_id, count(*) AS appels, sum(CASE WHEN status = 'succes' THEN 1 ELSE 0 END) AS succes,
                   sum(CASE WHEN status = 'erreur' THEN 1 ELSE 0 END) AS erreurs,
                   sum(CASE WHEN status = 'refuse' THEN 1 ELSE 0 END) AS refus,
                   round(avg(duration_ms)) AS duree_moy_ms, max(created_at) AS dernier_appel
            FROM {self.s.table('tool_calls')} GROUP BY tool_id ORDER BY appels DESC""")
        return r["rows"]

    def turn_latency_stats(self) -> list[dict]:
        r = self.sql.query(f"""
            SELECT to_date(c.created_at) AS jour, coalesce(a.name, c.agent_id) AS agent, count(*) AS reponses,
                   round(avg(c.latency_ms)) AS latence_moy_ms, max(c.latency_ms) AS latence_max_ms
            FROM {self.s.table('conversations')} c LEFT JOIN {self.s.table('agents')} a ON a.agent_id = c.agent_id
            WHERE c.role = 'assistant' AND c.latency_ms IS NOT NULL
            GROUP BY ALL ORDER BY jour DESC, reponses DESC LIMIT 100""")
        return r["rows"]
