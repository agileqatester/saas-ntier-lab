# SaaS lab docs

| Doc | Purpose |
|-----|---------|
| [TENANT_CONTROL_PLANE.md](./TENANT_CONTROL_PLANE.md) | How the Tenant Control Plane is implemented (API, SQLite registry, reconciler, edge, identity, lifecycle) |
| [VERIFICATION.md](./VERIFICATION.md) | Tests and manual checks we ran on the live stack |

Authentication is out of scope. The app simulates tenant authorization with `X-Lab-User` (see root README).

Related:

- [`control-plane/README.md`](../../control-plane/README.md) — run the CLI/API
- [`tests/README.md`](../../tests/README.md) — isolation pytest suite
- [`tests/contracts/tenant_contract.md`](../../tests/contracts/tenant_contract.md) — ACTIVE tenant definition
- [`tests/contracts/control_plane_contract.md`](../../tests/contracts/control_plane_contract.md) — CREATE/SUSPEND/RESUME/DELETE
- Root [`README.md`](../../README.md) — platform architecture + add-a-tenant
