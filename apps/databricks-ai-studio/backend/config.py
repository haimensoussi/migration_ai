"""Paramètres de l'application, lus depuis l'environnement (app.yaml / ressources Databricks Apps)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

_IDENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")


@dataclass(frozen=True)
class Settings:
    warehouse_id: str
    catalog: str
    schema: str
    default_model: str
    max_rows: int = 200
    sql_timeout_s: int = 120
    max_iterations: int = 6

    @property
    def prefix(self) -> str:
        """Préfixe `catalog`.`schema` des tables de configuration."""
        return f"`{self.catalog}`.`{self.schema}`"

    def table(self, name: str) -> str:
        return f"{self.prefix}.`{name}`"


def load_settings() -> Settings:
    s = Settings(
        warehouse_id=os.environ.get("DATABRICKS_WAREHOUSE_ID", ""),
        catalog=os.environ.get("AI_STUDIO_CATALOG", "dataops_dev"),
        schema=os.environ.get("AI_STUDIO_SCHEMA", "ai_studio"),
        default_model=os.environ.get("AI_STUDIO_DEFAULT_MODEL", "databricks-claude-sonnet-4-6"),
        max_rows=int(os.environ.get("AI_STUDIO_MAX_ROWS", "200")),
        sql_timeout_s=int(os.environ.get("AI_STUDIO_SQL_TIMEOUT_S", "120")),
    )
    for v in (s.catalog, s.schema):
        if not _IDENT.match(v):
            raise ValueError(f"Identifiant invalide dans la configuration : {v!r}")
    return s


def running_in_databricks_app() -> bool:
    return bool(os.environ.get("DATABRICKS_APP_NAME"))
