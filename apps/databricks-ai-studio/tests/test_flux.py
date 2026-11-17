import json

import pytest

from backend import flux
from backend.agent_repository import _is_created
from backend.tool_registry import ToolContext, ToolError, ToolRegistry
from tools.catalog import BUILTIN_TOOLS

DRAFT = {"name": "Envoyer un résumé Teams", "description": "Publie un résumé dans le canal Teams du Data Office.",
         "type": "action",
         "parametres": [{"nom": "titre", "type": "string", "obligatoire": True, "description": "Titre"},
                        {"nom": "jour", "type": "date", "obligatoire": False, "description": "Jour concerné"},
                        {"nom": "niveau", "type": "enum", "obligatoire": True, "description": "Criticité",
                         "valeurs": "haute, moyenne"},
                        {"nom": "", "type": "string"}],                       # ligne vide du tableur ignorée
         "valeurs_fixes": [{"nom": "canal", "valeur": "data-office"}, {"nom": "", "valeur": ""}],
         "reponse": "identifiant du message", "delai_minutes": 30}


class Sql:
    def __init__(self, rows=None):
        self.rows, self.calls = rows or [], []

    def execute(self, statement, params=None):
        self.calls.append((statement, params or {}))

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, params or {}))
        rows = [r for r in self.rows if r.get("_user") in (None, (params or {}).get("u"))]
        return {"rows": rows, "columns": [], "truncated": False}


def ctx(app_sql=None, user="a@sncf.fr"):
    return ToolContext(sql=None, workspace=None, user_email=user, conversation_id="c1", app_sql=app_sql,
                       agent_id="ag1")


def spec(**kw):
    return flux.build_spec({**DRAFT, **kw}, "a@sncf.fr", status="publie")


def test_schema_hides_fixed_values_and_maps_types():
    s = spec()
    assert s.tool_id == "flux_envoyer_un_resume_teams" and s.category == "Flux" and _is_created(s.executor)
    props = s.input_schema["properties"]
    assert list(props) == ["titre", "jour", "niveau"] and "canal" not in props
    assert props["jour"] == {"type": "string", "format": "date", "description": "Jour concerné (AAAA-MM-JJ)"}
    assert props["niveau"]["enum"] == ["haute", "moyenne"] and s.input_schema["required"] == ["titre", "niveau"]
    assert "data-office" not in s.description and "flux_suivi" in s.description
    assert s.config["valeurs_fixes"] == {"canal": "data-office"} and s.config["delai_minutes"] == 30
    assert flux.draft_from_spec(s)["description"] == DRAFT["description"]


def test_action_requires_confirmation_lecture_does_not():
    a, r = spec(), spec(type="lecture")
    assert a.requires_confirmation and not a.read_only
    assert not r.requires_confirmation and r.read_only


def test_check_errors():
    assert flux.check(DRAFT, {}, "a@sncf.fr") == []
    bad = {**DRAFT, "description": "court", "type": "autre",
           "parametres": [{"nom": "Mon Param", "type": "string", "description": "x"},
                          {"nom": "liste", "type": "enum", "description": "x", "valeurs": ""},
                          {"nom": "canal", "type": "string", "description": "x"},
                          {"nom": "sans_desc", "type": "string"}]}
    errs = " | ".join(flux.check(bad, {}, "a@sncf.fr"))
    for frag in ("trop courte", "Type inconnu", "invalide « mon param »", "Liste de valeurs vide",
                 "à la fois un paramètre et une valeur fixe", "Description manquante pour le paramètre sans_desc"):
        assert frag in errs, frag
    taken = flux.check(DRAFT, {"flux_envoyer_un_resume_teams": "b@sncf.fr"}, "a@sncf.fr")
    assert any("déjà pris" in e for e in taken)
    assert flux.check(DRAFT, {"flux_envoyer_un_resume_teams": "a@sncf.fr"}, "a@sncf.fr") == []  # nouvelle version
    assert any("déjà pris" in e for e in flux.check({**DRAFT, "tool_id": "flux_suivi"}, {"flux_suivi": "__integre__"}, "a"))


