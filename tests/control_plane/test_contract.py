"""Control Plane contract — behavior of CREATE/SUSPEND/RESUME/DELETE plus injected failures.

No live AWS/cluster. Actuators are fakes so we assert the state machine, not object names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from errors import AWSRetryableError, PermanentProvisioningError
from observe import Observed
from reconcile import reconcile_one
from store import TenantStore

pytestmark = [pytest.mark.unit]


@dataclass
class FakeWorld:
    namespaces: set[str] = field(default_factory=set)
    secrets: set[str] = field(default_factory=set)
    irsa: set[str] = field(default_factory=set)
    db_roles: set[str] = field(default_factory=set)
    rls: set[str] = field(default_factory=set)
    ingress: set[str] = field(default_factory=set)
    replicas: dict[str, int] = field(default_factory=dict)
    fail_on: str | None = None

    def _boom(self, step: str) -> None:
        if self.fail_on == step:
            if step in {"secret", "irsa"}:
                raise AWSRetryableError(f"injected {step}")
            raise PermanentProvisioningError(f"injected {step}")

    def observe(self, tenant_id: str, item: dict) -> Observed:
        ns = tenant_id in self.namespaces
        replicas = self.replicas.get(tenant_id, 0)
        return Observed(
            namespace=ns,
            deploy_ready=replicas >= 1,
            replicas=replicas,
            ingress=tenant_id in self.ingress,
            # Helm onboard installs these with the namespace in the real cluster.
            service=ns,
            network_policy=ns,
            resource_quota=ns,
            irsa_sa=tenant_id in self.irsa,
            secret=tenant_id in self.secrets,
            irsa=tenant_id in self.irsa,
        )

    def provision(self, store: TenantStore, tofu_dir: Path, tenant_id: str, **kwargs) -> None:
        self._boom("secret")
        self.secrets.add(tenant_id)
        self._boom("irsa")
        self.irsa.add(tenant_id)
        self._boom("db_role")
        self.db_roles.add(tenant_id)
        self._boom("rls")
        self.rls.add(tenant_id)
        self._boom("namespace")
        self.namespaces.add(tenant_id)
        self._boom("helm")
        self._boom("ingress")
        self.ingress.add(tenant_id)
        self.replicas[tenant_id] = 1
        store.upsert(
            tenant_id,
            desired_status="ACTIVE",
            status="ACTIVE",
            owned_by="control_plane",
            secret_name=f"secret/{tenant_id}",
            irsa_role_arn=f"arn:role/{tenant_id}",
            error=None,
        )

    def suspend(self, store: TenantStore, tenant_id: str) -> dict:
        self.replicas[tenant_id] = 0
        self.ingress.discard(tenant_id)
        return store.upsert(tenant_id, desired_status="SUSPENDED", status="SUSPENDED", error=None)

    def resume(self, store: TenantStore, tofu_dir: Path, tenant_id: str) -> dict:
        self.namespaces.add(tenant_id)
        self.ingress.add(tenant_id)
        self.replicas[tenant_id] = 1
        return store.upsert(tenant_id, desired_status="ACTIVE", status="ACTIVE", error=None)

    def delete(self, store: TenantStore, tofu_dir: Path, tenant_id: str) -> None:
        self._boom("db_role")
        self.db_roles.discard(tenant_id)
        self.rls.discard(tenant_id)
        self.namespaces.discard(tenant_id)
        self.ingress.discard(tenant_id)
        self.replicas.pop(tenant_id, None)
        self.irsa.discard(tenant_id)
        self.secrets.discard(tenant_id)
        store.delete(tenant_id)


def _run(store: TenantStore, world: FakeWorld, tid: str):
    return reconcile_one(
        store,
        Path("/tmp"),
        tid,
        observer=world,
        provision_fn=world.provision,
        suspend_fn=world.suspend,
        resume_fn=world.resume,
        delete_fn=world.delete,
    )


def test_create_contract(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "t.db")
    world = FakeWorld()
    store.upsert("z", desired_status="ACTIVE", status="PROVISIONING")
    result = _run(store, world, "z")
    assert result["status"] == "ACTIVE"
    assert "z" in world.namespaces
    assert "z" in world.secrets
    assert "z" in world.irsa
    assert "z" in world.db_roles
    assert "z" in world.rls
    assert "z" in world.ingress
    assert world.replicas["z"] == 1


def test_suspend_preserves_data(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "t.db")
    world = FakeWorld()
    store.upsert("z", desired_status="ACTIVE", status="PROVISIONING")
    _run(store, world, "z")
    store.upsert("z", desired_status="SUSPENDED")
    result = _run(store, world, "z")
    assert result["status"] == "SUSPENDED"
    assert world.replicas["z"] == 0
    assert "z" not in world.ingress
    assert "z" in world.namespaces
    assert "z" in world.db_roles


def test_resume_restores_workload(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "t.db")
    world = FakeWorld()
    store.upsert("z", desired_status="ACTIVE", status="PROVISIONING")
    _run(store, world, "z")
    store.upsert("z", desired_status="SUSPENDED")
    _run(store, world, "z")
    store.upsert("z", desired_status="ACTIVE")
    result = _run(store, world, "z")
    assert result["status"] == "ACTIVE"
    assert world.replicas["z"] == 1
    assert "z" in world.ingress


def test_delete_contract(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "t.db")
    world = FakeWorld()
    store.upsert("z", desired_status="ACTIVE", status="PROVISIONING")
    _run(store, world, "z")
    store.upsert("z", desired_status="GONE", status="DELETING")
    result = _run(store, world, "z")
    assert result["status"] == "GONE"
    assert store.get("z") is None
    assert "z" not in world.namespaces
    assert "z" not in world.secrets
    assert "z" not in world.irsa
    assert "z" not in world.db_roles


@pytest.mark.parametrize("step", ["secret", "irsa", "helm", "db_role", "ingress"])
def test_failure_injection_leaves_desired_active(tmp_path: Path, step: str) -> None:
    store = TenantStore(tmp_path / "t.db")
    world = FakeWorld(fail_on=step)
    store.upsert("z", desired_status="ACTIVE", status="PROVISIONING")
    with pytest.raises((AWSRetryableError, PermanentProvisioningError)):
        _run(store, world, "z")
    item = store.get("z")
    assert item is not None
    assert item["desired_status"] == "ACTIVE"
    # Namespace-only must not be treated as success.
    if "z" in world.namespaces and world.replicas.get("z", 0) < 1:
        obs = world.observe("z", item)
        assert not obs.matches_active()
