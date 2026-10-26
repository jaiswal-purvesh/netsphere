# NetSphere — API reference (Phase 1)

Full interactive OpenAPI docs are served live at `/docs` (Swagger UI) and
`/redoc` once the backend is running — this file is a stable, greppable
summary for people not running the service, not a duplicate source of
truth (the FastAPI route decorators are that).

All endpoints below are prefixed `/api/v1`. Endpoints marked 🔒 require a
bearer token; the permission code required is noted.

## Health / ops (no auth)

```
GET  /health                    liveness only
GET  /ready                     checks Postgres + Redis
GET  /metrics                   Prometheus text format
```
(All three are also served un-versioned at the root, e.g. `/health`.)

## Auth

```
POST /api/v1/auth/login         OAuth2 password form -> { access_token, token_type }
GET  /api/v1/auth/me       🔒    current user + roles
```

## Organization hierarchy 🔒 admin:view / admin:create

```
GET/POST /api/v1/orgs/organizations
GET/POST /api/v1/orgs/business-units
GET/POST /api/v1/orgs/environments
GET/POST /api/v1/orgs/cloud-accounts     (list is ipam:view — needed to pick an account when creating a network)
```

## IPAM 🔒 ipam:view / ipam:create

```
GET  /api/v1/ipam/search?ip=10.4.12.37
     -> { ip, matches: [...], best_match }           # longest-prefix-match, networks + subnets

GET  /api/v1/ipam/overlaps
     -> { conflicts: [{ type: duplicate|nested, cross_provider, a, b }] }
     Every overlapping pair across the whole table — the global conflict
     banner the IPAM page shows on load.

GET  /api/v1/ipam/networks/{id}/overlaps
     -> { network: { id, cidr }, conflicts: [{ type, cross_provider, network }] }
     Same duplicate/nested classification, scoped to one network's current
     CIDR against every other network — an on-demand "does this CIDR
     conflict with anything" probe, not just the whole-table sweep above.

GET  /api/v1/ipam/networks?provider=&q=
     -> [{ id, name, cidr, provider, region, owner_team, environment_name,
            firewall, status, subnet_count, overlap_warnings }]
     overlap_warnings is null on a plain list fetch (not computed per row
     here — expensive for a large table); it's populated by create/update
     below and by the import endpoint per row.
POST /api/v1/ipam/networks
     body: { cloud_account_id, name, cidr, provider, region?, owner_team?,
             business_unit_name?, environment_name?, vrf?, vlan?, firewall?,
             notes?, parent_network_id? }
     409 if (cloud_account_id, cidr) already exists **for that same
     account** (a hard uniqueness constraint, blocking). A CIDR that
     overlaps a *different* account/provider's network is allowed but
     flagged: the response's `overlap_warnings` lists every other network
     the new one duplicates or nests inside — informational, not blocking,
     same "alert, don't block" policy PATCH and the import endpoint use.

PATCH /api/v1/ipam/networks/{id}                                    ipam:update
     body (all optional, only supplied fields change):
       { name?, cidr?, firewall?, environment_name?, region?, owner_team?,
         business_unit_name?, vrf?, vlan?, notes?, status? }
     Editing cidr re-validates and re-checks the (cloud_account_id, cidr)
     uniqueness constraint (409 on collision — same account only),
     recomputes network_addr/broadcast_addr/prefix_len, and does not touch
     cloud_account_id, provider, or parent_network_id (those are re-create,
     not edit). Response includes `overlap_warnings` against other
     accounts/providers, same as POST. 404 if the network doesn't exist.

GET  /api/v1/ipam/networks/export?provider=&q=
     -> CSV file download (Content-Disposition: attachment), same filters
     as the list endpoint. Columns: cloud_account_id, account_identifier,
     provider, cidr, name, region, owner_team, business_unit_name,
     environment_name, vrf, vlan, firewall, status, notes — written so the
     file round-trips straight back through the import endpoint below.

POST /api/v1/ipam/networks/import                                   ipam:create
     multipart/form-data, field `file`: a CSV with the same columns
     `export` writes (only `cidr` and `name` are required; every other
     column is optional). Each row resolves its cloud account either by
     `cloud_account_id` (a UUID) or by `provider` + `account_identifier`
     (so a hand-written CSV never needs to know internal UUIDs), then
     upserts a Network by (cloud_account_id, cidr) — a CIDR already on
     that account updates the existing row instead of erroring. Each row
     runs in its own savepoint, so one bad row (invalid CIDR, unknown
     account) doesn't abort the batch — it's reported as an error for that
     row only. An overlapping CIDR is imported anyway and flagged in that
     row's `overlap_warnings`, never rejected.
     -> { created, updated, errors, rows: [{ row, status: created|updated|
          error, message?, cidr?, name?, network_id?, overlap_warnings? }] }
     400 if the file has no header row or is missing the `cidr`/`name`
     columns entirely.

GET  /api/v1/ipam/networks/{id}/subnets
GET  /api/v1/ipam/networks/{id}/free-space
     -> { network, total_addresses, total_free, free: [{range, addresses}] }

GET  /api/v1/ipam/networks/{id}/allocate/preview?hosts=N
     -> { suggested_cidr, prefix_len, usable_hosts, block_size, free }
     409 with { message, free } if no space / hosts too big for the network.

POST /api/v1/ipam/networks/{id}/allocate
     body: { hosts, name?, availability_zone?, owner_team?, application? }
     Recomputes the suggestion server-side — never trusts a client-supplied
     CIDR — then creates the Subnet. Same error shape as preview on failure.
```

