# NetSphere — Architecture

Enterprise Hybrid Multi-Cloud Network Management & Automation Platform.

**Status of this document:** covers the full target architecture (all 18 modules).
Only the pieces marked ✅ under "Phase 1 implementation status" in each section
are actually built in this delivery. Everything else is designed but not yet
implemented — see `ROADMAP.md` for sequencing. This file is intentionally the
single reference kept up to date as later phases land; do not fork it per phase.

## 1. Why this shape

NetSphere absorbs three things this team already has, rather than replacing
them:

- The **ip-pool-lookup** tool (Node/SQLite IPAM) — its data model and CIDR
  math are the direct ancestor of the `ipam` module here, now on Postgres with
  the organizational hierarchy (org → business unit → environment → cloud
  account) the standalone tool didn't need.
- **fwauto** / the firewall-policy-automation-design — that design already
  specifies a vendor-neutral intent model, a Panorama/FortiManager/Azure
  adapter contract, and a plan→PoA→approval→execute→verify pipeline. NetSphere's
  Automation and Change Management modules (10–11) are the home for that system
  once it's wired into a shared UI/RBAC/audit layer instead of standing alone.
  This document does not redesign fwauto — it references it.
- The **SOP for cloud network component deployment** — its 15-stage,
  Terraform-as-one-apply process is the workflow Module 10 (Automation) and
  Module 11 (Change Management) need to encode as states and approval gates,
  not a separate document to keep in sync by hand.

