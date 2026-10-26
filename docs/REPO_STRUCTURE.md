# NetSphere — Repository structure

```
netsphere/
├── docker-compose.yml         postgres + redis + backend + worker + frontend
├── .env.example                copy to .env for local dev
├── Makefile                    up/down/logs/migrate/seed/test/lint shortcuts
├── docs/
│   ├── ARCHITECTURE.md         system design, provider adapter pattern, what's built vs designed
│   ├── ERD.md                  entity-relationship diagram (mermaid) + tables not yet migrated
│   ├── API_SPEC.md             endpoint reference
│   ├── SECURITY.md             what's implemented vs explicitly not
│   └── ROADMAP.md              phase-by-phase status
├── backend/                    FastAPI + SQLAlchemy + Alembic (Python 3.11)
│   ├── app/
│   │   ├── main.py             app factory, middleware, router mounting
│   │   ├── config.py           pydantic-settings — the only place env vars are read
│   │   ├── db.py                engine/session/Base
│   │   ├── security.py          JWT + bcrypt
│   │   ├── deps.py              get_current_user, require_permission
│   │   ├── logging_config.py    structured JSON logs + request_id
│   │   ├── worker.py             Celery app (one demo task; real jobs are Phase 3/7)
│   │   ├── seed.py               idempotent local-dev seed (roles, admin user, demo org tree)
│   │   ├── models/               SQLAlchemy models: user/org/network/device/audit
│   │   ├── schemas/              Pydantic request/response shapes
│   │   ├── services/
│   │   │   ├── cidr.py           pure IPv4 CIDR math (no DB)
│   │   │   ├── allocate.py       pure subnet-allocation math (no DB) — unit tested in isolation
│   │   │   ├── ipam.py            DB-aware IPAM orchestration (search/overlaps/allocate)
│   │   │   ├── devices.py         device/interface discovery -> DB upsert + IPAM subnet cross-link
│   │   │   ├── discovery.py       cloud provider discovery -> DB upsert
│   │   │   └── audit.py           audit_log writer
│   │   ├── providers/
│   │   │   ├── base.py            CloudProvider/FirewallProvider/NetworkDeviceProvider ABCs
│   │   │   ├── aws.py azure.py gcp.py oci.py   real cloud adapters — NotImplementedError by design
│   │   │   ├── snmp.py            real device-discovery adapter — NotImplementedError by design
│   │   │   ├── mock/aws.py         fully-implemented mock cloud provider
│   │   │   └── mock/snmp.py        fully-implemented mock device provider
│   │   ├── core/rbac_seed.py      permission codes + role grants (data, not migrated)
│   │   └── api/v1/
│   │       ├── router.py          mounts every endpoint module
│   │       └── endpoints/         health, auth, orgs, ipam, devices, discovery, dashboard
│   ├── alembic/                  migrations (versions/f2d5ad919681_initial_schema.py is Phase 1's schema)
│   ├── tests/                    pytest — pure-logic unit tests + API/RBAC integration tests
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/                    Next.js 14 (App Router) + TypeScript + Tailwind
    ├── app/
    │   ├── login/page.tsx         email/password -> JWT in localStorage
    │   ├── (shell)/layout.tsx     sidebar with all 18 modules, redirects to /login if no token
    │   ├── (shell)/dashboard/     live stat cards from /api/v1/dashboard/summary
    │   ├── (shell)/ipam/          search, network/subnet browser, allocate flow
    │   ├── (shell)/network-inventory/  device list + interface detail pane
    │   └── (shell)/[module]/      generic "not implemented — see ROADMAP Phase N" page for every other module
    ├── lib/api.ts                 fetch wrapper: attaches JWT, throws ApiError on non-2xx
    ├── next.config.js             rewrites /api/* to the backend (same-origin in the browser)
    └── Dockerfile
```

## Where things are NOT (and why)

- No `k8s/` directory — Compose only in Phase 1 (see ROADMAP's explicit
  out-of-scope list). The backend is written stateless/env-var-configured
  so a future Helm chart is additive, not a rewrite.
- No `terraform/` or `ansible/` directories — Phase 7 wires in `fwauto`
  and/or a new automation runner; nothing to scaffold yet without
  duplicating that design.
- `alembic/versions/` has two revisions so far: the Phase 1 initial schema
  and Phase 2's `devices`/`interfaces` tables. Every schema change from
  here is a new revision via `alembic revision --autogenerate`, never a
  hand-edit of an existing one.
