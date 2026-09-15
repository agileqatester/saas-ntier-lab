"""Import bridge so control-plane can call helm/test-app/onboard_tenant.py."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ONBOARD_DIR = _REPO_ROOT / "helm" / "test-app"
if str(_ONBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_ONBOARD_DIR))

from onboard_tenant import (  # noqa: E402
    OnboardError,
    node_ip,
    onboard,
    onboard_tenant,
    require,
    run,
    run_out,
    tofu_bin,
    tofu_outputs,
    wait_ingress_hostname,
    write_alb_url,
)

__all__ = [
    "OnboardError",
    "node_ip",
    "onboard",
    "onboard_tenant",
    "require",
    "run",
    "run_out",
    "tofu_bin",
    "tofu_outputs",
    "wait_ingress_hostname",
    "write_alb_url",
]
