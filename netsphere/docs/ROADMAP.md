# NetSphere — Development Roadmap

Phases as specified by the product brief. Each phase's "Delivered" column is
filled in only once code, tests, and docs for it actually exist in this repo
— an empty column is not a promise, it's an honest "not started."

| Phase | Scope | Delivered in this repo? |
|---|---|---|
| **1. Foundation** | Repo, backend, frontend, Postgres, auth, RBAC, Docker, CI, logging | ✅ Yes — this delivery |
| **2. Network source of truth** | Networks, subnets, IPAM, devices, interfaces, inventory | ✅ Yes — IPAM (networks/subnets/IP addresses, search, allocate) + device/interface inventory (SNMP mock, Network Inventory page), including a best-effort cross-link from an interface's IP into an existing IPAM subnet |
| **3. Cloud discovery** | AWS/Azure/GCP/OCI adapters | ✅ Interface + mocks for all four clouds. ⏳ Real SDK adapters (all four currently `NotImplementedError` by design) |
| **4. Topology** | Network graph, relationships | ⏳ Not started |
| **5. Path Analyzer** | Route lookup, firewall/security validation, end-to-end path | ⏳ Not started |
| **6. Security** | Firewall/NSG/SG normalization, compliance | ⏳ Not started (converges with fwauto — see ARCHITECTURE §1) |
| **7. Automation** | Terraform, Ansible, approval workflow, change management | ⏳ Not started (converges with fwauto's plan/PoA/approval/execute pipeline and the deployment SOP's Terraform-as-one-apply flow) |
| **8. Monitoring** | VPN, BGP, connectivity, alerts | ⏳ Not started |
| **9. AI** | Network assistant, root-cause analysis, NL search, Terraform generation | ⏳ Not started |
| **10. Enterprise** | HA, Kubernetes, multi-tenancy, advanced RBAC, SSO/OIDC, audit hardening, reporting | ⏳ Not started |

## Immediate next session's likely candidates (not yet started, in priority order)

1. **`POST /v1/simulate`-equivalent read-only path check**, per the firewall
   design doc's own recommendation to ship the read-only value first —
   this is Module 6 (Path Analyzer) intersecting Module 7's existing
   `firewall-policy-automation-design.md` §3.8 API surface. Reuse that
   API shape rather than inventing a second one.
2. **Wire fwauto in as the Automation module's execution engine** rather
   than writing a second Terraform/Ansible runner — see ARCHITECTURE §1.
   This is the highest-leverage phase-7 step because most of the design
   work is already done in `firewall-policy-automation-design.md`.
3. Resource-scoped RBAC (Phase 10 item, but cheap to add early if the team
   starts onboarding more than one business unit before Phase 10 proper).
4. Routes/route-tables (the other half of "Network source of truth" per
   the original spec) — `route_tables`/`routes` tables, consumed later by
   the Phase 5 path validator; not started, no mock provider yet.
5. Real cloud SDK adapters (`providers/aws.py`/`azure.py`/`gcp.py`/`oci.py`),
   once there's an actual credential/secrets-manager story to hang them off
   of — currently all four correctly raise `NotImplementedError`.

## Just completed: Azure/GCP/OCI mock discovery (Phase 3 close-out)

- **Mocks**: `providers/mock/azure.py` (3 subscriptions / 4 VNets / 12
  subnets), `providers/mock/gcp.py` (3 projects / 4 VPCs / 10 subnets,
  uneven per-VPC subnet counts), `providers/mock/oci.py` (2 compartments /
  3 VCNs / 8 subnets) — same shape as `providers/mock/aws.py`, deterministic,
  no network calls, disjoint CIDR ranges from each other and from the AWS/
  SNMP demo data (documented in `providers/mock/README.md`) so the overlap
  detector never false-flags the seed data against itself.
- **API**: `POST /api/v1/discovery/{azure|gcp|oci}?cloud_account_id=&account_identifier=`,
  same shape as the existing `/discovery/aws`. The old blanket 501 for
  these three provider names is gone — the catch-all route now only 501s
  for a genuinely unimplemented provider name (currently none).
- **Seed**: `app/seed.py` generalized its AWS-only cloud-account/discovery
  block into a loop over all four providers (`_CLOUD_PROVIDERS`), so a
  fresh `docker compose up` seeds and discovers 16 networks / 45 subnets
  across all four clouds automatically, zero manual API calls.
- **Dashboard**: no code changes needed — `networks_by_provider` was
  already computed generically from `Network.provider`, so it started
  reporting real Azure/GCP/OCI counts automatically once data existed.
- **Tests**: 4 new tests (each provider's mock discovery, an explicit
  check of the documented demo totals for all four clouds together, and
  the unimplemented-provider path now returns 404 instead of 501 since
  nothing is unimplemented) — 47 total, all passing against a real
  Postgres.

## Just completed: device/interface inventory (Phase 2 close-out)

- **Tables**: `devices`, `interfaces` (migration `41e3e82c1344`), FK'd to
  `environments` the same way cloud accounts are, so on-prem inventory
  hangs off the same org hierarchy as everything else.
- **Provider adapter**: `NetworkDeviceProvider` ABC (`providers/base.py`)
  gained a real `discover_devices()` contract; `providers/snmp.py` is the
  real adapter (`NotImplementedError`, same as `aws.py`/`azure.py`/etc — a
  Phase 3 task: `pysnmp` + IF-MIB/SNMPv2-MIB walks); `providers/mock/snmp.py`
  is the fully-implemented mock (4 demo devices/8 interfaces across 2
  sites), same role as `MockAWSProvider`.
- **Discovery + cross-link**: `POST /api/v1/discovery/snmp?environment_id=&site=`
  upserts idempotently by `(environment_id, hostname)` / `(device_id, name)`.
  `app/services/devices.py` also does a best-effort lookup of each
  interface's `ip_address` against existing IPAM subnets and sets
  `interfaces.subnet_id` when it finds a match — the actual "network
  source of truth" convergence point between inventory and IPAM.
- **API**: `GET/POST /api/v1/devices`, `GET /api/v1/devices/{id}/interfaces`,
  behind a new `inventory:*` permission area.
- **UI**: Network Inventory page (device list + interface detail pane,
  same split layout as IPAM); Dashboard gained a device-count row.
- **Seed**: `python -m app.seed` now also runs mock SNMP discovery
  automatically (same rationale as the AWS auto-discovery fix), so a
  fresh `docker compose up` populates Network Inventory with zero manual
  API calls.
- **Tests**: 7 new tests (discovery ingestion, idempotency, site filter,
  404 on unknown environment, the subnet cross-link, and RBAC gating) —
  43 total, all passing against a real Postgres.

## Explicitly out of scope for this delivery (do not infer partial support)

- No OIDC/Entra ID integration — local JWT only.
- No live cloud API calls anywhere — every real provider adapter (as
  opposed to the mock ones under `providers/mock/`) raises
  `NotImplementedError` with a message naming what it needs.
- No Terraform/Ansible execution — no shell-out, no state file handling.
- No Kubernetes manifests — Docker Compose only. The backend is written
  stateless-service-first (no local file state, config via env vars) so a
  future Helm chart doesn't require an app rewrite, but no chart exists yet.
- No Vault/cloud-secrets-manager integration — `credential_ref` is a plain
  string column with nothing reading it yet.
- No tamper-evident (hash-chained) audit log — plain audit table only.
