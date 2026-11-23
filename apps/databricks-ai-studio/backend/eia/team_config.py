"""EIA Core - configuration des équipes métier (config/teams/<team_id>.json).

Toute la logique métier (sources, KPI, règles, seuils, instructions) vit dans ces fichiers ; les agents
transverses restent génériques. Les requêtes KPI référencent les sources par alias : {orders}, {targets}...
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from backend import sql_guard
from backend.eia.contracts import AGENT_ROLES, SEVERITIES

BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "teams")
TEAM_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
ALIAS = re.compile(r"\{([a-z][a-z0-9_]*)\}")
FQN = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$")
GRAINS = ("mois", "instantane", "dimension")
DIRECTIONS = ("hausse_favorable", "baisse_favorable")
RULE_TYPES = ("seuil_bas", "seuil_haut", "variation_annuelle", "variation_prevision")
RULE_STATUSES = ("a_valider", "valide", "desactive")
REQUIRED = ("team_id", "name", "description", "objectives", "sources", "kpis", "rules", "agents", "tools",
            "instructions", "validation_policy")


class TeamConfigError(ValueError):
    pass


@dataclass(frozen=True)
class TeamConfig:
    team_id: str
    name: str
    description: str
    objectives: list
    sources: dict            # alias -> catalog.schema.table
    kpis: list               # définitions KPI (id, label, unit, grain, direction, sql, formula, exclusions, limits)
    rules: list              # règles d'alerte (id, kpi, type, thresholds, status...)
    agents: list             # rôles EIA disponibles pour l'équipe
    tools: list              # outils autorisés
    instructions: dict       # rôle -> consignes métier
    validation_policy: dict
    forecast: dict = field(default_factory=dict)
    version: str = ""

    def kpi(self, kpi_id: str) -> dict:
        for k in self.kpis:
            if k["id"] == kpi_id:
                return k
        raise TeamConfigError(f"KPI inconnu pour l'équipe {self.team_id} : {kpi_id}")

    def rule(self, rule_id: str) -> dict:
        for r in self.rules:
            if r["id"] == rule_id:
                return r
        raise TeamConfigError(f"Règle inconnue pour l'équipe {self.team_id} : {rule_id}")

    def render_sql(self, sql: str) -> str:
        """Remplace les alias {source} par les noms complets ; refuse tout alias non déclaré."""
        def sub(m: re.Match) -> str:
            a = m.group(1)
            if a not in self.sources:
                raise TeamConfigError(f"Source non autorisée pour l'équipe {self.team_id} : {a}")
            return ".".join(f"`{p}`" for p in self.sources[a].split("."))
        return ALIAS.sub(sub, sql)

    def kpi_sql(self, kpi_id: str) -> str:
        return self.render_sql(self.kpi(kpi_id)["sql"])

    def instructions_for(self, role: str) -> str:
        return str(self.instructions.get("commun", "")) + ("\n" + str(self.instructions[role]) if role in self.instructions else "")


def _norm_ref(name: str) -> str:
    return name.replace("`", "").strip().lower()


def validate(d: dict, data_scope: tuple[str, str, str] | None = None, known_tools: set[str] | None = None) -> list[str]:
    """Contrôle d'une configuration d'équipe. Liste vide = conforme."""
    issues = [f"champ obligatoire manquant : {k}" for k in REQUIRED if k not in d]
    if issues:
        return issues
    if not TEAM_ID.match(str(d["team_id"])):
        issues.append("team_id invalide (minuscules, chiffres, _)")
    sources = d["sources"]
    if not isinstance(sources, dict) or not sources:
        issues.append("sources : dictionnaire alias -> table attendu")
        sources = {}
    for alias, fqn in sources.items():
        if not re.match(r"^[a-z][a-z0-9_]*$", alias) or not FQN.match(str(fqn)):
            issues.append(f"source invalide : {alias} -> {fqn}")
        elif data_scope:
            cat, sch, pre = data_scope
            c, s, t = str(fqn).split(".")
            if (c.lower(), s.lower()) != (cat.lower(), sch.lower()) or not t.lower().startswith(pre.lower()):
                issues.append(f"source hors zone de données {cat}.{sch}.{pre}* : {fqn}")
    allowed = {_norm_ref(v) for v in sources.values()}
    kpi_ids = set()
    for k in d["kpis"]:
        kid = k.get("id", "?")
        for f in ("id", "label", "unit", "grain", "direction", "sql", "formula"):
            if not k.get(f):
                issues.append(f"KPI {kid} : champ {f} manquant")
        if kid in kpi_ids:
            issues.append(f"KPI en double : {kid}")
        kpi_ids.add(kid)
        if k.get("grain") and k["grain"] not in GRAINS:
            issues.append(f"KPI {kid} : grain inconnu {k['grain']}")
        if k.get("direction") and k["direction"] not in DIRECTIONS:
            issues.append(f"KPI {kid} : sens inconnu {k['direction']}")
        sql = k.get("sql") or ""
        unknown = [a for a in ALIAS.findall(sql) if a not in sources]
        if unknown:
            issues.append(f"KPI {kid} : sources non déclarées {unknown}")
            continue
        rendered = ALIAS.sub(lambda m: sources[m.group(1)], sql)
        try:
            sql_guard.check_read_only(rendered)
        except sql_guard.SqlGuardError as e:
            issues.append(f"KPI {kid} : requête refusée ({e})")
            continue
        outside = {_norm_ref(t) for t in sql_guard.extract_table_refs(rendered)} - allowed
        if outside:
            issues.append(f"KPI {kid} : tables hors sources {sorted(outside)}")
        if " AS period" not in rendered or " AS value" not in rendered:
            issues.append(f"KPI {kid} : la requête doit renvoyer les colonnes period et value")
    for r in d["rules"]:
        rid = r.get("id", "?")
        if r.get("kpi") not in kpi_ids:
            issues.append(f"règle {rid} : KPI inconnu {r.get('kpi')}")
        if r.get("type") not in RULE_TYPES:
            issues.append(f"règle {rid} : type inconnu {r.get('type')}")
        if r.get("status") not in RULE_STATUSES:
            issues.append(f"règle {rid} : statut de validation inconnu {r.get('status')}")
        th = r.get("thresholds") or {}
        if not th or any(s not in SEVERITIES or not isinstance(v, (int, float)) for s, v in th.items()):
            issues.append(f"règle {rid} : seuils invalides (gravité -> nombre)")
        elif "attention" in th and "critique" in th:
            low = r.get("type") in ("seuil_bas", "variation_annuelle", "variation_prevision")
            if (low and th["critique"] > th["attention"]) or (not low and th["critique"] < th["attention"]):
                issues.append(f"règle {rid} : seuil critique moins sévère que le seuil d'attention")
    bad_roles = [a for a in d["agents"] if a not in AGENT_ROLES]
    if bad_roles:
        issues.append(f"agents inconnus : {bad_roles}")
    if known_tools is not None:
        miss = [t for t in d["tools"] if t not in known_tools]
        if miss:
            issues.append(f"outils inconnus : {miss}")
    vp = d["validation_policy"]
    if vp.get("mission_requires_validation") is not True:
        issues.append("validation_policy.mission_requires_validation doit être true")
    if vp.get("external_actions") not in ("interdit", "sur_validation"):
        issues.append("validation_policy.external_actions : interdit | sur_validation")
    return issues


def from_dict(d: dict, data_scope: tuple[str, str, str] | None = None, known_tools: set[str] | None = None) -> TeamConfig:
    issues = validate(d, data_scope, known_tools)
    if issues:
        raise TeamConfigError("Configuration d'équipe invalide : " + " ; ".join(issues))
    return TeamConfig(**{k: d[k] for k in REQUIRED}, forecast=d.get("forecast") or {}, version=str(d.get("version", "")))


def load(team_id: str, base_dir: str | None = None, data_scope: tuple[str, str, str] | None = None,
         known_tools: set[str] | None = None) -> TeamConfig:
    if not TEAM_ID.match(team_id or ""):
        raise TeamConfigError(f"Identifiant d'équipe invalide : {team_id!r}")
    path = os.path.join(base_dir or BASE_DIR, f"{team_id}.json")
    if not os.path.isfile(path):
        raise TeamConfigError(f"Configuration d'équipe introuvable : {team_id}")
    with open(path, encoding="utf-8") as f:
        d: dict[str, Any] = json.load(f)
    if d.get("team_id") != team_id:
        raise TeamConfigError(f"team_id du fichier ({d.get('team_id')}) différent du nom de fichier ({team_id})")
    return from_dict(d, data_scope, known_tools)


def available(base_dir: str | None = None) -> list[str]:
    d = base_dir or BASE_DIR
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and TEAM_ID.match(f[:-5])) if os.path.isdir(d) else []
