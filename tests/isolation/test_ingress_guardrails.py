"""Shared ALB Ingress group is a trust boundary (admission + tenant RBAC)."""

from __future__ import annotations

import pytest

from lib import kubectl
from lib.tenant import Tenant

pytestmark = [pytest.mark.isolation, pytest.mark.requires_cluster]


def test_tenant_sa_cannot_create_ingress(tenant_a: Tenant) -> None:
    result = kubectl.run(
        [
            "auth",
            "can-i",
            "create",
            "ingresses",
            "-n",
            tenant_a.namespace,
            f"--as=system:serviceaccount:{tenant_a.namespace}:test-app",
        ]
    )
    assert result.success, result.stderr
    assert result.stdout.strip() == "no"


def test_wrong_alb_group_name_is_denied(tenant_a: Tenant) -> None:
    manifest = f"""
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: qa-evil-group
  namespace: {tenant_a.namespace}
  annotations:
    alb.ingress.kubernetes.io/group.name: not-the-platform-group
spec:
  ingressClassName: alb
  rules:
    - http:
        paths:
          - path: /{tenant_a.namespace}
            pathType: Prefix
            backend:
              service:
                name: test-app
                port:
                  number: 8080
"""
    result = kubectl.apply_manifest(manifest)
    assert result.failed, "admission must reject a foreign group.name"
    blob = (result.stderr + result.stdout).lower()
    assert "denied" in blob or "validat" in blob or "group.name" in blob


def test_cross_tenant_ingress_path_is_denied(tenant_a: Tenant) -> None:
    manifest = f"""
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: qa-evil-path
  namespace: {tenant_a.namespace}
  annotations:
    alb.ingress.kubernetes.io/group.name: ntier-dev
spec:
  ingressClassName: alb
  rules:
    - http:
        paths:
          - path: /tenant-b
            pathType: Prefix
            backend:
              service:
                name: test-app
                port:
                  number: 8080
"""
    result = kubectl.apply_manifest(manifest)
    assert result.failed, "admission must reject a path outside this tenant namespace"
