"""Reconciler is desired vs observed — not namespace-exists => ACTIVE."""

from __future__ import annotations

import pytest

from observe import Observed
from reconcile import plan_action

pytestmark = [pytest.mark.unit]


def _infra_active(**overrides) -> Observed:
    base = dict(
        namespace=True,
        deploy_ready=True,
        replicas=1,
        ingress=True,
        service=True,
        network_policy=True,
        resource_quota=True,
        irsa_sa=True,
    )
    base.update(overrides)
    return Observed(**base)


def test_missing_namespace_provisions() -> None:
    plan = plan_action("ACTIVE", Observed(), "FAILED")
    assert plan.action == "provision"


def test_suspended_namespace_resumes() -> None:
    obs = Observed(namespace=True, deploy_ready=False, replicas=0, ingress=False)
    plan = plan_action("ACTIVE", obs, "SUSPENDED")
    assert plan.action == "resume"


def test_failed_partial_repairs_not_resume() -> None:
    obs = Observed(namespace=True, deploy_ready=False, replicas=0, ingress=False)
    plan = plan_action("ACTIVE", obs, "FAILED")
    assert plan.action == "repair"
    plan = plan_action("ACTIVE", obs, "DRIFT")
    assert plan.action == "repair"


def test_infra_without_netpol_is_not_active() -> None:
    obs = _infra_active(network_policy=False)
    assert not obs.matches_active()
    plan = plan_action("ACTIVE", obs, "ACTIVE")
    assert plan.action == "repair"


def test_fully_active_is_noop() -> None:
    obs = _infra_active()
    plan = plan_action("ACTIVE", obs, "ACTIVE")
    assert plan.action == "none"


def test_suspend_when_ingress_still_up() -> None:
    obs = _infra_active()
    plan = plan_action("SUSPENDED", obs, "ACTIVE")
    assert plan.action == "suspend"


def test_gone_deletes_until_namespace_absent() -> None:
    obs = Observed(namespace=True, replicas=0, ingress=False)
    assert plan_action("GONE", obs, "DELETE_FAILED").action == "delete"
    assert plan_action("GONE", Observed(), "DELETE_FAILED").action == "purge_registry"
