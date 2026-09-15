"""Drop Postgres tenant role via a Job using the known-good migrator IRSA."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

from onboard_bridge import OnboardError, run

_DROP_SCRIPT = textwrap.dedent(
    """\
    import json
    import os
    import boto3
    import psycopg2
    from psycopg2 import sql

    sm = boto3.client("secretsmanager", region_name=os.environ["AWS_REGION"])
    master = json.loads(sm.get_secret_value(SecretId=os.environ["MASTER_SECRET"])["SecretString"])
    conn = psycopg2.connect(
        host=master["host"],
        dbname=master.get("dbname", "postgres"),
        user=master["username"],
        password=master["password"],
        port=int(master.get("port", 5432)),
        sslmode="require",
    )
    conn.autocommit = True
    cur = conn.cursor()
    role = os.environ["DROP_ROLE"]
    pol = os.environ["DROP_POLICY"]
    cur.execute(sql.SQL("DROP POLICY IF EXISTS {} ON sample_requests").format(sql.Identifier(pol)))
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    if cur.fetchone():
        # Tenant roles only have GRANTs (table owned by master) — revoke then drop.
        cur.execute(sql.SQL("REVOKE ALL ON TABLE sample_requests FROM {}").format(sql.Identifier(role)))
        cur.execute(sql.SQL("REVOKE ALL ON SEQUENCE sample_requests_id_seq FROM {}").format(sql.Identifier(role)))
        cur.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(sql.Identifier(role)))
        cur.execute(sql.SQL("REVOKE ALL ON DATABASE postgres FROM {}").format(sql.Identifier(role)))
        cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        print(json.dumps({"msg": "dropped", "role": role}), flush=True)
    else:
        print(json.dumps({"msg": "role_absent", "role": role}), flush=True)
    cur.close()
    conn.close()
    """
)


def _kubectl_json(args: list[str]) -> dict:
    raw = subprocess.check_output(["kubectl", *args, "-o", "json"], text=True)
    return json.loads(raw)


def ensure_migrator_sa(outputs: dict, platform: str) -> str:
    """Ensure tenant-<platform>/test-app-migrate SA exists with migrator IRSA."""
    ns = f"tenant-{platform}"
    migrator = outputs.get("migrator_irsa_role_arn")
    if not migrator:
        raise OnboardError("tofu output migrator_irsa_role_arn is empty")
    sa = textwrap.dedent(
        f"""\
        apiVersion: v1
        kind: ServiceAccount
        metadata:
          name: test-app-migrate
          namespace: {ns}
          annotations:
            eks.amazonaws.com/role-arn: "{migrator}"
        """
    )
    subprocess.run(["kubectl", "apply", "-f", "-"], input=sa, text=True, check=True)
    return ns


def drop_postgres_role(outputs: dict, tenant_id: str, timeout: int = 300) -> None:
    platform = outputs.get("platform_tenant_id") or "a"
    ns = ensure_migrator_sa(outputs, platform)
    region = outputs.get("aws_region") or "us-east-1"
    master = outputs.get("rds_secret_name")
    if not master:
        raise OnboardError("tofu output rds_secret_name is empty")

    # Match migrate.py policy name: tenant_<id>_isolation
    role = f"tenant_{tenant_id}"
    policy = f"tenant_{tenant_id}_isolation"
    suffix = int(time.time()) % 100000
    job = f"drop-role-{tenant_id}-{suffix}"
    cm = f"drop-role-script-{tenant_id}-{suffix}"

    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "drop_role.py"
        script_path.write_text(_DROP_SCRIPT)
        run(
            [
                "kubectl",
                "-n",
                ns,
                "create",
                "configmap",
                cm,
                "--from-file=drop_role.py=" + str(script_path),
            ]
        )

    manifest = textwrap.dedent(
        f"""\
        apiVersion: batch/v1
        kind: Job
        metadata:
          name: {job}
          namespace: {ns}
        spec:
          backoffLimit: 1
          ttlSecondsAfterFinished: 300
          template:
            spec:
              restartPolicy: Never
              serviceAccountName: test-app-migrate
              containers:
                - name: drop
                  image: python:3.11-slim
                  command: ["/bin/sh", "-c"]
                  args:
                    - pip install -q boto3 psycopg2-binary && python /scripts/drop_role.py
                  env:
                    - name: AWS_REGION
                      value: "{region}"
                    - name: MASTER_SECRET
                      value: "{master}"
                    - name: DROP_ROLE
                      value: "{role}"
                    - name: DROP_POLICY
                      value: "{policy}"
                  volumeMounts:
                    - name: scripts
                      mountPath: /scripts
              volumes:
                - name: scripts
                  configMap:
                    name: {cm}
        """
    )
    print(f"+ kubectl apply Job {ns}/{job}", file=sys.stderr)
    subprocess.run(["kubectl", "apply", "-f", "-"], input=manifest, text=True, check=True)

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            js = _kubectl_json(["-n", ns, "get", "job", job])
            conds = {c["type"]: c["status"] for c in js.get("status", {}).get("conditions", [])}
            if conds.get("Complete") == "True":
                subprocess.call(["kubectl", "-n", ns, "logs", f"job/{job}"])
                return
            if conds.get("Failed") == "True":
                subprocess.call(["kubectl", "-n", ns, "logs", f"job/{job}"])
                raise OnboardError(f"drop-role job {job} failed")
            time.sleep(5)
        subprocess.call(["kubectl", "-n", ns, "logs", f"job/{job}"])
        raise OnboardError(f"drop-role job {job} timed out")
    finally:
        subprocess.call(
            ["kubectl", "-n", ns, "delete", "job", job, "--ignore-not-found", "--wait=false"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.call(
            ["kubectl", "-n", ns, "delete", "cm", cm, "--ignore-not-found"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
