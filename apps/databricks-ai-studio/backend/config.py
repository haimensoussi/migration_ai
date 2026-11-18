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
    tool_admins: tuple = ()
    platform_admins: tuple = ()   # SaaS : administrateurs de la plateforme (créent les organisations) - AI_STUDIO_PLATFORM_ADMINS
    tenant_catalog: str = "dataops_dev"   # SaaS : catalogue des schémas dédiés aux organisations - AI_STUDIO_TENANT_CATALOG
    team_admins: tuple = ()   # e-mails autorisés à publier les équipes (AI_STUDIO_TEAM_ADMINS ; défaut : tool_admins)   # e-mails autorisés à publier les outils qui écrivent ou envoient (AI_STUDIO_TOOL_ADMINS)

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
        team_admins=tuple(e.strip().lower() for e in os.environ.get("AI_STUDIO_TEAM_ADMINS", "").split(",") if e.strip()),
        tool_admins=tuple(e.strip().lower() for e in os.environ.get("AI_STUDIO_TOOL_ADMINS", "").split(",") if e.strip()),
        platform_admins=tuple(e.strip().lower() for e in os.environ.get("AI_STUDIO_PLATFORM_ADMINS", "").split(",")
                              if e.strip()),
        tenant_catalog=os.environ.get("AI_STUDIO_TENANT_CATALOG", "dataops_dev"),
    )
    for v in (s.catalog, s.schema, s.tenant_catalog):
        if not _IDENT.match(v):
            raise ValueError(f"Identifiant invalide dans la configuration : {v!r}")
    return s


def data_scope() -> tuple[str, str, str]:
    """Zone de données des agents : (catalogue, schéma, préfixe des tables de données).

    Défaut : dataops_dev.ai_studio, tables préfixées data_ (les autres tables du schéma sont la configuration
    de la plateforme : agents, conversations, journaux).
    """
    cat = os.environ.get("AI_STUDIO_DATA_CATALOG") or os.environ.get("AI_STUDIO_CATALOG", "dataops_dev")
    sch = os.environ.get("AI_STUDIO_DATA_SCHEMA") or os.environ.get("AI_STUDIO_SCHEMA", "ai_studio")
    pre = os.environ.get("AI_STUDIO_DATA_PREFIX", "data_")
    for v in (cat, sch):
        if not _IDENT.match(v):
            raise ValueError(f"Identifiant invalide dans la configuration : {v!r}")
    if pre and not re.match(r"^[A-Za-z0-9_]+$", pre):
        raise ValueError(f"Préfixe invalide dans la configuration : {pre!r}")
    return cat, sch, pre


def running_in_databricks_app() -> bool:
    return bool(os.environ.get("DATABRICKS_APP_NAME"))
