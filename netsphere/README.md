# NetSphere

**Enterprise Hybrid Multi-Cloud Network Management & Automation Platform.**

This is Phase 1 (Foundation), all of Phase 2 (Network source of truth —
IPAM and device/interface inventory), and Phase 3's mock discovery for
all four clouds, built and tested end to end — not a scaffold with TODOs
where the logic should be. See `docs/ARCHITECTURE.md` for the full target
design and `docs/ROADMAP.md` for exactly what's built vs.
designed-but-not-started. Read those two first; this README is just
"how do I run it."

## What's actually here

- IPAM: networks/subnets, IP search, overlap/conflict detection, and
  automatic subnet allocation from free space (search a network, tell it
  how many machines you need, get a correctly-aligned free CIDR).
- Device/interface inventory: on-prem routers/switches/firewalls and
  their interfaces, with a best-effort cross-link from an interface's IP
  into an existing IPAM subnet — the actual convergence point between the
  two halves of "network source of truth."
- Mock discovery providers for all four clouds the spec names — AWS (3
  accounts / 5 VPCs / 15 subnets), Azure (3 subscriptions / 4 VNets / 12
  subnets), GCP (3 projects / 4 VPCs / 10 subnets), OCI (2 compartments /
  3 VCNs / 8 subnets) — plus a mock SNMP provider (4 devices / 8
  interfaces across 2 sites). All five ingest into the real tables,
  proving the provider adapter pattern without needing real cloud
  credentials or SNMP access.
- JWT auth + RBAC (8 seeded roles, permission-per-endpoint, including an
  `inventory:*` area for devices).
- Structured logging, `/health`, `/ready`, `/metrics`.
- A Next.js frontend: working Dashboard, IPAM, and Network Inventory
  pages, plus a full 18-module sidebar where every other module is an
  honest "not implemented yet, see ROADMAP" page rather than a fake screen.
- 47 passing backend tests (pure CIDR/allocation math + API/RBAC
  integration tests against a real Postgres).

Everything else in the original spec (topology, path analyzer, firewall
management, automation/Terraform/Ansible, change management, compliance,
monitoring, AI assistant, SSO, multi-tenancy, and real cloud SDK adapters
for the four providers above) is designed in `docs/` but not built — see
`docs/ROADMAP.md`.

## Running it locally

### Option A — Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up --build
```

This starts Postgres, Redis, the backend (runs migrations + seeds demo
data on startup), a Celery worker, and the frontend.

- Frontend: http://localhost:3000 (sign in with the seeded admin — see below)
- Backend API docs: http://localhost:8000/docs
- Seeded login: `admin@netsphere.local` / `ChangeMe123!` (from `.env`'s
  `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` — change these before any
  shared deployment)

The seed step (`python -m app.seed`, run automatically on backend startup)
creates the demo org hierarchy, the mock cloud accounts for all four
clouds, and runs every mock discovery flow — AWS/Azure/GCP/OCI
(networks/subnets) and SNMP (devices/interfaces) — so the Dashboard,
IPAM, and Network Inventory pages all show real data (16 networks / 45
subnets across 4 clouds, 4 devices / 8 interfaces) the first time you
open them, with no manual API calls needed. This is safe to run
unattended since every mock provider makes no real network calls and
uses deterministic fake data.

To re-run discovery by hand later (e.g. after changing the mock data, or
against a real provider once one is wired in):

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -d "username=admin@netsphere.local&password=ChangeMe123!" \
  -H "Content-Type: application/x-www-form-urlencoded" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# list the demo cloud accounts the seed created
curl -s localhost:8000/api/v1/orgs/cloud-accounts -H "Authorization: Bearer $TOKEN"

# run mock AWS discovery against one of them (use its id from above) --
# safe to re-run any time, upserts by (cloud_account_id, cidr)
curl -s -X POST "localhost:8000/api/v1/discovery/aws?cloud_account_id=<id>&account_identifier=<account>" \
  -H "Authorization: Bearer $TOKEN"
```

Then open the Dashboard and IPAM pages in the frontend to see it show up.

### Option B — run backend and frontend directly (faster iteration)

Needs Postgres 16 and Redis running locally (`postgresql-16` +
`redis-server` packages, or point `DATABASE_URL`/`REDIS_URL` at anything
reachable).

```bash
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://netsphere:netsphere@localhost:5432/netsphere
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```

## Running the tests

```bash
cd backend
# needs a netsphere_test database the test user can create tables in
python3 -m pytest -q
```

36 tests: pure CIDR/allocation math (no DB), plus API + RBAC integration
tests against a real Postgres (schema is created/dropped per test via
`Base.metadata`, not through Alembic — keeps tests fast and independent
of migration history).

## Directory guide

See `docs/REPO_STRUCTURE.md` for the annotated file tree.

## Contributing to later phases

Read `docs/ROADMAP.md`'s "immediate next session" list before starting —
it's ordered by what's actually the highest-leverage next step, and it
calls out where a later phase should **reuse** an existing design
(`firewall-policy-automation-design.md` for firewall/automation, the SOP
doc for the Terraform-as-one-apply change flow) instead of re-designing
it from scratch.
