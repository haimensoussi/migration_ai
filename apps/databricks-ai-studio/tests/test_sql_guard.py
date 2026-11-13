import pytest

from backend.sql_guard import SqlGuardError, check_read_only, extract_table_refs


@pytest.mark.parametrize("sql", [
    "SELECT * FROM a.b.c",
    "  with x as (select 1 as v) select * from x;",
    "SHOW TABLES IN dataops_dev.ai_studio",
    "DESCRIBE TABLE a.b.c",
    "SELECT 'delete from t' AS txt, `update` FROM a.b.c -- drop table",
    "(SELECT 1)",
])
def test_allowed(sql):
    assert check_read_only(sql)


@pytest.mark.parametrize("sql", [
    "DELETE FROM a.b.c",
    "SELECT 1; DROP TABLE a.b.c",
    "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x",
    "MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN DELETE",
    "SELECT * FROM read_files('/Volumes/x')",
    "SELECT secret('scope','key')",
    "CREATE TABLE t AS SELECT 1",
    "",
    "SELECT 'unterminated",
    "/* commentaire */ GRANT SELECT ON TABLE t TO `x`",
])
def test_refused(sql):
    with pytest.raises(SqlGuardError):
        check_read_only(sql)


def test_trailing_semicolon_removed():
    assert check_read_only("SELECT 1 ;") == "SELECT 1"


def test_extract_refs():
    sql = "WITH x AS (SELECT * FROM `a`.`b`.`c`) SELECT * FROM x JOIN d.e.f ON 1=1 -- FROM g.h.i"
    assert extract_table_refs(sql) == {"a.b.c", "d.e.f"}
