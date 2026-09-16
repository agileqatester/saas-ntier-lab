# Control Plane contract (lifecycle QA)

Isolation tests assert **tenant behavior**. This suite asserts **Control Plane
lifecycle behavior** with fakes — not live AWS or a cluster.

Automated: [`tests/control_plane/test_contract.py`](../control_plane/test_contract.py),
plus unit tests for SQLite concurrency, `validate_tenant_id()`, retry
classification, and desired-vs-observed `plan_action()`.

Live CLI/API checks remain in [`docs/saas/VERIFICATION.md`](../../docs/saas/VERIFICATION.md).
Those are not a substitute for this contract.

```text
Registry
   ↓
Desired state   ACTIVE | SUSPENDED | GONE
   ↓
Reconciler
   ↓
K8s + IAM + Secrets + DB
   ↓
Observed state  (namespace ∧ deploy ready ∧ replicas≥1 ∧ ingress) → ACTIVE
                (namespace ∧ replicas=0 ∧ no ingress)             → SUSPENDED
                (no namespace)                                    → GONE
```

A namespace **existing** is not ACTIVE. `discover_active()` lists unmanaged
`tenant-*` namespaces; it does not promote them.

## CREATE → ACTIVE

```text
CREATE
 ├─ secret created
 ├─ IRSA created
 ├─ DB role created
 ├─ RLS policy created
 ├─ namespace created
 ├─ Ingress created
 └─ ACTIVE
```

## SUSPEND

```text
SUSPEND
 ├─ replicas = 0
 ├─ ingress removed
 └─ data preserved (namespace + DB role remain)
```

## RESUME

```text
RESUME
 ├─ workload restored
 ├─ ingress restored
 └─ ACTIVE
```

## DELETE

```text
DELETE
 ├─ DB role removed
 ├─ namespace removed
 ├─ secret removed
 ├─ IRSA removed
 └─ registry removed
```

## Failure injection

Desired stays `ACTIVE` (or `GONE` on delete). Observed must not be treated as
success when only a prefix of the contract landed.

| Injection | Expect |
|-----------|--------|
| AWS secret creation fails | retryable or FAILED; not ACTIVE |
| IAM role creation fails | same |
| Helm fails | namespace-only ≠ ACTIVE |
| DB role creation fails | not ACTIVE |
| Ingress never gets hostname | not ACTIVE |
| kubectl times out | retryable |
| control-plane process crashes | SQLite row + desired survive; `reconcile` continues |
