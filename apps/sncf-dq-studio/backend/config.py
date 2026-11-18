"""Configuration de l'App (variables d'environnement injectees par Databricks Apps, voir app.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from backend.naming import check_code_source, check_identifier

DEFAULT_JOB_ID = 1083902303793833
DEFAULT_MODEL = "databricks-claude-sonnet-4-6"


def running_in_databricks_app() -> bool:
    return bool(os.getenv("DATABRICKS_APP_NAME") or os.getenv("DATABRICKS_APP_PORT"))


@dataclass(frozen=True)
class Settings:
    warehouse_id: str
    model_endpoint: str
    job_id: int
    catalog: str
    app_schema: str
    default_source: str
    admins: tuple[str, ...]
    max_rows: int = 200
    sql_timeout_s: int = 120

    @property
    def app_fqn(self) -> str:
        return f"{self.catalog}.{self.app_schema}"


def _int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env
    admins = tuple(a.strip().lower() for a in (e.get("DQ_ADMINS") or "").split(",") if a.strip())
    return Settings(
        warehouse_id=(e.get("DATABRICKS_WAREHOUSE_ID") or "").strip(),
        model_endpoint=(e.get("DQ_MODEL_ENDPOINT") or DEFAULT_MODEL).strip(),
        job_id=_int(e.get("DQ_JOB_ID"), DEFAULT_JOB_ID),
        catalog=check_identifier((e.get("DQ_CATALOG") or "dataops_dev").strip(), "catalogue"),
        app_schema=check_identifier((e.get("DQ_APP_SCHEMA") or "sncf_dqv3_app").strip(), "schema de l'App"),
        default_source=check_code_source((e.get("DQ_DEFAULT_SOURCE") or "ddr").strip()),
        admins=admins,
        max_rows=max(10, min(_int(e.get("DQ_MAX_ROWS"), 200), 1000)),
    )
