from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0

    @property
    def failed(self) -> bool:
        return self.returncode != 0


def _kubectl() -> str:
    path = shutil.which("kubectl")
    if not path:
        raise RuntimeError("kubectl not found on PATH")
    return path


def run(args: list[str], *, check: bool = False, timeout: float = 60) -> CmdResult:
    cmd = [_kubectl(), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    result = CmdResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())
    if check and result.failed:
        raise RuntimeError(f"kubectl {' '.join(args)} failed: {result.stderr or result.stdout}")
    return result


def namespace_exists(name: str) -> bool:
    return run(["get", "ns", name, "-o", "name"]).success


def deployment_ready(namespace: str, name: str = "test-app") -> bool:
    r = run(
        [
            "get",
            "deploy",
            name,
            "-n",
            namespace,
            "-o",
            "jsonpath={.status.readyReplicas}",
        ]
    )
    if r.failed or not r.stdout:
        return False
    try:
        return int(r.stdout) >= 1
    except ValueError:
        return False


def exec_in_app(namespace: str, command: list[str], *, timeout: float = 30) -> CmdResult:
    """Run a command in the tenant app pod (first ready pod for deploy/test-app)."""
    return run(
        [
            "exec",
            "-n",
            namespace,
            "deploy/test-app",
            "--",
            *command,
        ],
        timeout=timeout,
    )


def get_json(args: list[str]) -> dict:
    r = run([*args, "-o", "json"], check=True)
    return json.loads(r.stdout)