## Device / interface inventory 🔒 inventory:view / inventory:create

```
GET  /api/v1/devices?site=&q=
     -> [{ id, environment_id, hostname, vendor, device_type, mgmt_ip,
            site, source, status, interface_count }]

POST /api/v1/devices
     body: { environment_id, hostname, device_type?, vendor?, mgmt_ip?,
             site?, notes? }
     Creates a "manual" (not SNMP-discovered) device.

GET  /api/v1/devices/{id}/interfaces
     -> [{ id, device_id, name, description, ip_address, mac_address,
            admin_status, oper_status, speed_mbps, vlan_id, subnet_id }]
     subnet_id is set when app/services/devices.py found an existing IPAM
     subnet containing this interface's ip_address — nullable, not enforced.
```

## Discovery 🔒 discovery:execute

```
POST /api/v1/discovery/{aws|azure|gcp|oci}?cloud_account_id=&account_identifier=
     Runs the matching mock cloud provider (see providers/mock/README.md
     for exact demo counts per cloud), upserts networks+subnets.
     account_identifier="*" matches every demo account/subscription/
     project/compartment for that provider; a specific id scopes to just
     that one. Idempotent — safe to re-run.

POST /api/v1/discovery/snmp?environment_id=&site=
     Runs MockSNMPProvider, upserts devices+interfaces (and best-effort
     cross-links each interface into an existing IPAM subnet by IP
     containment). site is optional — omit for every demo device, or scope
     to one site (e.g. "dc1"). Idempotent — safe to re-run. 404 if
     environment_id doesn't exist.

POST /api/v1/discovery/{anything else}
     404 — unknown provider name. (Every provider name the product spec
     actually names now has a mock; the old blanket 501 for azure/gcp/oci
     is gone.)
```

## Dashboard 🔒 ipam:view

```
GET /api/v1/dashboard/summary
    -> { total_networks, networks_by_provider, total_subnets,
         total_devices, devices_by_type,
         vpn_tunnels: null, bgp_sessions: null, firewalls: null,
         network_incidents: null, configuration_drift: null,
         policy_violations: null }
    The null fields are modules not built yet (Phases 4-8) — reported as
    null, not a fabricated 0, so a UI can render "N/A" honestly.
    Note: top-level "firewalls" (null) is the Phase-6 Firewall Management
    module's managed-policy count, not devices_by_type.firewall (the
    device-inventory count, real today) — the two are unrelated.
```

## Automation — POA generator 🔒 automation:view / automation:create / automation:execute / automation:export

