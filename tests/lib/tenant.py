from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from lib import kubectl

LAB_USER_HEADER = "X-Lab-User"


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
    lab_user: str = ""

    def url(self, path: str) -> str:
        prefix = self.path_prefix.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url.rstrip('/')}{prefix}{path}"

    def request(
        self,
        method: str,
        path: str = "/",
        *,
        user: str | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """HTTP call with simulated lab user (X-Lab-User).

        user=None → this tenant's default lab_user.
        user=""   → omit the header (missing-user case).
        """
        kwargs.setdefault("timeout", self.timeout)
        headers = dict(kwargs.pop("headers", None) or {})
        chosen = self.lab_user if user is None else user
        if chosen:
            headers[LAB_USER_HEADER] = chosen
        return requests.request(method.upper(), self.url(path), headers=headers, **kwargs)

    def get(self, path: str, *, user: str | None = None, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, user=user, **kwargs)

    def post(self, path: str, *, user: str | None = None, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, user=user, **kwargs)

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

    def db_query_without_tenant_context(self, sql: str = "SELECT id, tenant_id FROM sample_requests") -> kubectl.CmdResult:
        """Open a fresh DB session and run SQL *without* set_config('app.tenant_id').

        Contract: FORCE RLS must yield zero rows (fail closed), not the whole table.
        """
        assert self.secret_name, "tenant secret_name required"
        code = f"""
import json, os, boto3, psycopg2
sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
secret = json.loads(sm.get_secret_value(SecretId={self.secret_name!r})["SecretString"])
conn = psycopg2.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", "5432")),
    dbname=os.environ.get("DB_NAME") or secret.get("dbname", "postgres"),
    user=secret["username"],
    password=secret["password"],
)
conn.autocommit = True
cur = conn.cursor()
# Deliberately do NOT set app.tenant_id
cur.execute("SELECT current_setting('app.tenant_id', true)")
print("setting=" + repr(cur.fetchone()[0]))
cur.execute({sql!r})
rows = cur.fetchall()
print("count=" + str(len(rows)))
for r in rows:
    print("row=" + repr(r))
cur.close()
conn.close()
"""
        return self.exec_python(code, timeout=60)
