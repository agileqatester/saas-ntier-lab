from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from lib.tenant import Tenant

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "tenants.yaml"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "smoke: environment readiness")
    config.addinivalue_line("markers", "isolation: tenant isolation contracts")
    config.addinivalue_line("markers", "requires_cluster: needs kubectl + deployed tenants")


@pytest.fixture(scope="session")
def tenants_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def base_url(tenants_config: dict) -> str:
    url = os.environ.get("TENANT_BASE_URL") or tenants_config.get("environment", {}).get("base_url") or ""
    url = url.rstrip("/")
    if not url:
        pytest.skip(
            "Set TENANT_BASE_URL to the ALB URL "
            "(tofu -chdir=env/dev/workload output -raw alb_url)"
        )
    return url


@pytest.fixture(scope="session")
def request_timeout(tenants_config: dict) -> float:
    return float(tenants_config.get("environment", {}).get("request_timeout_seconds", 10))


@pytest.fixture(scope="session")
def secret_names() -> dict[str, str]:
    """Prefer live tofu output; fall back to tenants.yaml / env."""
    raw = os.environ.get("TENANT_SECRET_NAMES_JSON")
    if raw:
        return json.loads(raw)
    # Optional: caller exported individual names
    return {}


def _make_tenant(
    key: str,
    tenants_config: dict,
    base_url: str,
    request_timeout: float,
    secret_names: dict[str, str],
) -> Tenant:
    raw = tenants_config["tenants"][key]
    tid = str(raw["id"])
    secret = secret_names.get(tid) or raw.get("secret_name") or f"ntier-dev/rds/tenant-{tid}"
    return Tenant(
        key=key,
        id=tid,
        namespace=str(raw["namespace"]),
        path_prefix=str(raw["path_prefix"]),
        base_url=base_url,
        timeout=request_timeout,
        secret_name=secret,
        service_dns=f"test-app.{raw['namespace']}.svc.cluster.local",
        service_port=8080,
    )


@pytest.fixture(scope="session")
def tenant_a(
    tenants_config: dict, base_url: str, request_timeout: float, secret_names: dict[str, str]
) -> Tenant:
    return _make_tenant("tenant-a", tenants_config, base_url, request_timeout, secret_names)


@pytest.fixture(scope="session")
def tenant_b(
    tenants_config: dict, base_url: str, request_timeout: float, secret_names: dict[str, str]
) -> Tenant:
    return _make_tenant("tenant-b", tenants_config, base_url, request_timeout, secret_names)
