# SaaS lab — verification log

What we ran against the live Dev stack while building the Tenant Control Plane (2026-09). Re-run after major edge/identity changes.

---

## A. Isolation QA (pytest)

**Contract:** [`tests/contracts/tenant_contract.md`](../../tests/contracts/tenant_contract.md)  
**Control Plane contract (unit, no cluster):** [`tests/contracts/control_plane_contract.md`](../../tests/contracts/control_plane_contract.md)  
**How:** [`tests/README.md`](../../tests/README.md)

```bash
export TENANT_BASE_URL="$(cat env/dev/workload/.alb_url)"   # or tofu output -raw alb_url
# kubectl already pointed at the cluster
.venv-tests/bin/pytest tests/ -v
```

| When | Edge | Result |
|------|------|--------|
| After fresh apply + scripted onboard | Legacy NodePort ALB | **23 passed** |
| After Phase A (`alb_controller` + ClusterIP Ingress) | Shared LBC ALB | **23 passed** |

Coverage (summary):

- **Smoke:** namespace, Ready deploy, `/health`, DB reachable (`a`/`b`)
- **Authorization:** `X-Lab-User` allow/deny; header is not a Postgres tenant switch (`/health` stays open)
- **Database:** own rows OK; spoof `tenant_id` in query/body blocked; missing RLS context → no rows
- **IAM:** each tenant reads only its secret
- **Network:** east-west blocked between tenant Services
- **Compute:** ResourceQuota blocks extra pods; peer tenant stays healthy

Fixtures stay on permanent tenants `a`/`b` in `tests/config/tenants.yaml` (path-based URLs — not NodePorts).

---

## B. Control plane — automated contract (no cluster)

```bash
.venv-tests/bin/pytest tests/ -v -m unit
```

Covers SQLite transactions / version conflicts, shared `validate_tenant_id()`,
retry classification, reconciler plans, and CREATE/SUSPEND/RESUME/DELETE plus
injected secret/IAM/Helm/DB/Ingress failures. Namespace existence is not treated
as ACTIVE.

Live create/lifecycle below is still the cluster proof; it is not the only CP test.

---

## C. Control plane — create (identity out of OpenTofu)

```bash
control-plane/.venv/bin/python control-plane/cli.py create f
# or API: POST http://127.0.0.1:8088/tenants {"id":"f"}
```

| Check | Result |
|-------|--------|
| Registry `owned_by` | `control_plane` |
| `terraform.tfvars` / `tofu output tenant_ids` | No `f` (identity not in OpenTofu) |
| SM secret tagged | `ManagedBy=tenant-control-plane` |
| `GET /tenant-f/health` | `tenant_id: f`, DB connected |
| Write/read `/db/items` + `/db/records` | Own data only |

---

## D. Control plane — lifecycle

Exercised on tenant `f` (then cleaned up):

| Step | Expected | Observed |
|------|----------|----------|
| `POST …/suspend` | `SUSPENDED`, replicas=0 | ALB **503** on `/tenant-f/health` |
| `POST …/resume` | `ACTIVE` again | Health OK |
| `DELETE …/f` | Registry 404, ns gone | SM + IRSA removed **after** DB role drop |
| Peer `tenant-a` | Unaffected | Health OK |

Delete is fail-closed: if the drop-role Job fails, status is `DELETE_FAILED` and AWS identity stays. Retry `cli.py delete`.

---

## E. Polish — adopt, CLI, DROP ROLE

| Step | Result |
|------|--------|
| `cli.py adopt a b c d e` | All listed `owned_by: control_plane` |
| `manage_tenant_identity=false` + tofu `state rm` of per-tenant identity | AWS objects kept; OpenTofu no longer manages them |
| `cli.py create g` → health | OK |
| `cli.py delete g` | Log `{"msg":"dropped","role":"tenant_g"}` + secret/role gone |
| `onboard_tenant.py --help` | Deprecation text points at `cli.py` |

---

## F. Manual edge / isolation (spot checks)

Useful alongside pytest:

```bash
ALB="$(cat env/dev/workload/.alb_url)"
curl -sS "$ALB/tenant-a/health"
curl -sS "$ALB/tenant-b/health"
curl -sS -H 'X-Lab-User: alice' -X POST "$ALB/tenant-a/db/items" \
  -H 'Content-Type: application/json' -d '{"message":"from-a"}'
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-a/db/records?tenant_id=b&limit=5"   # still tenant a
curl -sS -H 'X-Lab-User: alice' "$ALB/tenant-b/"   # 403

kubectl run netcheck -n tenant-b --rm -it --image=busybox --restart=Never -- \
  wget -qO- --timeout=3 http://test-app.tenant-a.svc.cluster.local:8080/health
# pass: timeout / fail (NetworkPolicy)
```

---

## G. Destroy habit

Workload destroy is slow (EKS/RDS often 10–20+ min). Close the `my_ip` quote and include `/32`:

```bash
cd env/dev/workload
tofu destroy -var-file=terraform.tfvars \
  -var="my_ip=$(curl -s https://checkip.amazonaws.com)/32"
```

Keep `env/dev/network` applied. Control-plane-owned SM/IRSA for remaining tenants are **not** in tofu state — delete tenants via `cli.py delete` before destroy, or clean leftover secrets/roles in AWS if you skip that.
