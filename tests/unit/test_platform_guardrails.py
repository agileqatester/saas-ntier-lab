"""Helm templates for shared-ALB admission and egress NetworkPolicy."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.unit]


def _helm_template(chart: Path, extra: list[str]) -> str:
    return subprocess.check_output(
        ["helm", "template", "qa", str(chart), *extra],
        text=True,
    )


def test_guardrails_require_shared_group_and_alb_class() -> None:
    rendered = _helm_template(
        ROOT / "helm" / "platform-guardrails",
        ["--set", "groupName=ntier-dev", "--set", "ingressClass=alb"],
    )
    assert "kind: ValidatingAdmissionPolicy" in rendered
    assert "group.name" in rendered
    assert "ntier-dev" in rendered
    assert "ingressClassName" in rendered
    assert "Deny" in rendered


def test_networkpolicy_has_egress_dns_postgres_and_https() -> None:
    rendered = _helm_template(
        ROOT / "helm" / "test-app",
        [
            "--set",
            "tenant.id=a",
            "--set",
            "networkPolicy.enabled=true",
            "--set",
            "networkPolicy.egress.enabled=true",
            "--set-json",
            'networkPolicy.egress.postgresCidrs=["10.0.1.0/24"]',
        ],
    )
    assert "Egress" in rendered
    assert "k8s-app: kube-dns" in rendered
    assert "port: 5432" in rendered
    assert "port: 443" in rendered
    role = rendered.split("kind: Role", 1)[1].split("---", 1)[0]
    assert "networking.k8s.io" not in role
