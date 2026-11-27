"""EIA Core - persistance (tables eia_* de dataops_dev.ai_studio, compte de l'application).

Deux magasins au même contrat CRUD : MemoryEiaStore (tests) et SqlEiaStore (Delta via SqlClient).
Les règles (transitions, validation humaine, dédoublonnage, journal) sont dans EiaRepository, indépendant du magasin.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
from typing import Any, Callable

from backend.eia.contracts import ContractError, check_transition, new_id

# table -> (clés, colonnes, types particuliers). Types : ts = TIMESTAMP, d = DOUBLE, i = INT, j = JSON (STRING).
TABLES: dict[str, tuple[tuple[str, ...], tuple[str, ...], dict[str, str]]] = {
    "eia_runs": (("run_id",), ("run_id", "team_id", "trigger", "request", "requested_by", "status", "plan", "summary",
                               "error", "started_at", "ended_at"),
                 {"plan": "j", "started_at": "ts", "ended_at": "ts"}),
    "eia_run_steps": (("run_id", "step_id"), ("run_id", "step_id", "agent", "status", "attempts", "depends_on", "output",
                                              "issues", "error", "started_at", "ended_at", "duration_ms"),
                      {"attempts": "i", "depends_on": "j", "output": "j", "issues": "j", "started_at": "ts",
                       "ended_at": "ts", "duration_ms": "i"}),
    "eia_alerts": (("alert_id",), ("alert_id", "team_id", "run_id", "rule_id", "rule_status", "kind", "severity", "title",
                                   "message", "metric", "scope", "period", "observed", "threshold", "evidence",
                                   "fingerprint", "status", "occurrences", "first_seen_at", "last_seen_at", "decided_by",
                                   "decided_at"),
                   {"observed": "d", "threshold": "d", "evidence": "j", "occurrences": "i", "first_seen_at": "ts",
                    "last_seen_at": "ts", "decided_at": "ts"}),
    "eia_recommendations": (("reco_id",), ("reco_id", "team_id", "run_id", "title", "rationale", "priority", "based_on",
                                           "expected_impact", "assumptions", "risks", "status", "created_at",
                                           "decided_by", "decided_at", "decision_note"),
                            {"priority": "i", "based_on": "j", "assumptions": "j", "risks": "j", "created_at": "ts",
                             "decided_at": "ts"}),
    "eia_missions": (("mission_id",), ("mission_id", "team_id", "reco_id", "title", "objective", "owner", "due_date",
                                       "deliverables", "success_kpis", "status", "created_by", "created_at",
                                       "validated_by", "validated_at", "updated_at"),
                     {"deliverables": "j", "success_kpis": "j", "created_at": "ts", "validated_at": "ts",
                      "updated_at": "ts"}),
    "eia_mission_tasks": (("mission_id", "task_id"), ("mission_id", "task_id", "title", "owner", "due_date",
                                                      "deliverable", "depends_on", "status", "updated_by",
                                                      "updated_at", "required_skills", "estimated_hours"),
                          {"depends_on": "j", "updated_at": "ts", "required_skills": "j", "estimated_hours": "i"}),
    "eia_people": (("person_id",), ("person_id", "team_id", "full_name", "email", "job_title", "department", "region",
                                    "capacity_hours_week", "availability_pct", "status", "source", "updated_at"),
                   {"capacity_hours_week": "i", "availability_pct": "i", "updated_at": "ts"}),
    "eia_person_skills": (("person_id", "skill"), ("person_id", "skill", "level", "assessed_by", "updated_at"),
                          {"level": "i", "updated_at": "ts"}),
    "eia_assignments": (("assignment_id",), ("assignment_id", "mission_id", "task_id", "person_id", "rank", "score",
                                             "skill_score", "availability_score", "rationale", "gaps", "status",
                                             "proposed_by", "proposed_at", "decided_by", "decided_at"),
                        {"rank": "i", "score": "d", "skill_score": "d", "availability_score": "d", "gaps": "j",
                         "proposed_at": "ts", "decided_at": "ts"}),
    "eia_events": (("event_id",), ("event_id", "object_type", "object_id", "event_type", "actor", "payload",
                                   "created_at"), {"payload": "j", "created_at": "ts"}),
    "eia_team_configs": (("config_id",), ("config_id", "team_id", "version", "status", "name", "models", "config",
                                         "controls", "recette", "created_by", "created_at", "decided_by",
                                         "decided_at"),
                         {"models": "j", "config": "j", "controls": "j", "recette": "j", "created_at": "ts",
                          "decided_at": "ts"}),
    "eia_architectures": (("arch_id",), ("arch_id", "plan_id", "name", "status", "mesh", "eia", "deployment",
                                         "created_by", "created_at", "updated_by", "updated_at", "decided_by",
                                         "decided_at"),
                          {"mesh": "j", "eia": "j", "deployment": "j", "created_at": "ts", "updated_at": "ts",
                           "decided_at": "ts"}),
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _check(table: str, fields: dict) -> None:
    if table not in TABLES:
        raise ContractError(f"Table EIA inconnue : {table}")
    bad = [k for k in fields if k not in TABLES[table][1]]
    if bad:
        raise ContractError(f"Colonnes inconnues pour {table} : {bad}")


class MemoryEiaStore:
    """Magasin en mémoire (tests, démonstration hors Databricks)."""

    def __init__(self):
        self.data: dict[str, list[dict]] = {t: [] for t in TABLES}

    def insert(self, table: str, row: dict) -> None:
        _check(table, row)
        keys = TABLES[table][0]
        if self.get(table, {k: row.get(k) for k in keys}):
            raise ContractError(f"Clé déjà présente dans {table} : {[row.get(k) for k in keys]}")
        self.data[table].append({c: copy.deepcopy(row.get(c)) for c in TABLES[table][1]})

    def get(self, table: str, key: dict) -> dict | None:
        for r in self.data[table]:
            if all(r.get(k) == v for k, v in key.items()):
                return copy.deepcopy(r)
        return None

    def update(self, table: str, key: dict, fields: dict) -> None:
        _check(table, fields)
        for r in self.data[table]:
            if all(r.get(k) == v for k, v in key.items()):
                r.update(copy.deepcopy(fields))

    def find(self, table: str, where: dict | None = None, order_by: str | None = None, desc: bool = True,
             limit: int = 200) -> list[dict]:
        out = []
        for r in self.data[table]:
            ok = True
            for k, v in (where or {}).items():
                ok = ok and (r.get(k) in v if isinstance(v, (list, tuple, set)) else r.get(k) == v)
            if ok:
                out.append(copy.deepcopy(r))
        if order_by:
            out.sort(key=lambda x: (x.get(order_by) is None, x.get(order_by) or ""), reverse=desc)
        return out[:limit]


class SqlEiaStore:
    """Magasin Delta via SqlClient (paramètres nommés ; les valeurs reviennent en texte et sont reconverties)."""

    def __init__(self, sql: Any, table: Callable[[str], str]):
        self.sql, self.t = sql, table

    @staticmethod
    def _expr(col: str, kind: str | None, p: str) -> str:
        return {"ts": f"CAST(:{p} AS TIMESTAMP)", "d": f"CAST(:{p} AS DOUBLE)", "i": f"CAST(:{p} AS INT)"}.get(kind or "", f":{p}")

    @staticmethod
    def _out(table: str, row: dict) -> dict:
        types = TABLES[table][2]
        r = dict(row)
        for c, k in types.items():
            v = r.get(c)
            if v is None:
                continue
            if k == "d":
                r[c] = float(v)
            elif k == "i":
                r[c] = int(float(v))
            elif k == "ts":
                r[c] = str(v).replace("T", " ")[:19]
        return r

    def _sel(self, table: str) -> str:
        types = TABLES[table][2]
        return ", ".join(f"CAST({c} AS STRING) AS {c}" if types.get(c) == "ts" else c for c in TABLES[table][1])

    def insert(self, table: str, row: dict) -> None:
        _check(table, row)
        cols = [c for c in TABLES[table][1] if c in row]
        types = TABLES[table][2]
        vals = ", ".join(self._expr(c, types.get(c), f"v{i}") for i, c in enumerate(cols))
        self.sql.execute(f"INSERT INTO {self.t(table)} ({', '.join(cols)}) VALUES ({vals})",
                         {f"v{i}": row[c] for i, c in enumerate(cols)})

    def get(self, table: str, key: dict) -> dict | None:
        rows = self.find(table, key, limit=1)
        return rows[0] if rows else None

    def update(self, table: str, key: dict, fields: dict) -> None:
        _check(table, {**fields, **key})
        if not fields:
            return
        types = TABLES[table][2]
        sets = ", ".join(f"{c} = {self._expr(c, types.get(c), f's{i}')}" for i, c in enumerate(fields))
        cond = " AND ".join(f"{k} = :k{i}" for i, k in enumerate(key))
        params = {**{f"s{i}": v for i, v in enumerate(fields.values())}, **{f"k{i}": v for i, v in enumerate(key.values())}}
        self.sql.execute(f"UPDATE {self.t(table)} SET {sets} WHERE {cond}", params)

    def find(self, table: str, where: dict | None = None, order_by: str | None = None, desc: bool = True,
             limit: int = 200) -> list[dict]:
        _check(table, where or {})
        conds, params = [], {}
        for i, (k, v) in enumerate((where or {}).items()):
            if isinstance(v, (list, tuple, set)):
                names = [f"w{i}_{j}" for j in range(len(v))]
                conds.append(f"{k} IN ({', '.join(':' + n for n in names)})" if names else "FALSE")
                params.update(dict(zip(names, v)))
            else:
                conds.append(f"{k} = :w{i}")
                params[f"w{i}"] = v
        if order_by and order_by not in TABLES[table][1]:
            raise ContractError(f"Tri inconnu : {order_by}")
        q = (f"SELECT {self._sel(table)} FROM {self.t(table)}" + (f" WHERE {' AND '.join(conds)}" if conds else "")
             + (f" ORDER BY {order_by} {'DESC' if desc else 'ASC'}" if order_by else "") + f" LIMIT {int(limit)}")
        return [self._out(table, r) for r in self.sql.query(q, params or None).get("rows") or []]


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _load(v: Any, default: Any = None) -> Any:
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


class EiaRepository:
    """Règles communes de persistance : statuts, décisions humaines, dédoublonnage des alertes, journal."""

    def __init__(self, store: Any, clock: Callable[[], str] = now):
        self.s, self.clock = store, clock

    # ---- journal ----
    def log(self, object_type: str, object_id: str, event_type: str, actor: str, payload: Any = None) -> None:
        self.s.insert("eia_events", {"event_id": new_id("ev"), "object_type": object_type, "object_id": object_id,
                                     "event_type": event_type, "actor": actor, "payload": _j(payload or {}),
                                     "created_at": self.clock()})

    def events(self, object_id: str) -> list[dict]:
        return self.s.find("eia_events", {"object_id": object_id}, "created_at", desc=False)

    # ---- exécutions ----
    def start_run(self, team_id: str, trigger: str, request: str, user: str, plan: Any) -> str:
        rid = new_id("run")
        self.s.insert("eia_runs", {"run_id": rid, "team_id": team_id, "trigger": trigger, "request": request[:4000],
                                   "requested_by": user, "status": "en_cours", "plan": _j(plan), "started_at": self.clock()})
        self.log("run", rid, "cree", user, {"trigger": trigger})
        return rid

    def end_run(self, run_id: str, status: str, summary: str = "", error: str = "") -> None:
        cur = self.s.get("eia_runs", {"run_id": run_id})
        if not cur:
            raise ContractError(f"Exécution inconnue : {run_id}")
        check_transition("run", cur["status"], status)
        self.s.update("eia_runs", {"run_id": run_id}, {"status": status, "summary": summary[:4000], "error": error[:2000] or None,
                                                       "ended_at": self.clock()})
        self.log("run", run_id, status, "hakim")

    def save_step(self, run_id: str, step_id: str, agent: str, status: str, **fields: Any) -> None:
        row = {k: (_j(v) if TABLES["eia_run_steps"][2].get(k) == "j" else v) for k, v in fields.items()}
        if self.s.get("eia_run_steps", {"run_id": run_id, "step_id": step_id}):
            self.s.update("eia_run_steps", {"run_id": run_id, "step_id": step_id}, {"status": status, **row})
        else:
            self.s.insert("eia_run_steps", {"run_id": run_id, "step_id": step_id, "agent": agent, "status": status, **row})

    def steps(self, run_id: str) -> list[dict]:
        return self.s.find("eia_run_steps", {"run_id": run_id}, "started_at", desc=False)

    # ---- alertes ----
    def record_alert(self, team_id: str, run_id: str | None, a: dict, fp: str) -> tuple[str, bool]:
        """Enregistre une alerte ; si une alerte non résolue a la même empreinte, incrémente au lieu de dupliquer."""
        t = self.clock()
        open_ = self.s.find("eia_alerts", {"fingerprint": fp, "status": ["nouvelle", "vue", "acquittee"]}, limit=1)
        if open_:
            cur = open_[0]
            self.s.update("eia_alerts", {"alert_id": cur["alert_id"]},
                          {"occurrences": int(cur.get("occurrences") or 1) + 1, "last_seen_at": t,
                           "observed": a.get("observed"), "run_id": run_id})
            return cur["alert_id"], False
        aid = a.get("id") or new_id("al")
        self.s.insert("eia_alerts", {"alert_id": aid, "team_id": team_id, "run_id": run_id, "rule_id": a["rule_id"],
                                     "rule_status": a.get("rule_status", "a_valider"), "kind": a.get("kind", "metier"),
                                     "severity": a["severity"], "title": a["title"], "message": a.get("message", ""),
                                     "metric": a.get("metric", ""), "scope": a.get("scope", ""), "period": a.get("period", ""),
                                     "observed": a.get("observed"), "threshold": a.get("threshold"),
                                     "evidence": _j(a.get("evidence")), "fingerprint": fp, "status": "nouvelle",
                                     "occurrences": 1, "first_seen_at": t, "last_seen_at": t})
        self.log("alert", aid, "creee", "alerting", {"severity": a["severity"], "rule_id": a["rule_id"]})
        return aid, True

    def alerts(self, team_id: str, statuses: list[str] | None = None, limit: int = 200) -> list[dict]:
        where: dict[str, Any] = {"team_id": team_id}
        if statuses:
            where["status"] = statuses
        rows = self.s.find("eia_alerts", where, "last_seen_at", limit=limit)
        for r in rows:
            r["evidence"] = _load(r.get("evidence"), {})
        return rows

    def set_alert_status(self, alert_id: str, status: str, user: str) -> None:
        cur = self.s.get("eia_alerts", {"alert_id": alert_id})
        if not cur:
            raise ContractError(f"Alerte inconnue : {alert_id}")
        check_transition("alert", cur["status"], status, user)
        self.s.update("eia_alerts", {"alert_id": alert_id}, {"status": status, "decided_by": user, "decided_at": self.clock()})
        self.log("alert", alert_id, status, user)

    # ---- recommandations ----
    def save_recommendations(self, team_id: str, run_id: str, recos: list[dict]) -> list[str]:
        ids = []
        for r in recos:
            rid = r.get("id") or new_id("rc")
            self.s.insert("eia_recommendations", {
                "reco_id": rid, "team_id": team_id, "run_id": run_id, "title": r["title"], "rationale": r["rationale"],
                "priority": int(r["priority"]), "based_on": _j(r.get("based_on") or []),
                "expected_impact": r.get("expected_impact", ""), "assumptions": _j(r.get("assumptions") or []),
                "risks": _j(r.get("risks") or []), "status": "proposee", "created_at": self.clock()})
            self.log("recommendation", rid, "proposee", "advisor")
            ids.append(rid)
        return ids

    def recommendations(self, team_id: str, run_id: str | None = None, limit: int = 100) -> list[dict]:
        where = {"team_id": team_id, **({"run_id": run_id} if run_id else {})}
        rows = self.s.find("eia_recommendations", where, "created_at", limit=limit)
        for r in rows:
            for k in ("based_on", "assumptions", "risks"):
                r[k] = _load(r.get(k), [])
        return sorted(rows, key=lambda x: (x.get("run_id") or "", x.get("priority") or 99))

    def set_recommendation_status(self, reco_id: str, status: str, user: str, note: str = "") -> None:
        cur = self.s.get("eia_recommendations", {"reco_id": reco_id})
        if not cur:
            raise ContractError(f"Recommandation inconnue : {reco_id}")
        check_transition("recommendation", cur["status"], status, user)
        self.s.update("eia_recommendations", {"reco_id": reco_id},
                      {"status": status, "decided_by": user, "decided_at": self.clock(), "decision_note": note[:2000]})
        self.log("recommendation", reco_id, status, user, {"note": note})

    # ---- missions ----
    def create_mission_draft(self, team_id: str, m: dict, tasks: list[dict], user: str) -> str:
        """Crée une mission TOUJOURS en brouillon ; la validation est une décision humaine distincte."""
        if m.get("status") not in (None, "brouillon"):
            raise ContractError("Une mission est créée en brouillon ; la validation se fait ensuite par l'utilisateur")
        reco = self.s.get("eia_recommendations", {"reco_id": m["recommendation_id"]})
        if not reco or reco["status"] not in ("selectionnee", "validee"):
            raise ContractError("La recommandation d'origine doit avoir été sélectionnée par l'utilisateur")
        if not tasks or not m.get("success_kpis"):
            raise ContractError("Une mission exige des tâches et des KPI de réussite")
        mid = m.get("id") or new_id("ms")
        t = self.clock()
        self.s.insert("eia_missions", {
            "mission_id": mid, "team_id": team_id, "reco_id": m["recommendation_id"], "title": m["title"],
            "objective": m["objective"], "owner": m.get("owner", ""), "due_date": m.get("due_date"),
            "deliverables": _j(m.get("deliverables") or []), "success_kpis": _j(m["success_kpis"]), "status": "brouillon",
            "created_by": user, "created_at": t, "updated_at": t})
        for x in tasks:
            self.s.insert("eia_mission_tasks", {
                "mission_id": mid, "task_id": x.get("id") or new_id("mt"), "title": x["title"], "owner": x.get("owner", ""),
                "due_date": x.get("due_date"), "deliverable": x.get("deliverable", ""),
                "depends_on": _j(x.get("depends_on") or []), "status": "a_faire", "updated_by": user, "updated_at": t,
                "required_skills": _j(x.get("required_skills") or []), "estimated_hours": x.get("estimated_hours")})
        self.log("mission", mid, "brouillon", user, {"reco_id": m["recommendation_id"], "tasks": len(tasks)})
        return mid

    def set_mission_status(self, mission_id: str, status: str, user: str) -> None:
        cur = self.s.get("eia_missions", {"mission_id": mission_id})
        if not cur:
            raise ContractError(f"Mission inconnue : {mission_id}")
        check_transition("mission", cur["status"], status, user)
        fields: dict[str, Any] = {"status": status, "updated_at": self.clock()}
        if status == "validee":
            fields.update(validated_by=user, validated_at=self.clock())
        self.s.update("eia_missions", {"mission_id": mission_id}, fields)
        self.log("mission", mission_id, status, user)

    def missions(self, team_id: str, statuses: list[str] | None = None, limit: int = 100) -> list[dict]:
        where: dict[str, Any] = {"team_id": team_id, **({"status": statuses} if statuses else {})}
        rows = self.s.find("eia_missions", where, "created_at", limit=limit)
        for r in rows:
            r["deliverables"], r["success_kpis"] = _load(r.get("deliverables"), []), _load(r.get("success_kpis"), [])
        return rows

    def tasks(self, mission_id: str) -> list[dict]:
        rows = self.s.find("eia_mission_tasks", {"mission_id": mission_id}, "task_id", desc=False, limit=500)
        for r in rows:
            r["depends_on"] = _load(r.get("depends_on"), [])
            r["required_skills"] = _load(r.get("required_skills"), [])
        return rows

    def set_task_status(self, mission_id: str, task_id: str, status: str, user: str) -> None:
        m = self.s.get("eia_missions", {"mission_id": mission_id})
        if not m or m["status"] not in ("validee", "en_cours"):
            raise ContractError("Les tâches ne peuvent avancer que sur une mission validée")
        cur = self.s.get("eia_mission_tasks", {"mission_id": mission_id, "task_id": task_id})
        if not cur:
            raise ContractError(f"Tâche inconnue : {task_id}")
        check_transition("task", cur["status"], status, user)
        self.s.update("eia_mission_tasks", {"mission_id": mission_id, "task_id": task_id},
                      {"status": status, "updated_by": user, "updated_at": self.clock()})
        self.log("task", task_id, status, user, {"mission_id": mission_id})

    # ---- personnel et affectations ----
    def upsert_person(self, p: dict, skills: dict[str, int], actor: str) -> None:
        """Crée ou met à jour une personne et ses compétences (niveau 1 à 5)."""
        bad = {s: lv for s, lv in skills.items() if not isinstance(lv, int) or not 1 <= lv <= 5}
        if bad:
            raise ContractError(f"Niveaux de compétence invalides (1 à 5) : {bad}")
        t = self.clock()
        row = {k: p.get(k) for k in TABLES["eia_people"][1] if k in p}
        row["updated_at"] = t
        if self.s.get("eia_people", {"person_id": p["person_id"]}):
            self.s.update("eia_people", {"person_id": p["person_id"]}, {k: v for k, v in row.items() if k != "person_id"})
        else:
            self.s.insert("eia_people", row)
        for skill, level in skills.items():
            key = {"person_id": p["person_id"], "skill": skill}
            if self.s.get("eia_person_skills", key):
                self.s.update("eia_person_skills", key, {"level": level, "assessed_by": actor, "updated_at": t})
            else:
                self.s.insert("eia_person_skills", {**key, "level": level, "assessed_by": actor, "updated_at": t})

    def people(self, team_id: str, active_only: bool = True) -> list[dict]:
        where: dict[str, Any] = {"team_id": team_id, **({"status": "actif"} if active_only else {})}
        rows = self.s.find("eia_people", where, "person_id", desc=False, limit=2000)
        ids = [r["person_id"] for r in rows]
        skills: dict[str, dict[str, int]] = {}
        for i in range(0, len(ids), 200):
            for s in self.s.find("eia_person_skills", {"person_id": ids[i:i + 200]}, limit=20000):
                skills.setdefault(s["person_id"], {})[s["skill"]] = int(s["level"])
        for r in rows:
            r["skills"] = skills.get(r["person_id"], {})
        return rows

    def workload_hours(self, person_ids: list[str]) -> dict[str, int]:
        """Heures des tâches ouvertes déjà confirmées pour chaque personne."""
        load = {p: 0 for p in person_ids}
        if not person_ids:
            return load
        conf = self.s.find("eia_assignments", {"person_id": person_ids, "status": "confirmee"}, limit=20000)
        for a in conf:
            t = self.s.get("eia_mission_tasks", {"mission_id": a["mission_id"], "task_id": a["task_id"]})
            if t and t["status"] in ("a_faire", "en_cours", "bloque"):
                load[a["person_id"]] += int(t.get("estimated_hours") or 0)
        return load

    def propose_assignments(self, mission_id: str, task_id: str, candidates: list[dict], proposer: str) -> list[str]:
        """Enregistre les candidats classés (statut proposée) ; les propositions précédentes non décidées sont annulées."""
        if not self.s.get("eia_mission_tasks", {"mission_id": mission_id, "task_id": task_id}):
            raise ContractError(f"Tâche inconnue : {task_id}")
        if self.s.find("eia_assignments", {"task_id": task_id, "status": "confirmee"}, limit=1):
            raise ContractError("Une affectation est déjà confirmée pour cette tâche")
        for old in self.s.find("eia_assignments", {"task_id": task_id, "status": "proposee"}, limit=100):
            self.s.update("eia_assignments", {"assignment_id": old["assignment_id"]}, {"status": "annulee"})
        t, ids = self.clock(), []
        for rank, cnd in enumerate(candidates, 1):
            aid = new_id("as")
            self.s.insert("eia_assignments", {
                "assignment_id": aid, "mission_id": mission_id, "task_id": task_id, "person_id": cnd["person_id"],
                "rank": rank, "score": cnd["score"], "skill_score": cnd["skill_score"],
                "availability_score": cnd["availability_score"], "rationale": cnd["rationale"][:2000],
                "gaps": _j(cnd.get("gaps") or []), "status": "proposee", "proposed_by": proposer, "proposed_at": t})
            ids.append(aid)
        self.log("task", task_id, "affectation_proposee", proposer, {"mission_id": mission_id, "candidats": len(ids)})
        return ids

    def assignments(self, task_id: str) -> list[dict]:
        rows = self.s.find("eia_assignments", {"task_id": task_id}, "rank", desc=False, limit=100)
        for r in rows:
            r["gaps"] = _load(r.get("gaps"), [])
        return rows

    def decide_assignment(self, assignment_id: str, status: str, user: str) -> None:
        """Confirmation ou refus par un responsable identifié ; la confirmation nécessite une mission validée."""
        cur = self.s.get("eia_assignments", {"assignment_id": assignment_id})
        if not cur:
            raise ContractError(f"Affectation inconnue : {assignment_id}")
        check_transition("assignment", cur["status"], status, user)
        if status == "confirmee":
            m = self.s.get("eia_missions", {"mission_id": cur["mission_id"]})
            if not m or m["status"] not in ("validee", "en_cours"):
                raise ContractError("Une affectation ne peut être confirmée que sur une mission validée")
        t = self.clock()
        self.s.update("eia_assignments", {"assignment_id": assignment_id},
                      {"status": status, "decided_by": user, "decided_at": t})
        if status == "confirmee":
            for other in self.s.find("eia_assignments", {"task_id": cur["task_id"], "status": "proposee"}, limit=100):
                self.s.update("eia_assignments", {"assignment_id": other["assignment_id"]}, {"status": "annulee"})
            p = self.s.get("eia_people", {"person_id": cur["person_id"]}) or {}
            self.s.update("eia_mission_tasks", {"mission_id": cur["mission_id"], "task_id": cur["task_id"]},
                          {"owner": p.get("full_name") or cur["person_id"], "updated_by": user, "updated_at": t})
        self.log("assignment", assignment_id, status, user, {"task_id": cur["task_id"], "person_id": cur["person_id"]})

    # ---- équipes conçues par le Team Builder (EIA Factory) ----
    TEAM_CONFIG_TRANSITIONS = {"brouillon": ("en_service", "retiree"), "en_service": ("retiree",), "retiree": ()}

    def save_team_config(self, row: dict) -> str:
        """Brouillon versionné (AG09). Toujours en brouillon : la mise en service est une décision distincte."""
        user = row.get("created_by") or ""
        if not user or user.startswith("agent:"):
            raise ContractError("Enregistrement réservé à un utilisateur identifié")
        cid = row.get("config_id") or new_id("tc")
        self.s.insert("eia_team_configs", {
            "config_id": cid, "team_id": row["team_id"], "version": row.get("version") or "0.1", "status": "brouillon",
            "name": row.get("name") or row["team_id"], "models": _j(row.get("models") or []),
            "config": _j(row["config"]), "controls": _j(row.get("controls") or {}), "recette": _j(row.get("recette") or {}),
            "created_by": user, "created_at": self.clock()})
        self.log("team_config", cid, "brouillon", user, {"team_id": row["team_id"]})
        return cid

    def _team_row(self, r: dict) -> dict:
        for k, default in (("models", []), ("config", {}), ("controls", {}), ("recette", {})):
            r[k] = _load(r.get(k), default)
        return r

    def team_configs(self, team_id: str | None = None, statuses: list[str] | None = None, limit: int = 100) -> list[dict]:
        where = {**({"team_id": team_id} if team_id else {}), **({"status": statuses} if statuses else {})}
        return [self._team_row(r) for r in self.s.find("eia_team_configs", where, "created_at", limit=limit)]

    def team_config(self, config_id: str) -> dict | None:
        r = self.s.get("eia_team_configs", {"config_id": config_id})
        return self._team_row(r) if r else None

    def team_config_in_service(self, team_id: str) -> dict | None:
        rows = self.team_configs(team_id, ["en_service"], limit=1)
        return rows[0] if rows else None

    def set_team_config_status(self, config_id: str, status: str, user: str, blockers: list[str] | None = None) -> None:
        """Mise en service ou retrait par un humain identifié ; une seule version en service par équipe."""
        if not user or user.startswith("agent:"):
            raise ContractError("Décision réservée à un utilisateur identifié")
        cur = self.team_config(config_id)
        if not cur:
            raise ContractError(f"Configuration d'équipe inconnue : {config_id}")
        if status not in self.TEAM_CONFIG_TRANSITIONS.get(cur["status"], ()):
            raise ContractError(f"Transition interdite : {cur['status']} -> {status}")
        if status == "en_service" and blockers:
            raise ContractError("Mise en service impossible : " + " ; ".join(blockers))
        t = self.clock()
        if status == "en_service":
            for other in self.team_configs(cur["team_id"], ["en_service"]):
                self.s.update("eia_team_configs", {"config_id": other["config_id"]},
                              {"status": "retiree", "decided_by": user, "decided_at": t})
                self.log("team_config", other["config_id"], "retiree", user, {"remplacee_par": config_id})
        self.s.update("eia_team_configs", {"config_id": config_id}, {"status": status, "decided_by": user, "decided_at": t})
        self.log("team_config", config_id, status, user, {"team_id": cur["team_id"]})

    # ---- architectures d'entreprise (AG10 : Data Mesh + EIA ; AG09 : déploiement) ----
    ARCH_TRANSITIONS = {"brouillon": ("mesh_valide", "retiree"), "mesh_valide": ("brouillon", "eia_valide", "retiree"),
                        "eia_valide": ("mesh_valide", "deployee", "retiree"), "deployee": ("retiree",), "retiree": ()}
    ARCH_EDITABLE = {"mesh": ("brouillon",), "eia": ("mesh_valide",), "deployment": ("eia_valide", "deployee")}

    @staticmethod
    def _human(user: str) -> None:
        if not user or user.startswith("agent:"):
            raise ContractError("Action réservée à un utilisateur identifié")

    def _arch_row(self, r: dict) -> dict:
        for k in ("mesh", "eia", "deployment"):
            r[k] = _load(r.get(k), {})
        return r

    def save_architecture(self, plan_id: str, name: str, mesh: dict, user: str) -> str:
        """Nouvelle architecture en brouillon (découpage Data Mesh proposé par AG10)."""
        self._human(user)
        aid, t = new_id("ar"), self.clock()
        self.s.insert("eia_architectures", {"arch_id": aid, "plan_id": plan_id, "name": (name or plan_id)[:120],
                                            "status": "brouillon", "mesh": _j(mesh), "eia": _j({}),
                                            "deployment": _j({}), "created_by": user, "created_at": t,
                                            "updated_by": user, "updated_at": t})
        self.log("architecture", aid, "brouillon", user, {"plan_id": plan_id})
        return aid

    def architecture(self, arch_id: str) -> dict | None:
        r = self.s.get("eia_architectures", {"arch_id": arch_id})
        return self._arch_row(r) if r else None

    def architectures(self, plan_id: str, limit: int = 20) -> list[dict]:
        return [self._arch_row(r) for r in self.s.find("eia_architectures", {"plan_id": plan_id}, "created_at",
                                                       limit=limit)]

    def current_architecture(self, plan_id: str) -> dict | None:
        return next((a for a in self.architectures(plan_id) if a["status"] != "retiree"), None)

    def update_architecture(self, arch_id: str, part: str, value: dict, user: str) -> None:
        """Modification d'une partie, seulement au statut qui la permet (découpage avant sa validation, etc.)."""
        self._human(user)
        cur = self.architecture(arch_id)
        if not cur:
            raise ContractError(f"Architecture inconnue : {arch_id}")
        if part not in self.ARCH_EDITABLE:
            raise ContractError(f"Partie inconnue : {part}")
        if cur["status"] not in self.ARCH_EDITABLE[part]:
            raise ContractError(f"{part} non modifiable au statut {cur['status']}")
        self.s.update("eia_architectures", {"arch_id": arch_id},
                      {part: _j(value), "updated_by": user, "updated_at": self.clock()})
        self.log("architecture", arch_id, f"{part}_modifie", user, {})

    def set_architecture_status(self, arch_id: str, status: str, user: str) -> None:
        """Validation, réouverture, déploiement ou retrait : décision d'un humain identifié."""
        self._human(user)
        cur = self.architecture(arch_id)
        if not cur:
            raise ContractError(f"Architecture inconnue : {arch_id}")
        if status not in self.ARCH_TRANSITIONS.get(cur["status"], ()):
            raise ContractError(f"Transition interdite : {cur['status']} -> {status}")
        if status == "eia_valide" and not cur["eia"].get("agents"):
            raise ContractError("Aucune architecture EIA à valider")
        if status == "deployee" and cur["deployment"].get("statut") != "brouillon":
            raise ContractError("Déploiement non réussi : statut déployé impossible")
        t = self.clock()
        self.s.update("eia_architectures", {"arch_id": arch_id},
                      {"status": status, "decided_by": user, "decided_at": t, "updated_by": user, "updated_at": t})
        self.log("architecture", arch_id, status, user, {"plan_id": cur["plan_id"]})
