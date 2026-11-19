import itertools
from types import SimpleNamespace

import pytest

from backend import publication as pub
from backend.agent_repository import AgentRepository

OWNER, ADMIN, RESP, OTHER = "owner@sncf.fr", "admin@sncf.fr", "resp.sc@sncf.fr", "autre@sncf.fr"
CONTRACT = {"version": 1, "domaine": "Supply Chain", "perimetre": "Analyse des stocks magasins Supply Chain",
            "donnees": "a.b.c", "limites": "Lecture seule", "responsable_metier": RESP, "date_revue": "2027-01-01"}


class FakeSql:
    """Base en mémoire reconnaissant les instructions du service de publication."""

    def __init__(self):
        self.agents = {"a1": {"agent_id": "a1", "name": "Agent 1", "owner": OWNER, "status": "brouillon",
                              "current_version": 3}}
        self.reqs, self.owners, self.clock = [], [], itertools.count()

    def query(self, q, p=None, row_limit=None):
        p = p or {}
        if "FROM t.domain_owners" in q:
            return {"rows": [dict(domaine=d, email=e) for d, e in self.owners]}
        if "FROM t.agents WHERE agent_id" in q:
            a = self.agents.get(p["a"])
            return {"rows": [dict(a)] if a else []}
        if "WHERE request_id = :r" in q:
            return {"rows": [dict(r) for r in self.reqs if r["request_id"] == p["r"]]}
        if "FROM t.publication_requests r" in q:
            rows = [r for r in self.reqs if ("s" not in p or r["status"] == p["s"])
                    and ("a" not in p or r["agent_id"] == p["a"])]
            return {"rows": [dict(r) for r in sorted(rows, key=lambda r: -r["requested_at"])]}
        raise AssertionError(q)

    def execute(self, q, p=None):
        p = p or {}
        if q.startswith("UPDATE t.agents"):
            self.agents[p["a"]]["status"] = p["s"]
        elif "INSERT INTO t.publication_requests" in q:
            self.reqs.append({"request_id": p["id"], "agent_id": p["a"], "agent_version": p["v"], "domaine": p["d"],
                              "contract_version": p["cv"], "contract_completeness": p["cc"], "status": p["s"],
                              "origin": p["o"], "requested_by": p["u"], "requested_at": next(self.clock),
                              "decided_by": p["db"], "decision_note": p["n"], "self_validation": p["sv"]})
        elif "UPDATE t.publication_requests" in q and "WHERE request_id" in q:
            for r in self.reqs:
                if r["request_id"] == p["r"] and r["status"] == pub.PENDING:
                    r.update(status=p["s"], decided_by=p["u"], decision_note=p["n"], self_validation=p["sv"])
        elif "UPDATE t.publication_requests" in q:
            for r in self.reqs:
                if r["agent_id"] == p["a"] and r["status"] == pub.PENDING:
                    r.update(status=p["s"], decided_by=p["u"], decision_note=p["n"])
        elif "INSERT INTO t.domain_owners REPLACE WHERE" in q:
            self.owners = [o for o in self.owners if o[0] != p["d"]] + \
                [(p["d"], v) for k, v in p.items() if k.startswith("e")]
        elif q.startswith("DELETE FROM t.domain_owners"):
            self.owners = [o for o in self.owners if o[0] != p["d"]]
        else:
            raise AssertionError(q)


def service(contract=CONTRACT, admins=(ADMIN,)):
    s = SimpleNamespace(table=lambda n: f"t.{n}", team_admins=admins, tool_admins=())
    svc = pub.PublicationService(FakeSql(), s)
    svc.contracts = SimpleNamespace(latest=lambda aid: dict(contract) if contract else None)
    return svc


def test_validators_fallback_to_admins_until_designated():
    assert pub.validators_for("PTE", {}, {ADMIN}) == ({ADMIN}, "repli")
    assert pub.validators_for("PTE", {"PTE": ["R@X.FR"]}, {ADMIN}) == ({"r@x.fr"}, "domaine")
    assert pub.admins_of(SimpleNamespace(team_admins=(), tool_admins=("T@X.FR",))) == {"t@x.fr"}


def test_submission_requires_owner_and_domain_only():
    agent = {"owner": OWNER, "status": "brouillon"}
    errs, warns = pub.submission_issues(agent, {"domaine": "PTE"}, OWNER)
    assert errs == [] and warns and "incomplète" in warns[0]           # fiche incomplète : avertissement seul
    assert pub.submission_issues(agent, CONTRACT, OWNER) == ([], [])
    assert len(pub.submission_issues(agent, None, OWNER)[0]) == 1      # pas de domaine : bloquant
    assert len(pub.submission_issues(agent, CONTRACT, OTHER)[0]) == 1  # pas propriétaire : bloquant


