import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeSql:
    """SqlClient factice : enregistre les requetes et renvoie des reponses programmees."""

    def __init__(self, responses=None, fail_on=None):
        self.calls = []
        self.responses = list(responses or [])
        self.fail_on = fail_on

    def query(self, statement, params=None, row_limit=None):
        self.calls.append((statement, params or {}, row_limit))
        if self.fail_on and self.fail_on in statement:
            raise RuntimeError("PERMISSION_DENIED")
        rows = self.responses.pop(0) if self.responses else []
        cols = list(rows[0].keys()) if rows else []
        return {"columns": cols, "rows": rows, "truncated": False, "types": {}}

    def execute(self, statement, params=None):
        self.query(statement, params)


class FakeApi:
    def __init__(self, responses=None, fail=False):
        self.calls = []
        self.responses = responses or {}
        self.fail = fail

    def do(self, method, path, query=None, body=None):
        self.calls.append((method, path, query, body))
        if self.fail:
            raise RuntimeError("PERMISSION_DENIED: job")
        return self.responses.get(path, {})


class FakeW:
    def __init__(self, responses=None, fail=False):
        self.api_client = FakeApi(responses, fail)
