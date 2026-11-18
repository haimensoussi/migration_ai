import pytest

from backend import jobs_service as J
from backend.app_repository import AppRepository
from backend.config import load_settings
from backend.dq_repository import DqRepository
from backend.naming import NamingError, check_prefix, parse_patterns, prefix_for, schema_fqn
from backend.roles import resolve_roles
from backend.sql_guard import SqlGuardError, check_read_only, check_scope
from tests.conftest import FakeSql, FakeW

SRC = {"code_source": "ddr", "bronze_catalog": "dataops_dev", "bronze_schema": "description_du_reseau_bronze",
       "dq_prefix": "sncf_dqv3_ddr", "filiere": "a_qualifier", "tables_incluses": "%",
       "tables_exclues": "dq_%,rapport_%,slv_%,qrt_%", "ref_catalog": "dataops_dev", "ref_schema": "sncf_dqv3_ref"}


# ---------- nommage ----------
def test_prefix_et_schemas():
    assert prefix_for("ddr") == "sncf_dqv3_ddr"
    assert schema_fqn("dataops_dev", "sncf_dqv3_ddr", "gold") == "dataops_dev.sncf_dqv3_ddr_gold"
    assert check_prefix("sncf_dqv3") == "sncf_dqv3"
    for bad in ("sncf_dqv3_ddr; DROP", "autre_prefix", "sncf_dqv3_DDR", ""):
        with pytest.raises(NamingError):
            check_prefix(bad)
    with pytest.raises(NamingError):
        prefix_for("d")


def test_motifs():
    assert parse_patterns(" a%, b_% ,") == ["a%", "b_%"]
    with pytest.raises(NamingError):
        parse_patterns("a'; DROP TABLE x")


def test_settings_par_defaut():
    s = load_settings({"DATABRICKS_WAREHOUSE_ID": "w1", "DQ_ADMINS": "A@x.fr, b@x.fr"})
    assert s.job_id == 1083902303793833 and s.default_source == "ddr" and s.app_fqn == "dataops_dev.sncf_dqv3_app"
    assert s.admins == ("a@x.fr", "b@x.fr")
    with pytest.raises(NamingError):
        load_settings({"DQ_CATALOG": "x;y"})


# ---------- roles ----------
def test_roles():
    rows = [{"principal": "U@sncf.fr", "role": "lanceur", "actif": "true"},
            {"principal": "u@sncf.fr", "role": "resp_metier", "actif": "false"},
            {"principal": "u@sncf.fr", "role": "inconnu", "actif": "true"}]
    r = resolve_roles("u@sncf.fr", rows)
    assert r.roles == frozenset({"lanceur"}) and r.can("lancer") and not r.can("valider_regle")
    lecteur = resolve_roles("x@sncf.fr", rows)
    assert not lecteur.can("lancer") and lecteur.labels() == ["Lecteur"]
    admin = resolve_roles("Admin@sncf.fr", [], admins=["admin@sncf.fr"])
    assert admin.can("lancer") and admin.can("valider_regle") and admin.can("gerer_sources")


# ---------- parametres du job ----------
def test_parametres_job():
    p = J.build_job_parameters(SRC, "dataops_dev", "declivite%", "", "Supply Chain")
    assert set(p) == set(J.JOB_PARAM_KEYS)
    assert p["dq_prefix"] == "sncf_dqv3_ddr" and p["bronze_schema"] == "description_du_reseau_bronze"
    assert p["tables_incluses"] == "declivite%"
    assert p["tables_exclues"] == "dq_%,rapport_%,slv_%,qrt_%"  # exclusions techniques toujours presentes
    assert p["filiere_defaut"] == "Supply Chain"


def test_parametres_job_refus():
    with pytest.raises(NamingError):
        J.build_job_parameters({**SRC, "dq_prefix": "sncf_dqv3"}, "dataops_dev")  # prefixe non conforme
    with pytest.raises(NamingError):
        J.build_job_parameters(SRC, "dataops_dev", filiere="Inconnue")
    with pytest.raises(NamingError):
        J.build_job_parameters({**SRC, "bronze_schema": "x; DROP"}, "dataops_dev")


def _repo(fail_on=None):
    return AppRepository(FakeSql(), FakeSql(fail_on=fail_on), "dataops_dev", "sncf_dqv3_app")


def test_lancement_trace():
    repo = _repo()
    w = FakeW({"/api/2.2/jobs/run-now": {"run_id": 42}})
    roles = resolve_roles("u@sncf.fr", [{"principal": "u@sncf.fr", "role": "lanceur", "actif": True}])
    params = J.build_job_parameters(SRC, "dataops_dev")
    out = J.launch(repo, w, 1083902303793833, "u@sncf.fr", roles, SRC, params)
    assert out["run_id"] == 42 and out["warning"] is None
    method, path, _, body = w.api_client.calls[0]
    assert (method, path) == ("POST", "/api/2.2/jobs/run-now")
    assert body == {"job_id": 1083902303793833, "job_parameters": params}
    insert, upd = repo.write_sql.calls
    assert "INSERT INTO dataops_dev.sncf_dqv3_app.app_lancements" in insert[0] and insert[1]["u"] == "u@sncf.fr"
    assert "UPDATE" in upd[0] and upd[1]["s"] == "lance" and upd[1]["r"] == "42"