def test_submit_then_validate_by_fallback_admin():
    svc = service()
    rid, _ = svc.submit("a1", OWNER)
    assert svc.sql.agents["a1"]["status"] == "en_validation"
    assert [r["request_id"] for r in svc.pending_for(ADMIN)] == [rid] and svc.pending_for(OTHER) == []
    with pytest.raises(pub.PublicationError):
        svc.decide(rid, OTHER, True)                                     # non valideur
    assert svc.decide(rid, ADMIN, True, "OK") == pub.VALIDATED
    assert svc.sql.agents["a1"]["status"] == "publie"
    r = svc.sql.reqs[0]
    assert r["agent_version"] == 3 and r["domaine"] == "Supply Chain" and r["self_validation"] is False
    with pytest.raises(pub.PublicationError):
        svc.decide(rid, ADMIN, True)                                     # déjà traitée


def test_designated_owner_replaces_fallback():
    svc = service()
    svc.set_domain_owners("Supply Chain", [RESP], ADMIN)
    rid, _ = svc.submit("a1", OWNER)
    assert svc.pending_for(ADMIN) == [] and len(svc.pending_for(RESP)) == 1
    with pytest.raises(pub.PublicationError):
        svc.decide(rid, ADMIN, True)
    with pytest.raises(pub.PublicationError):
        svc.set_domain_owners("Supply Chain", ["x@y.fr"], RESP)           # seul un admin désigne
    with pytest.raises(pub.PublicationError):
        svc.set_domain_owners("Supply Chain", ["pas-un-mail"], ADMIN)


def test_refusal_needs_reason_and_returns_to_draft():
    svc = service()
    rid, _ = svc.submit("a1", OWNER)
    with pytest.raises(pub.PublicationError):
        svc.decide(rid, ADMIN, False, "  ")
    assert svc.decide(rid, ADMIN, False, "Périmètre trop large") == pub.REFUSED
    assert svc.sql.agents["a1"]["status"] == "brouillon"


def test_changed_version_makes_request_obsolete():
    svc = service()
    rid, _ = svc.submit("a1", OWNER)
    svc.sql.agents["a1"]["current_version"] = 4
    with pytest.raises(pub.PublicationError):
        svc.decide(rid, ADMIN, True)
    assert svc.sql.reqs[0]["status"] == pub.OBSOLETE and svc.sql.agents["a1"]["status"] == "brouillon"


def test_resubmit_replaces_and_cancel_returns_to_draft():
    svc = service()
    svc.submit("a1", OWNER)
    svc.submit("a1", OWNER)
    assert [r["status"] for r in svc.sql.reqs] == [pub.CANCELLED, pub.PENDING]
    with pytest.raises(pub.PublicationError):
        svc.cancel("a1", OTHER)
    svc.cancel("a1", OWNER)
    assert svc.sql.reqs[1]["status"] == pub.CANCELLED and svc.sql.agents["a1"]["status"] == "brouillon"


def test_self_validation_is_traced():
    svc = service(admins=(OWNER,))
    rid, _ = svc.submit("a1", OWNER)
    svc.decide(rid, OWNER, True)
    assert svc.sql.reqs[0]["self_validation"] is True


def test_record_traces_direct_publications():
    svc = service()
    svc.record("a1", ADMIN, "reprise", "Validation réputée acquise")
    r = svc.sql.reqs[0]
    assert r["status"] == pub.VALIDATED and r["origin"] == "reprise" and r["decided_by"] == ADMIN
    assert svc.sql.agents["a1"]["status"] == "publie"
    with pytest.raises(pub.PublicationError):
        svc.record("a1", OTHER, "equipe", "x")                           # chef d'équipe : admin seulement
    with pytest.raises(pub.PublicationError):
        svc.record("a1", ADMIN, "soumission", "x")


def test_repository_refuses_direct_publication():
    repo = AgentRepository(None, SimpleNamespace(table=lambda n: n))
    for call in (lambda: repo.set_status("a1", "publie"), lambda: repo.set_status("a1", "en_validation"),
                 lambda: repo.create_agent({"name": "x"}, {}, OWNER, "publie"),
                 lambda: repo.save_version("a1", {"name": "x"}, {}, OWNER, "publie")):
        with pytest.raises(ValueError, match="demande de validation"):
            call()
