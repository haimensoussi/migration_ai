"""Registre des outils : contrats (schémas JSON), résolution des exécuteurs, validation des arguments."""
from __future__ import annotations

import importlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


class ToolError(RuntimeError):
    """Erreur fonctionnelle d'un outil (message destiné à l'utilisateur et au modèle)."""


class ToolPermissionError(ToolError):
    pass


@dataclass
class ToolSpec:
    tool_id: str
    name: str
    category: str
    description: str
    input_schema: dict
    output_schema: dict
    executor: str  # "tools.module:fonction"
    identity: str = "utilisateur"
    requires_confirmation: bool = False
    read_only: bool = True
    status: str = "publie"
    version: str = "1.0.0"

    def to_openai(self) -> dict:
        return {"type": "function",
                "function": {"name": self.tool_id, "description": self.description,
                             "parameters": self.input_schema}}

    def to_row(self) -> dict:
        d = asdict(self)
        d["input_schema"] = json.dumps(self.input_schema, ensure_ascii=False)
        d["output_schema"] = json.dumps(self.output_schema, ensure_ascii=False)
        return d

    @classmethod
    def from_row(cls, r: dict) -> "ToolSpec":
        def b(v):
            return v if isinstance(v, bool) else str(v).lower() == "true"
        return cls(tool_id=r["tool_id"], name=r["name"], category=r["category"], description=r["description"],
                   input_schema=json.loads(r["input_schema"]), output_schema=json.loads(r["output_schema"]),
                   executor=r["executor"], identity=r["identity"],
                   requires_confirmation=b(r["requires_confirmation"]), read_only=b(r["read_only"]),
                   status=r["status"], version=r["version"])


@dataclass
class ToolContext:
    """Ressources mises à disposition des outils, toutes sous l'identité de l'utilisateur."""
    sql: Any                       # SqlClient utilisateur
    workspace: Any                 # WorkspaceClient utilisateur
    allowed_tables: list[str] = field(default_factory=list)
    max_rows: int = 200


ALLOWED_EXECUTOR_PREFIX = "tools."


def resolve_executor(path: str) -> Callable[..., Any]:
    """Seuls les modules du paquet `tools` sont exécutables (pas de chemin arbitraire)."""
    if ":" not in path or not path.startswith(ALLOWED_EXECUTOR_PREFIX):
        raise ToolError(f"Exécuteur non autorisé : {path}")
    mod, fn = path.split(":", 1)
    return getattr(importlib.import_module(mod), fn)


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def validate_args(schema: dict, args: dict) -> dict:
    """Validation minimale (champs requis, types, propriétés inconnues) sans dépendance externe."""
    if not isinstance(args, dict):
        raise ToolError("Les arguments doivent être un objet JSON.")
    props = schema.get("properties", {})
    missing = [k for k in schema.get("required", []) if k not in args or args[k] in (None, "")]
    if missing:
        raise ToolError(f"Arguments requis manquants : {', '.join(missing)}")
    unknown = [k for k in args if k not in props]
    if unknown:
        raise ToolError(f"Arguments inconnus : {', '.join(unknown)}")
    out = {}
    for k, v in args.items():
        t = props[k].get("type")
        if t == "integer" and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v)
        if t in _TYPES and (not isinstance(v, _TYPES[t]) or (t in ("integer", "number") and isinstance(v, bool))):
            raise ToolError(f"Type invalide pour {k} : {t} attendu")
        if "enum" in props[k] and v not in props[k]["enum"]:
            raise ToolError(f"Valeur non autorisée pour {k} : {v}")
        if t == "integer":
            if "minimum" in props[k] and v < props[k]["minimum"]:
                raise ToolError(f"{k} doit être >= {props[k]['minimum']}")
            if "maximum" in props[k] and v > props[k]["maximum"]:
                v = props[k]["maximum"]
        out[k] = v
    return out


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]):
        self.specs = {s.tool_id: s for s in specs}

    def published(self) -> list[ToolSpec]:
        return [s for s in self.specs.values() if s.status == "publie"]

    def for_agent(self, tool_ids: list[str]) -> dict[str, ToolSpec]:
        return {t: self.specs[t] for t in tool_ids if t in self.specs and self.specs[t].status == "publie"}

    def run(self, spec: ToolSpec, ctx: ToolContext, args: dict) -> Any:
        fn = resolve_executor(spec.executor)
        return fn(ctx, **validate_args(spec.input_schema, args))