def test_lancement_refuse_sans_role():
    repo = _repo()
    w = FakeW({"/api/2.2/jobs/run-now": {"run_id": 42}})
    with pytest.raises(J.LaunchRefused):
        J.launch(repo, w, 1, "x@sncf.fr", resolve_roles("x@sncf.fr", []), SRC, J.build_job_parameters(SRC, "dataops_dev"))
    assert not w.api_client.calls and not repo.write_sql.calls


def test_lancement_refuse_sans_trace():
    repo = _repo(fail_on="INSERT")
    w = FakeW({"/api/2.2/jobs/run-now": {"run_id": 42}})
    admin = resolve_roles("a@sncf.fr", [], admins=["a@sncf.fr"])
    with pytest.raises(J.AuditUnavailable):
        J.launch(repo, w, 1, "a@sncf.fr", admin, SRC, J.build_job_parameters(SRC, "dataops_dev"))
    assert not w.api_client.calls  # aucun job lance sans trace


def test_lancement_echec_api_trace():
    repo = _repo()
    w = FakeW(fail=True)
    admin = resolve_roles("a@sncf.fr", [], admins=["a@sncf.fr"])
    with pytest.raises(J.LaunchError):
        J.launch(repo, w, 1, "a@sncf.fr", admin, SRC, J.build_job_parameters(SRC, "dataops_dev"))
    assert repo.write_sql.calls[-1][1]["s"] == "echec_lancement"


# ---------- suivi ----------
RUN = {
    "run_id": 7, "start_time": 1000, "end_time": 61000, "trigger": "ONE_TIME",
    "state": {"life_cycle_state": "INTERNAL_ERROR", "result_state": "FAILED", "state_message": "Task decouverte failed"},
    "status": {"state": "TERMINATED", "termination_details": {"code": "RUN_EXECUTION_ERROR"}},
    "job_parameters": [{"name": "dq_prefix", "default": "sncf_dqv3", "value": "sncf_dqv3_coplann"},
                       {"name": "bronze_schema", "default": "sncf_dqv3_bronze"}],
    "tasks": [
        {"task_key": "decouverte", "run_id": 1, "attempt_number": 0, "start_time": 2000, "end_time": 3000,
         "state": {"result_state": "FAILED"}},
        {"task_key": "decouverte", "run_id": 2, "attempt_number": 1, "start_time": 5000, "end_time": 9000,
         "state": {"result_state": "SUCCESS"}},
        {"task_key": "gold", "run_id": 3, "start_time": 10000, "state": {"result_state": "UPSTREAM_FAILED"}},
    ],
}


def test_resume_run():
    s = J.summarize_run(RUN)
    assert s["etat"] == "Termine" and s["resultat"] == "Echec" and s["duree_s"] == 60.0
    assert s["dq_prefix"] == "sncf_dqv3_coplann" and s["bronze_schema"] == "sncf_dqv3_bronze"
    tasks = J.task_summary(RUN)
    assert [t["tache"] for t in tasks] == ["decouverte", "gold"]
    assert tasks[0]["etat"] == "Reussi" and tasks[0]["task_run_id"] == 2  # derniere tentative retenue
    assert tasks[1]["etat"] == "Non execute (echec amont)"


def test_dq_repository_requetes():
    sql = FakeSql([[{"databaseName": "sncf_dqv3_ddr_gold"}], [{"nb_objets": "3"}]])
    repo = DqRepository(sql, "dataops_dev", "sncf_dqv3_ddr")
    assert repo.exists()
    assert repo.indicateurs() == {"nb_objets": "3"}
    assert "dataops_dev.sncf_dqv3_ddr_gold.v_dq_kpi_courant" in sql.calls[1][0]
    repo.erreurs_techniques(235975222816147)
    assert sql.calls[-1][1] == {"j": "235975222816147"}
    with pytest.raises(NamingError):
        DqRepository(sql, "dataops_dev", "x")


# ---------- garde-fous SQL ----------
ALLOWED = {"dataops_dev.sncf_dqv3_ddr_gold", "dataops_dev.sncf_dqv3_ddr_results"}


def test_sql_guard_lecture_seule():
    assert check_read_only("SELECT 1;") == "SELECT 1"
    for bad in ("DELETE FROM t", "SELECT 1; DROP TABLE t", "SHOW TABLES", "WITH a AS (SELECT 1) INSERT INTO t SELECT * FROM a",
                "SELECT * FROM read_files('/x')"):
        with pytest.raises(SqlGuardError):
            check_read_only(bad)
    assert check_read_only("SELECT 'DELETE' AS mot")  # mot-cle dans un litteral : autorise


def test_sql_guard_perimetre():
    ok = "WITH x AS (SELECT * FROM dataops_dev.sncf_dqv3_ddr_gold.v_dq_kpi_courant) SELECT * FROM x " \
         "JOIN dataops_dev.sncf_dqv3_ddr_results.dq_run r ON 1 = 1"
    assert len(check_scope(ok, ALLOWED)) == 2
    for bad in ("SELECT * FROM dataops_dev.ai_studio.agents", "SELECT * FROM v_dq_kpi_courant",
                "SELECT * FROM dataops_dev.sncf_dqv3_gold.dq_kpi_daily", "SELECT 1"):
        with pytest.raises(SqlGuardError):
            check_scope(bad, ALLOWED)