Ported from a standalone RITM-POA tool — see `docs/ROADMAP.md`'s "Just
completed: Automation module" entry and `backend/app/poa/README.md` for
the full field/logic reference.

```
GET /api/v1/automation/poa/reference-files                🔒 automation:view
    -> [{ kind, label, uploaded, filename, size_bytes, updated_at }, ...]
    One entry per POA_REFERENCE_KINDS slot (7 total), whether or not a
    file has been uploaded for it yet.

PUT /api/v1/automation/poa/reference-files/{kind}          🔒 automation:create
    multipart: file=<csv|xlsx|xls|ods>
    Uploads/replaces the reference inventory for that kind (unique per
    kind — a new upload replaces the old one in place, no versioning).
    404 if kind isn't one of POA_REFERENCE_KINDS. 400 if empty or over 25MB.
    -> { kind, label, uploaded: true, filename, size_bytes, updated_at }

DELETE /api/v1/automation/poa/reference-files/{kind}        🔒 automation:create
    -> 204. 404 if nothing uploaded for that kind.

POST /api/v1/automation/poa/runs                            🔒 automation:execute
    multipart: input_file=<csv|xlsx|xls|ods|odt>, ritm_number=<optional>,
    metadata=<optional JSON — PoaRunCreateMetadata shape>
    Loads the RITM input, enriches every row against the currently
    uploaded reference files, generates the Excel + Word POA, and stores
    the run. RITM number precedence: the form field > parsed from the
    input filename > metadata.ritm_number > literal "RITM". 400 if the
    input file is empty, over 10MB, unreadable, or every row is missing
    both a Source IP and a usable destination.
    -> PoaRunDetail (includes every enriched row + warnings)

GET /api/v1/automation/poa/runs                             🔒 automation:view
    -> [PoaRunSummary, ...] newest first

GET /api/v1/automation/poa/runs/{run_id}                    🔒 automation:view
    -> PoaRunDetail. 404 if run_id doesn't exist.

GET /api/v1/automation/poa/runs/{run_id}/excel               🔒 automation:export
GET /api/v1/automation/poa/runs/{run_id}/docx                🔒 automation:export
    -> the stored .xlsx / .docx as a file download (Content-Disposition:
       attachment; filename=<RITM>-POA.xlsx|docx)
```

## Naming 🔒 ipam:view or inventory:view (either)

Read-only; nothing is written to the inventory. Convention and rules live in
`app/services/naming.py`.

- `GET /naming/spec` — components (id, label, scope `cloud|onprem`, pattern,
  roles), environment codes, region codes per provider, provider limits, known
  on-prem sites, and the rule list.
- `POST /naming/generate` — body `{component, provider?, env?, region?, site?,
  app?, role?, kind?, seq?}`. Returns `{name, pattern, parts, issues[], unique,
  collisions[], seq, alternatives[]}`. `name` is `null` when inputs are missing
  (all problems listed in `issues`). `seq` defaults to the next free number.
- `POST /naming/validate` — body `{name, component, provider?}`. Returns
  `{compliant, issues[], parts, pattern}`.
- `GET /naming/audit` — every named inventory object scored:
  `{total, compliant, non_compliant, sections[{component, items[{name,
  compliant, issues[], suggestion}]}]}`.

## Endpoints specified for later phases (not implemented — do not call)

Per the original product brief, these are designed but do not exist yet:
`GET /api/v1/topology`, `POST /api/v1/path/validate`, `GET
/api/v1/firewalls`, `GET /api/v1/firewall/policies`, `GET
/api/v1/security-rules`, `GET /api/v1/vpn`, `GET /api/v1/bgp`, `POST
/api/v1/change`, `POST /api/v1/approval`, `GET /api/v1/compliance`. The
firewall/change set should be satisfied by wiring in fwauto's
already-designed API surface (`firewall-policy-automation-design.md` §3.8)
rather than inventing a parallel one — see `ARCHITECTURE.md` §1. The POA
generator above is the one piece of the Automation module (Phase 7) that
is now delivered; Terraform/Ansible execution (`automation/plan`,
`automation/apply`) is still not started.
