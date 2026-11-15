import json

from backend import tool_builder as tb
from backend.tool_registry import ToolContext, ToolSpec
from tools.catalog import BUILTIN_TOOLS

T = "dataops_dev.description_du_reseau_bronze.gares_de_voyageurs"
EXISTING = {t.tool_id: t for t in BUILTIN_TOOLS}


def draft(**kw):
    base = {"name": "Gares par département",
            "description": "Liste les gares voyageurs d'un département avec leurs coordonnées.",
            "category": "Données",
            "sql": f"SELECT Nom_Gare FROM {T} WHERE left(`Code commune`, 2) = :departement ORDER BY Nom_Gare;",
            "parameters": [{"name": "departement", "type": "string", "description": "Code", "required": True,
                            "example": "35"}]}
    return tb.normalize({**base, **kw})


class Sql:
    def __init__(self, fail_on=None, plan="== Physical Plan =="):
        self.fail_on, self.plan, self.calls = fail_on, plan, []

    def query(self, statement, params=None, row_limit=None):
        self.calls.append(statement)
        if self.fail_on and self.fail_on in statement:
            raise RuntimeError("TABLE_OR_VIEW_NOT_FOUND")
        if statement.startswith("EXPLAIN"):
            return {"columns": ["plan"], "rows": [{"plan": self.plan}], "truncated": False}
        return {"columns": ["Nom_Gare"], "rows": [{"Nom_Gare": "Rennes"}], "truncated": False}


def test_normalize_and_build_roundtrip():
    d = draft()
    assert d["tool_id"] == "gares_par_departement" and not d["sql"].endswith(";")
    c = tb.check(d, EXISTING, "u@sncf.fr")
    assert c.ok, c.errors
    s = tb.build_spec(d, "u@sncf.fr")
    assert s.executor == "tools.custom_tools:sql_template" and s.read_only and s.status == "brouillon"
    assert s.config["tables"] == [T] and s.config["examples"] == {"departement": "35"}
    assert s.input_schema["required"] == ["departement"]
    back = ToolSpec.from_row({**s.to_row(), "requires_confirmation": "false", "read_only": "true"})
    assert back == s and tb.draft_from_spec(back)["sql"] == d["sql"]
    assert tb.fingerprint(d) == tb.fingerprint(tb.draft_from_spec(back))


def test_check_errors():
    def errs(**kw):
        return " | ".join(tb.check(draft(**kw), EXISTING, "u@sncf.fr").errors)
    assert "déjà utilisé" in errs(tool_id="execute_sql")
    assert "Identifiant invalide" in errs(tool_id="X")
    assert "Description trop courte" in errs(description="court")
    assert "refusée" in errs(sql=f"DELETE FROM {T} WHERE a = :departement")
    assert "noms complets" in errs(sql="SELECT * FROM gares WHERE a = :departement")
    assert "non déclarés : autre" in errs(sql=f"SELECT * FROM {T} WHERE a = :departement AND b = :autre")
    assert "absents de la requête : departement" in errs(sql=f"SELECT * FROM {T}")
    assert "invalide" in errs(parameters=[{"name": "Dép", "type": "string", "description": "d"}],
                              sql=f"SELECT * FROM {T} WHERE a = :Dép")
    assert "Type invalide" in errs(parameters=[{"name": "departement", "type": "date", "description": "d"}])


def test_check_with_sql_access_and_compilation():
    assert tb.check(draft(), EXISTING, "u", Sql()).ok
    assert "inaccessible" in tb.check(draft(), EXISTING, "u", Sql(fail_on="DESCRIBE")).errors[0]
    bad = Sql(plan="Error occurred during query planning: [UNRESOLVED_COLUMN] ...")
    assert "ne compile pas" in tb.check(draft(), EXISTING, "u", bad).errors[0]


def test_owner_protection():
    other = tb.build_spec(draft(), "autre@sncf.fr")
    mine = tb.build_spec(draft(), "u@sncf.fr")
    assert "déjà utilisé" in tb.check(draft(), {other.tool_id: other}, "u@sncf.fr").errors[0]
    assert tb.check(draft(), {mine.tool_id: mine}, "u@sncf.fr").ok


def test_run_test_reports_success_and_failure():
    s = tb.build_spec(draft(), "u")
    ok = tb.run_test(s, {"departement": "35"}, ToolContext(sql=Sql(), workspace=None))
    assert ok["ok"] and ok["nombre_lignes"] == 1 and ok["apercu"] == [{"Nom_Gare": "Rennes"}]
    ko = tb.run_test(s, {}, ToolContext(sql=Sql(), workspace=None))
    assert not ko["ok"] and "departement" in ko["erreur"]
    json.dumps(ok)
