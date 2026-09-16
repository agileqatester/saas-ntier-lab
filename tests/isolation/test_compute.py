"""Compute isolation — ResourceQuota effect + noisy-neighbor.

Contract: a tenant that hits its pod quota must not take down peer tenants.
Do not assert ResourceQuota object names — assert Pending/reject + peer health.
"""

from __future__ import annotations

import time
import uuid

import pytest

from lib import kubectl
from lib.tenant import Tenant

pytestmark = [pytest.mark.isolation, pytest.mark.requires_cluster]

OVERFLOW_NAME = "qa-quota-overflow"


def _overflow_manifest(name: str) -> str:
    # Tiny pause pod; LimitRange supplies default requests/limits.
    return f"""apiVersion: v1
kind: Pod
metadata:
  name: {name}
  labels:
    app: qa-quota-overflow
spec:
  restartPolicy: Never
  containers:
    - name: pause
      image: public.ecr.aws/eks-distro/kubernetes/pause:3.9
      command: ["sleep", "3600"]
"""


@pytest.fixture
def cleanup_overflow(tenant_a: Tenant):
    yield
    kubectl.delete_resource("pod", OVERFLOW_NAME, namespace=tenant_a.namespace)


def test_tenant_a_quota_blocks_extra_pod(tenant_a: Tenant, cleanup_overflow) -> None:
    """pods=2 is already migrate(Completed)+app; a third pod should stay Pending (or fail create)."""
    applied = kubectl.apply_manifest(
        _overflow_manifest(OVERFLOW_NAME),
        namespace=tenant_a.namespace,
    )
    # create may succeed with Pending, or API may reject — both are quota enforcement
    if applied.failed and "exceeded quota" in (applied.stderr + applied.stdout).lower():
        return

    assert applied.success, applied.stderr or applied.stdout

    deadline = time.time() + 45
    phase = ""
    while time.time() < deadline:
        phase = kubectl.pod_phase(tenant_a.namespace, OVERFLOW_NAME)
        if phase in ("Pending", "Failed"):
            break
        if phase == "Running":
            pytest.fail("overflow pod became Running — ResourceQuota did not bound tenant-a")
        time.sleep(2)

    assert phase == "Pending", f"expected Pending from quota, got {phase!r}"


def test_tenant_b_remains_healthy_when_tenant_a_hits_quota(
    tenant_a: Tenant,
    tenant_b: Tenant,
    cleanup_overflow,
) -> None:
    name = f"{OVERFLOW_NAME}-{uuid.uuid4().hex[:6]}"
    try:
        kubectl.apply_manifest(_overflow_manifest(name), namespace=tenant_a.namespace)
        # Give controller a moment; peer must stay healthy regardless.
        time.sleep(3)
        response = tenant_b.get("/health")
        assert response.status_code == 200, response.text
        assert response.json().get("status") == "healthy"
        # /health is slim ({"status":"healthy"}); 503 if Postgres is down.
        db = tenant_b.get("/db/version")
        assert db.status_code == 200, db.text
    finally:
        kubectl.delete_resource("pod", name, namespace=tenant_a.namespace)
