"""reconcile_one must wire plan_action + validate_active_contract (no silent ACTIVE)."""

from __future__ import annotations

from pathlib import Path

import pytest

from observe import Observed
from reconcile import reconcile_one
from store import TenantStore

pytestmark = [pytest.mark.unit]


class _PartialObserver:
    """Namespace present but isolation objects missing — not contract-ACTIVE."""

    def observe(self, tenant_id: str, item: dict) -> Observed:
        return Observed(
            namespace=True,
            deploy_ready=True,
            replicas=1,
            ingress=True,
            service=True,
            network_policy=False,
            resource_quota=True,
            irsa_sa=True,
        )


class _FullObserver:
    def observe(self, tenant_id: str, item: dict) -> Observed:
        return Observed(
            namespace=True,
            deploy_ready=True,
            replicas=1,
            ingress=True,
            service=True,
            network_policy=True,
            resource_quota=True,
            irsa_sa=True,
        )


def test_reconcile_does_not_mark_partial_provision_active(tmp_path: Path) -> None:
    """Fake provisioner writes ACTIVE, but observer still lacks NetPol/Quota → DRIFT.

    Catches the regression where reconcile trusted the provisioner status and
    skipped observe → validate_active_contract.
    """
    store = TenantStore(tmp_path / "t.db")
    store.upsert("z", desired_status="ACTIVE", status="PROVISIONING")

    class _MissingThenPartial:
        """First look: no namespace (→ provision). After provision: still incomplete."""

        def __init__(self) -> None:
            self.calls = 0

        def observe(self, tenant_id: str, item: dict) -> Observed:
            self.calls += 1
            if self.calls == 1:
                return Observed()
            return Observed(
                namespace=True,
                deploy_ready=True,
                replicas=1,
                ingress=True,
                service=True,
                network_policy=False,
                resource_quota=False,
                irsa_sa=True,
            )

    def provision_lie(store, tofu_dir, tenant_id, **kwargs):
        # Pretend success even though isolation objects are missing.
        store.upsert(
            tenant_id,
            desired_status="ACTIVE",
            status="ACTIVE",
            owned_by="control_plane",
            secret_name=f"secret/{tenant_id}",
            irsa_role_arn=f"arn:role/{tenant_id}",
            error=None,
        )

    observer = _MissingThenPartial()
    result = reconcile_one(
        store,
        Path("/tmp"),
        "z",
        observer=observer,
        provision_fn=provision_lie,
        resume_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no resume")),
    )
    assert observer.calls >= 2  # plan observe + post-action contract observe
    assert result["status"] == "DRIFT"
    assert store.get("z")["status"] == "DRIFT"
    err = result.get("error") or ""
    assert "network_policy" in err or "resource_quota" in err


def test_failed_partial_plans_repair_not_resume(tmp_path: Path) -> None:
    store = TenantStore(tmp_path / "t.db")
    store.upsert(
        "z",
        desired_status="ACTIVE",
        status="FAILED",
        owned_by="control_plane",
        secret_name="s/z",
        irsa_role_arn="arn:z",
    )
    called: list[str] = []

    def repair(store, tofu_dir, tenant_id, **kwargs):
        called.append("repair")
        store.upsert(
            tenant_id,
            status="ACTIVE",
            owned_by="control_plane",
            secret_name="s/z",
            irsa_role_arn="arn:z",
            error=None,
        )

    def resume(*_a, **_k):
        called.append("resume")
        raise AssertionError("resume must not run for FAILED")

    # Observe stays partial after repair → post-action contract gate → DRIFT.
    result = reconcile_one(
        store,
        Path("/tmp"),
        "z",
        observer=_PartialObserver(),
        provision_fn=repair,
        resume_fn=resume,
    )
    assert called == ["repair"]
    assert result["status"] == "DRIFT"
    assert "network_policy" in (result.get("error") or "")


def test_contract_gate_on_noop_rejects_missing_identity(tmp_path: Path) -> None:
    """Infra looks complete but CP registry identity missing → DRIFT, not ACTIVE."""
    store = TenantStore(tmp_path / "t.db")
    store.upsert(
        "z",
        desired_status="ACTIVE",
        status="ACTIVE",
        owned_by="control_plane",
        secret_name=None,
        irsa_role_arn="arn:z",
    )
    result = reconcile_one(
        store,
        Path("/tmp"),
        "z",
        observer=_FullObserver(),
        provision_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no repair")),
        resume_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no resume")),
    )
    assert result["status"] == "DRIFT"
    assert "secret_name" in (result.get("error") or "")

    store.upsert("z", secret_name="s/z", status="DRIFT")
    ok = reconcile_one(
        store,
        Path("/tmp"),
        "z",
        observer=_FullObserver(),
        provision_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no repair")),
    )
    assert ok["status"] == "ACTIVE"
    assert ok.get("error") is None
