"""Ensure tenant id exists in OpenTofu (tfvars + apply) before k8s onboard."""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from onboard_bridge import OnboardError, tofu_bin, tofu_outputs


_TENANT_IDS_RE = re.compile(
    r"^(\s*tenant_ids\s*=\s*)\[([^\]]*)\](\s*)$",
    re.MULTILINE,
)


def _parse_ids(inner: str) -> list[str]:
    return re.findall(r'"([a-z][a-z0-9]{0,15})"', inner)


def _format_ids(ids: list[str]) -> str:
    return "[" + ", ".join(f'"{tid}"' for tid in ids) + "]"


def public_ip_cidr() -> str:
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as resp:
        ip = resp.read().decode().strip()
    if not ip:
        raise OnboardError("could not detect public IP for my_ip")
    return f"{ip}/32"


def ensure_tenant_in_tfvars(tfvars: Path, tenant_id: str) -> bool:
    """Append tenant_id to tenant_ids if missing. Returns True if file changed."""
    text = tfvars.read_text()
    match = _TENANT_IDS_RE.search(text)
    if not match:
        raise OnboardError(f"no tenant_ids = [...] line in {tfvars}")
    ids = _parse_ids(match.group(2))
    if tenant_id in ids:
        return False
    ids.append(tenant_id)
    new_line = f"{match.group(1)}{_format_ids(ids)}{match.group(3)}"
    text = text[: match.start()] + new_line + text[match.end() :]
    tfvars.write_text(text)
    print(f"+ updated {tfvars}: tenant_ids -> {ids}", file=sys.stderr)
    return True


def apply_workload(tofu_dir: Path, my_ip: str | None = None) -> None:
    cidr = my_ip or public_ip_cidr()
    tfvars = tofu_dir / "terraform.tfvars"
    cmd = [
        tofu_bin(),
        "apply",
        "-auto-approve",
        f"-var-file={tfvars.name}",
        f"-var=my_ip={cidr}",
    ]
    print("+", " ".join(cmd), file=sys.stderr)
    subprocess.check_call(cmd, cwd=str(tofu_dir))


def ensure_infra(tofu_dir: Path, tenant_id: str, my_ip: str | None = None) -> dict:
    """Make sure IRSA/secret/ALB/NodePort exist for tenant_id; apply if needed."""
    tfvars = tofu_dir / "terraform.tfvars"
    if not tfvars.exists():
        raise OnboardError(f"missing {tfvars} (gitignored local file)")

    changed = ensure_tenant_in_tfvars(tfvars, tenant_id)
    outputs = tofu_outputs(str(tofu_dir))
    ids = outputs.get("tenant_ids") or []
    irsa = outputs.get("tenant_irsa_role_arns") or {}
    already = tenant_id in ids and tenant_id in irsa
    if changed or not already:
        apply_workload(tofu_dir, my_ip=my_ip)
        outputs = tofu_outputs(str(tofu_dir))
    return outputs
