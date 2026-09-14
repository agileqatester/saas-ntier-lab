from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from lib import kubectl


@dataclass(frozen=True)
class Tenant:
    """One permanent QA tenant. Edge access is path-based (ALB), not NodePort."""

    key: str
    id: str
    namespace: str
    path_prefix: str
    base_url: str
    timeout: float = 10.0
    secret_name: str | None = None
    service_dns: str = ""
    service_port: int = 8080

    def url(self, path: str) -> str:
        prefix = self.path_prefix.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url.rstrip('/')}{prefix}{path}"

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return requests.get(self.url(path), **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return requests.post(self.url(path), **kwargs)

    def exec_python(self, code: str, *, timeout: float = 60) -> kubectl.CmdResult:
        """Run Python in the app pod with the same PYTHONPATH as the Deployment."""
        return kubectl.run(
            [
                "exec",
                "-n",
                self.namespace,
                "deploy/test-app",
                "--",
                "env",
                "PYTHONUSERBASE=/tmp/py",
                "HOME=/tmp",
                "PYTHONPATH=/tmp/py/lib/python3.11/site-packages",
                "python",
                "-c",
                code,
            ],
            timeout=timeout,
        )

    def cluster_url(self, path: str = "/health") -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"http://{self.service_dns}:{self.service_port}{path}"

    def probe_cluster(self, path: str = "/health", *, timeout_sec: int = 3) -> kubectl.CmdResult:
        url = self.cluster_url(path)
        code = (
            "import urllib.request, socket\n"
            f"socket.setdefaulttimeout({timeout_sec})\n"
            f"r = urllib.request.urlopen({url!r})\n"
            "print(r.status)\n"
        )
        return self.exec_python(code, timeout=timeout_sec + 15)

    def get_secret(self, secret_id: str) -> kubectl.CmdResult:
        code = (
            "import boto3\n"
            "from botocore.exceptions import ClientError\n"
            'sm = boto3.client("secretsmanager", region_name="us-east-1")\n'
            "try:\n"
            f"    sm.get_secret_value(SecretId={secret_id!r})\n"
            '    print("ALLOW")\n'
            "except ClientError as e:\n"
            '    print("DENY:" + e.response["Error"]["Code"])\n'
            "    raise SystemExit(1)\n"
        )
        return self.exec_python(code, timeout=45)
