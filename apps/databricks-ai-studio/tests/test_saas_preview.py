"""Mode « Aperçu en tant que » : réduit les droits, ne les augmente jamais, survit à la relecture, est audité."""
import itertools

import pytest

from backend.saas.agent_studio import AgentStudio
from backend.saas.models import DEFAULT_ROLES, AccessDenied, Identity, Membership, Role, ValidationError
from backend.saas.setup_wizard import DATA_STEPS, SetupWizard
from backend.saas.store import MemoryStore
from backend.saas.tenant_service import TenantService

PLATFORM = Identity("plateforme@discovery.io", "test")
OWNER = Identity("owner@alpha.com", "test")
USER = Identity("user@alpha.com", "test")
SETUP = {
    "organisation": {"display_name": "Alpha", "contact_email": "dpo@alpha.com", "language": "fr", "timezone": "UTC"},
    "infrastructure": {"warehouse_id": "d0642494ed2912f0", "max_rows": 200, "sql_timeout_s": 120},
    "ia": {"default_endpoint": "databricks-claude-sonnet-4-6", "allowed_endpoints": [], "temperature": 0.2,
           "max_tokens": 4096},
    "securite": {"default_member_role": "user", "allowed_domains": "alpha.com", "write_approval": True},
    "modules": {"agent_studio": True},
}


class Checker:
    def warehouse(self, _):
        return True, "ok"

    endpoint = schema = warehouse


@pytest.fixture
def env():
    store = MemoryStore({k: Role(k, k, r, frozenset(p)) for k, (r, p) in DEFAULT_ROLES.items()})
    svc = TenantService(store, [PLATFORM.email])
    t = svc.create_tenant(PLATFORM, "Alpha SA", "alpha", OWNER.email)
    ctx = svc.resolve(OWNER, t.tenant_id)
    clock = (f"2026-11-18T10:00:{i:02d}+00:00" for i in itertools.count())
    wiz = SetupWizard(svc, now=lambda: next(clock))
    for step in DATA_STEPS:
        wiz.save_step(ctx, step, SETUP[step])
    wiz.activate(ctx, Checker())
    svc.add_member(ctx, USER.email, "user")
    return svc, store, ctx


def test_preview_reduces_rights_on_every_check(env):
    svc, store, ctx = env
    p = svc.start_preview(ctx, "user")
    assert p.preview and p.role.role_id == "user" and p.actual_role.role_id == "owner"
    for call in (lambda: svc.get_settings(p), lambda: svc.add_member(p, "x@alpha.com", "viewer"),
                 lambda: AgentStudio(svc, lambda: []).save_draft(p, None, {})):
        with pytest.raises(AccessDenied):
            call()
    fresh = svc.authorize(p, "agents.read", "test")          # le contexte frais garde l'aperçu
    assert fresh.preview and fresh.role.role_id == "user"
    assert svc.stop_preview(p).role.role_id == "owner"
    assert svc.get_settings(svc.stop_preview(p))            # droits réels retrouvés


def test_preview_never_elevates(env):
    svc, store, ctx = env
    u = svc.resolve(USER, ctx.tenant_id)
    for role in ("owner", "admin", "builder", "user", "inconnu"):
        with pytest.raises(ValidationError):
            svc.start_preview(u, role)
    forged = svc.resolve(USER, ctx.tenant_id, preview_role="owner")   # appel direct : plafonné au rôle réel
    assert forged.role.role_id == "user"
    with pytest.raises(AccessDenied):
        svc.get_settings(forged)


def test_real_role_downgrade_wins_during_preview(env):
    svc, store, ctx = env
    p = svc.start_preview(ctx, "builder")
    store.upsert_membership(Membership(ctx.tenant_id, OWNER.email, "viewer", "actif", PLATFORM.email))
    assert svc.authorize(p, "tenant.read", "test").role.role_id == "viewer"
    store.upsert_membership(Membership(ctx.tenant_id, OWNER.email, "owner", "suspendu", PLATFORM.email))
    with pytest.raises(AccessDenied):
        svc.authorize(p, "tenant.read", "test")


def test_preview_is_audited(env):
    svc, store, ctx = env
    p = svc.start_preview(ctx, "viewer")
    svc.stop_preview(p)
    actions = [(a["action"], a["target_id"]) for a in svc.audit_log(ctx)]
    assert ("tenant.preview", "viewer") in actions and ("tenant.preview_end", "viewer") in actions


def test_preview_does_not_change_platform_identity(env):
    """Le service plateforme reste lié à l'identité ; l'interface masque ces fonctions en aperçu (platform_admin)."""
    svc, store, ctx = env
    me = svc.resolve(PLATFORM, ctx.tenant_id) if store.get_membership(ctx.tenant_id, PLATFORM.email) else None
    assert me is None
    p = svc.start_preview(ctx, "user")
    svc2 = TenantService(store, [OWNER.email])
    assert svc2.acts_as_platform_admin(OWNER, ctx) is True and svc2.acts_as_platform_admin(OWNER, p) is False
    assert svc2.acts_as_platform_admin(OWNER, None) is True
