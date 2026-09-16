"""Reconciler is desired vs observed — not namespace-exists => ACTIVE."""

from __future__ import annotations

import pytest

from observe import Observed
from reconcile import plan_action

pytestmark = [pytest.mark.unit]


def test_missing_namespace_provisions() -> None:
    plan = plan_action("ACTIVE", Observed(), "FAILED")
    assert plan.action == "provision"


def test_partial_namespace_resumes() -> None:
    obs = Observed(namespace=True, deploy_ready=False, replicas=0, ingress=False)
    plan = plan_action("ACTIVE", obs, "DRIFT")
    assert plan.action == "resume"


def test_fully_active_is_noop() -> None:
    obs = Observed(namespace=True, deploy_ready=True, replicas=1, ingress=True)
    plan = plan_action("ACTIVE", obs, "ACTIVE")
    assert plan.action == "none"


def test_suspend_when_ingress_still_up() -> None:
    obs = Observed(namespace=True, deploy_ready=True, replicas=1, ingress=True)
    plan = plan_action("SUSPENDED", obs, "ACTIVE")
    assert plan.action == "suspend"


def test_gone_deletes_until_namespace_absent() -> None:
    obs = Observed(namespace=True, replicas=0, ingress=False)
    assert plan_action("GONE", obs, "DELETE_FAILED").action == "delete"
    assert plan_action("GONE", Observed(), "DELETE_FAILED").action == "purge_registry"
