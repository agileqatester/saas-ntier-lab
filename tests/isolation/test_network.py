"""Network isolation — effective connectivity, not NetworkPolicy YAML shape.

Contract:
- Tenant can reach its own Service
- Tenant cannot reach another tenant's Service (Ingress NetworkPolicy)
- Arbitrary internet TCP/80 is denied (egress default-deny)
"""

from __future__ import annotations

import pytest

from lib.tenant import Tenant

pytestmark = [pytest.mark.isolation, pytest.mark.requires_cluster]


def test_tenant_a_can_reach_own_service(tenant_a: Tenant) -> None:
    result = tenant_a.probe_cluster("/health", timeout_sec=3)
    assert result.success, result.stderr or result.stdout
    assert "200" in result.stdout


def test_tenant_b_can_reach_own_service(tenant_b: Tenant) -> None:
    result = tenant_b.probe_cluster("/health", timeout_sec=3)
    assert result.success, result.stderr or result.stdout
    assert "200" in result.stdout


def test_tenant_a_cannot_reach_tenant_b(tenant_a: Tenant, tenant_b: Tenant) -> None:
    url = tenant_b.cluster_url("/health")
    code = (
        "import urllib.request, socket\n"
        "socket.setdefaulttimeout(3)\n"
        f"urllib.request.urlopen({url!r})\n"
    )
    result = tenant_a.exec_python(code, timeout=20)
    assert result.failed, f"cross-tenant connect should fail, got: {result.stdout}"


def test_egress_to_internet_http_is_denied(tenant_a: Tenant) -> None:
    """Default-deny egress: DNS/Postgres/HTTPS may be allowed; arbitrary :80 is not."""
    code = (
        "import socket\n"
        "s = socket.socket()\n"
        "s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "    print('OPEN')\n"
        "except Exception:\n"
        "    print('DENIED')\n"
        "finally:\n"
        "    s.close()\n"
    )
    result = tenant_a.exec_python(code, timeout=20)
    assert result.success, result.stderr or result.stdout
    assert "DENIED" in result.stdout


def test_tenant_b_cannot_reach_tenant_a(tenant_a: Tenant, tenant_b: Tenant) -> None:
    url = tenant_a.cluster_url("/health")
    code = (
        "import urllib.request, socket\n"
        "socket.setdefaulttimeout(3)\n"
        f"urllib.request.urlopen({url!r})\n"
    )
    result = tenant_b.exec_python(code, timeout=20)
    assert result.failed, f"cross-tenant connect should fail, got: {result.stdout}"
