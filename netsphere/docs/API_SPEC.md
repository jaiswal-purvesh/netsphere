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

GET  /api/v1/ipam/networks?provider=&q=
POST /api/v1/ipam/networks
     body: { cloud_account_id, name, cidr, provider, region?, owner_team?,
             business_unit_name?, environment_name?, vrf?, vlan?, notes?,
             parent_network_id? }
     409 if (cloud_account_id, cidr) already exists.

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

## Endpoints specified for later phases (not implemented — do not call)

Per the original product brief, these are designed but do not exist yet:
`GET /api/v1/topology`, `POST /api/v1/path/validate`, `GET
/api/v1/firewalls`, `GET /api/v1/firewall/policies`, `GET
/api/v1/security-rules`, `GET /api/v1/vpn`, `GET /api/v1/bgp`, `POST
/api/v1/automation/plan`, `POST /api/v1/automation/apply`, `POST
/api/v1/change`, `POST /api/v1/approval`, `GET /api/v1/compliance`. The
firewall/automation/change set should be satisfied by wiring in fwauto's
already-designed API surface (`firewall-policy-automation-design.md` §3.8)
rather than inventing a parallel one — see `ARCHITECTURE.md` §1.