def test_call_flow_writes_row_and_merges_fixed_values():
    s, sql = spec(type="lecture"), Sql()
    out = ToolRegistry([s]).run(s, ctx(sql), {"titre": "Bilan", "niveau": "haute", "canal": "pirate"}
                                if False else {"titre": "Bilan", "niveau": "haute"})
    stmt, p = sql.calls[0]
    assert "INSERT INTO" in stmt and "flux_demandes" in stmt and "'en_attente'" in stmt
    assert p["flux"] == s.tool_id and p["user"] == "a@sncf.fr" and p["conv"] == "c1" and p["agent"] == "ag1"
    assert json.loads(p["params"]) == {"titre": "Bilan", "niveau": "haute", "canal": "data-office"}
    assert p["test"] is False and len(out["demande_id"]) == 32 and out["statut"] == "en_attente"
    assert "canal" not in json.dumps(out)   # valeur fixe jamais renvoyée au modèle


def test_agent_cannot_override_fixed_value_or_send_bad_date():
    s = spec(type="lecture")
    with pytest.raises(ToolError, match="inconnus"):     # canal absent du schéma : refusé par le registre
        ToolRegistry([s]).run(s, ctx(Sql()), {"titre": "T", "niveau": "haute", "canal": "autre"})
    with pytest.raises(ToolError, match="Date invalide"):
        ToolRegistry([s]).run(s, ctx(Sql()), {"titre": "T", "niveau": "haute", "jour": "17/11/2026"})
    with pytest.raises(ToolError, match="Valeur non autorisée"):
        ToolRegistry([s]).run(s, ctx(Sql()), {"titre": "T", "niveau": "basse"})


def test_missing_app_sql_raises():
    s = spec(type="lecture")
    with pytest.raises(ToolError, match="indisponible"):
        ToolRegistry([s]).run(s, ctx(None), {"titre": "T", "niveau": "haute"})
    reg = ToolRegistry(BUILTIN_TOOLS)
    with pytest.raises(ToolError, match="indisponible"):
        reg.run(reg.specs["flux_suivi"], ctx(None), {"demande_id": "a" * 32})


def _row(statut, age, user="a@sncf.fr", **kw):
    return {"_user": user, "demande_id": "a" * 32, "flux_id": "flux_x", "statut": statut, "age_minutes": str(age),
            "config": json.dumps({"delai_minutes": 30}), "created_at": "2026-11-17 10:00:00", "termine_at": None, **kw}


def test_flux_suivi_filters_user_and_computes_expiry():
    reg = ToolRegistry(BUILTIN_TOOLS)
    sp = reg.specs["flux_suivi"]
    assert sp.read_only and sp.status == "publie" and sp.category == "Flux"
    sql = Sql([_row("en_attente", 31)])
    r = reg.run(sp, ctx(sql), {"demande_id": "A" * 32})
    stmt, p = sql.calls[-1]
    assert "d.user_name = :u" in stmt and p == {"id": "a" * 32, "u": "a@sncf.fr"}
    assert r["statut"] == "expiree"
    assert reg.run(sp, ctx(Sql([_row("en_attente", 30)])), {"demande_id": "a" * 32})["statut"] == "en_attente"
    with pytest.raises(ToolError, match="introuvable"):     # demande d'un autre utilisateur
        reg.run(sp, ctx(Sql([_row("terminee", 1, user="b@sncf.fr")])), {"demande_id": "a" * 32})
    done = reg.run(sp, ctx(Sql([_row("terminee", 1, reponse='{"message_id": 42}')])), {"demande_id": "a" * 32})
    assert done["reponse"] == {"message_id": 42}
    err = reg.run(sp, ctx(Sql([_row("erreur", 1, erreur="Canal introuvable")])), {"demande_id": "a" * 32})
    assert err["erreur"] == "Canal introuvable"
    with pytest.raises(ToolError, match="invalide"):
        reg.run(sp, ctx(Sql()), {"demande_id": "x'; DROP TABLE t; --"})


def test_pa_queries_contain_flux_id_and_reject_bad_id():
    s = spec()
    q = flux.pa_queries(s, "dataops_dev.ai_studio.flux_demandes")
    assert len(q) == 4 and all(f"flux_id = '{s.tool_id}'" in v for v in q.values())
    assert all("dataops_dev.ai_studio.flux_demandes" in v for v in q.values())
    from dataclasses import replace
    with pytest.raises(ValueError):
        flux.pa_queries(replace(s, tool_id="flux_x'; DROP"), "t")
    js = flux.json_schema(s)
    assert set(js["properties"]) == {"titre", "jour", "niveau", "canal"} and "canal" in js["required"]