Building NetSphere as a new platform only makes sense if it becomes the place
these three converge — a shared IPAM, a shared RBAC/audit model, one topology
and one change-management pipeline that fwauto's firewall changes and the
SOP's Terraform network changes both flow through. The fwauto half of that
convergence is now real (see ROADMAP's "fwauto wired into the Automation
module" write-up): `/automation`'s "All changes" tab reads fwauto's
`FwIntent` pipeline and this module's own `PoaRun` table through one
normalized feed, gated by a shared RBAC union check and a shared reader of
the `audit_logs` table — without merging fwauto's code in; its own tables,
service layer, and API stay exactly where Phase 3/6 put them, and this hub
is a read layer on top. The SOP's Terraform-as-one-apply half of this
convergence is not yet started — a state-machine problem distinct enough
from fwauto's rule-diffing pipeline that it isn't just "the same wiring
again."

## 2. System architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend — Next.js 14 (App Router) + TypeScript + Tailwind         │
│  React Query for data fetching · topology via a graph library       │
│  (Phase 4) · Recharts for dashboard charts (Phase 1 uses simple      │
│  stat cards, no charting library dependency yet)                    │
└───────────────────────────────┬───────────────────────────────────┘
                                 │ HTTPS / JSON (OpenAPI-described)
┌───────────────────────────────▼───────────────────────────────────┐
│  API Gateway / Backend API — FastAPI (Python 3.11)                  │
│  ├─ Auth & AuthZ: OAuth2 password flow (dev) + JWT; OIDC/Entra ID    │
│  │  adapter point reserved for Phase 10                             │
│  ├─ RBAC middleware — role → permission → resource-scope checks     │
│  ├─ Structured JSON logging, request_id middleware                  │
│  └─ /health /ready /metrics on every service                        │
├───────────────────────────────────────────────────────────────────┤
│  Core Network Management Services (this repo's `app/services/`)     │
│  ├─ IPAM service         ✅ Phase 1/2                                │
│  ├─ Discovery service     ✅ mock providers only, Phase 1             │
│  ├─ Topology service      ⏳ Phase 4                                  │
│  ├─ Path validation       ⏳ Phase 5                                  │
│  ├─ Firewall normalization ⏳ Phase 6 (integrates fwauto's rulebase   │
│  │    normalization rather than re-implementing it)                 │
│  ├─ Automation/orchestration 🟡 Phase 7 partial — `automation_hub.py` │
│  │    (unified fwauto+POA change feed/audit, ✅); Terraform/Ansible   │
│  │    runners + the SOP's state machine ⏳ still not built           │
│  ├─ Compliance engine      ⏳ Phase 6                                 │
│  ├─ Drift detection        ⏳ Phase 6                                 │
│  └─ AI assistant           ⏳ Phase 9                                 │
├───────────────────────────────────────────────────────────────────┤
│  Provider Integration Layer — `app/providers/`                      │
│  ├─ CloudProvider ABC → AWS / Azure / GCP / OCI adapters             │
│  │    Real SDK-backed adapters: interface defined, NotImplementedError│
│  │    Mock adapters: AWS mock fully implemented (demo data);         │
│  │    Azure/GCP/OCI mocks are thin stubs — see providers/README.md   │
│  ├─ FirewallProvider ABC → PaloAlto / Fortinet adapters (interface   │
│  │    only — defers to fwauto's adapter contract, §3.2 of the        │
│  │    firewall-policy-automation-design doc, rather than a second one)│
│  └─ NetworkDeviceProvider ABC → Cisco / Juniper / generic SNMP        │
│       (interface only)                                              │
└───────────────────────────────┬───────────────────────────────────┘
                                 │
        ┌────────────────────────┼─────────────────────────┐
        ▼                        ▼                          ▼
┌───────────────┐      ┌──────────────────┐      ┌────────────────────┐
│  PostgreSQL 16  │      │  Redis            │      │  Celery workers    │
│  system of      │      │  cache + Celery   │      │  discovery jobs,   │
│  record         │      │  broker           │      │  scheduled scans   │
└───────────────┘      └──────────────────┘      └────────────────────┘
```

Supporting, designed but not built in Phase 1 (see ROADMAP): object storage
for evidence/report exports, Prometheus/Grafana scrape targets (the `/metrics`
endpoint is live; the Grafana dashboards are not), OpenSearch-compatible log
shipping, and a secrets-manager integration point (Vault / cloud secret
managers) — Phase 1 uses environment variables only, explicitly for local dev,
per the "never store credentials in source, support env vars for dev" rule.

## 3. Provider adapter pattern

```python
class CloudProvider(ABC):
    """One instance per (provider, account/subscription/project)."""

    @abstractmethod
    async def discover_networks(self) -> list[DiscoveredNetwork]: ...

    @abstractmethod
    async def discover_subnets(self, network_id: str) -> list[DiscoveredSubnet]: ...

    # ... discover_route_tables, discover_security_groups, discover_vpn,
    #     discover_interconnects, discover_load_balancers — same shape.
```

`AWSProvider(CloudProvider)`, `AzureProvider`, `GCPProvider`, `OCIProvider` are
the real, credential-backed implementations — each currently a skeleton class
whose methods raise `NotImplementedError("requires boto3 + AWS credentials — \
see providers/README.md")` (or the Azure/GCP/OCI equivalent), so the interface
is real and typed but nothing pretends to call a cloud API it can't reach.
`MockAWSProvider(CloudProvider)` implements the same interface against
generated demo data (see `docs/DEMO_DATA.md`) and is what `docker-compose`
wires up by default — the whole platform runs and demonstrates the discovery
→ IPAM → dashboard flow with zero cloud credentials. The same pattern applies
to `FirewallProvider` (PaloAlto/Fortinet) and `NetworkDeviceProvider`
(Cisco/Juniper/generic SNMP), except those three are interface-only in this
delivery — no mock yet — because Module 7/4 aren't in scope until Phase 4/6.

This is the one architectural rule that must not be violated as the platform
grows: **no cloud-SDK import, vendor-specific field name, or vendor API call
appears outside `app/providers/`.** Services and API endpoints only ever see
the normalized dataclasses (`DiscoveredNetwork`, `DiscoveredSubnet`, ...).

## 4. Data model overview

Full ERD in `docs/ERD.md`. Summary of the hierarchy this phase implements:

```
Organization
  └─ BusinessUnit
       └─ Environment (prod/staging/dev, per business unit)
            └─ CloudAccount (provider + account/subscription/project id)
                 └─ Network (VPC/VNet/VCN/on-prem network)
                      └─ Subnet
                           └─ IPAddress (individual allocation records)
```

`User` / `Role` / `Permission` / `RolePermission` / `UserRole` are independent
of that hierarchy (RBAC is evaluated per-request, not stored per-resource in
Phase 1 — resource-scoped RBAC, e.g. "this NOC operator can only see the
EMEA business unit," is a Phase 10 multi-tenancy feature, tracked in
ROADMAP).

## 5. Security architecture (Phase 1 scope)

- Passwords: bcrypt via `passlib`. JWT access tokens (short-lived) signed with
  a server-side secret from the environment; no refresh-token rotation yet
  (Phase 10 — OIDC/Entra ID replaces this token model rather than extending
  it, so building refresh rotation now would be throwaway work).
- RBAC: role → permission checks enforced as a FastAPI dependency
  (`require_permission("ipam:write")`) on every mutating endpoint. Seeded
  roles match the spec: SUPER_ADMIN, NETWORK_ADMIN, NETWORK_ENGINEER,
  CLOUD_NETWORK_ENGINEER, SECURITY_ENGINEER, NOC_OPERATOR, AUDITOR,
  READ_ONLY.
- Every mutating request writes an `audit_log` row (actor, action, resource,
  before/after JSON, request_id, result) — see `app/services/audit.py`.
  Tamper-evidence (hash chaining, per fwauto's `audit_event` design) is
  **not** implemented in Phase 1; the table is append-only at the
  application layer only. Flagged as a gap, not silently deferred.
- No destructive automation exists yet (Phase 7+), so "requires approval"
  logic for changes is designed (see ROADMAP Phase 7) but not implemented —
  there is nothing destructive to gate yet.
- Cloud credentials: the `cloud_account` table stores `credential_ref`
  (a string pointer, e.g. a Vault path or ARN) — never a raw key/secret.
  Phase 1's mock providers ignore this field entirely.

## 6. Observability

`/health` (liveness — process is up), `/ready` (readiness — DB + Redis
reachable), `/metrics` (Prometheus text format via `prometheus-fastapi-
instrumentator`) are live on the backend in Phase 1. Every request gets a
`request_id` (from the client's `X-Request-ID` header if present, else
generated) attached to its structured log line and echoed in the response
header. Distributed tracing (OpenTelemetry) is designed for but not wired up.

## 7. What Phase 1 of this repository actually contains

See `ROADMAP.md` for the full phase list. This delivery is Phase 1
(Foundation) plus the IPAM slice of Phase 2:

- FastAPI backend, SQLAlchemy models, Alembic migrations, JWT auth, RBAC,
  structured logging, health/ready/metrics — all real, all tested.
- IPAM: networks/subnets/IP records, CIDR search, overlap detection, and
  automatic subnet allocation from free space (ported and extended from the
  ip-pool-lookup tool's `lib/allocate.js` logic) — all real, all tested.
- Mock AWS discovery provider + a discovery endpoint that ingests its demo
  data into the IPAM tables, demonstrating the adapter pattern end-to-end.
- Next.js frontend: sidebar shell listing all 18 modules (most marked
  "Phase N" and disabled), a working Dashboard (live counts from the API)
  and a working IPAM page (search, list, allocate).
- Docker Compose for local dev (postgres, redis, backend, worker, frontend);
  a GitHub Actions CI workflow running backend tests.

Every other module in the original spec (topology, path analyzer, firewall
management, connectivity monitoring, automation/Terraform/Ansible execution,
change management, compliance, drift, AI assistant, multi-tenant RBAC scoping,
OIDC/SSO) is designed in this document and `ROADMAP.md` but **not implemented**
— each has a placeholder page in the frontend nav and an explicit "not
implemented, see ROADMAP Phase N" note rather than a fake/mocked screen
pretending to be real.
