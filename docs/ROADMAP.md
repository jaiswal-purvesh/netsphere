# NetSphere — Development Roadmap

Phases as specified by the product brief. Each phase's "Delivered" column is
filled in only once code, tests, and docs for it actually exist in this repo
— an empty column is not a promise, it's an honest "not started."

| Phase | Scope | Delivered in this repo? |
|---|---|---|
| **1. Foundation** | Repo, backend, frontend, Postgres, auth, RBAC, Docker, CI, logging | ✅ Yes — this delivery |
| **2. Network source of truth** | Networks, subnets, IPAM, devices, interfaces, inventory | ✅ Yes — IPAM (networks/subnets/IP addresses, search, allocate) + device/interface inventory (SNMP mock, Network Inventory page) + routing inventory (route tables per cloud network, on-prem device static routes, `/routing` page) + cloud network interfaces/peerings (`/cloud-networks` page), including best-effort cross-links from an interface's IP into an existing IPAM subnet and a subnet into its route table |
| **3. Cloud discovery** | AWS/Azure/GCP/OCI adapters | ✅ Interface + mocks for all four clouds, now including per-network ENI/NIC/VNIC interfaces and VPC/VNet/VCN peering connections (`/cloud-networks`). ⏳ Real SDK adapters (all four currently `NotImplementedError` by design) |
| **4. Topology** | Network graph, relationships | ✅ Yes — `GET /topology` (org hierarchy → cloud account → network → subnet, plus device/interface and `Network.firewall` relationships, read live off Phase 1-2 data rather than a separate store) + `/topology` page (searchable tree, per-node detail, per-network SVG diagram) |
| **5. Path Analyzer** | Route lookup, firewall/security validation, end-to-end path | 🟡 Partial — the read-only "would this be allowed today?" check is delivered (`POST /path/simulate`, `GET /path/runs`, `/path-analyzer` page): resolves source/destination to a known network, finds any firewall recorded against each, and checks a real live rulebase via the same `fw_panorama_adapter`/`fw_redundancy` primitives Policy Optimizer uses. Route-table-aware multi-hop path computation (this phase's own follow-up, roadmap item 4 below) is not built — today a path is at most the two enforcement points `Network.firewall` names |
| **6. Security** | Firewall/NSG/SG normalization, compliance | 🟡 Partial — normalized cloud NSG/SG/SL objects (`security_groups`/`security_rules`) are delivered, deployed to via the same intent → plan → guardrails → PoA → approval → execute → verify pipeline Phase 3's Panorama automation already built (`FwIntent.target_kind`), plus a RITM/connectivity-request sheet intake that creates those intents automatically with a real CIDR-containment resolver (`/security-policies` page). Compliance policy engine (Module 12) still not started |
| **7. Automation** | Terraform, Ansible, approval workflow, change management | 🟡 Partial — the Plan of Action (POA) generator is delivered (`/automation` page's "POA generator" tab, `POST /automation/poa/runs`), and fwauto is now wired in as the module's shared UI/RBAC/audit layer per ARCHITECTURE §1: a unified "All changes" tab (`GET /automation/changes`, `/changes/summary`) merges POA runs and fwauto firewall/cloud-policy intents into one feed with real counts, gated by a new any-of-two-permissions RBAC check, plus the first-ever reader of the `audit_logs` table (`GET /automation/audit`) scoped to both change kinds. Terraform/Ansible execution (a second runner, deliberately not built — fwauto remains the one execution engine) and the approval workflow's extension to POA runs are still not started |
| **8. Monitoring** | VPN, BGP, connectivity, alerts | 🟡 Partial — connectivity monitoring is delivered: `circuits`/`bgp_sessions`/`connectivity_links`/`vpn_connections` (dedicated interconnects — Direct Connect/ExpressRoute/Interconnect/FastConnect — plus on-prem MPLS/VRF handoffs and IPsec VPN backups), discovery-sourced for all four clouds plus SNMP, `/connectivity` page. Alerts/incidents (Module 8's other half) still not started |
| **9. AI** | Network assistant, root-cause analysis, NL search, Terraform generation | ⏳ Not started |
| **10. Enterprise** | HA, Kubernetes, multi-tenancy, advanced RBAC, SSO/OIDC, audit hardening, reporting | ⏳ Not started |

## Immediate next session's likely candidates (not yet started, in priority order)

1. Resource-scoped RBAC (Phase 10 item, but cheap to add early if the team
   starts onboarding more than one business unit before Phase 10 proper).
2. Real cloud SDK adapters (`providers/aws.py`/`azure.py`/`gcp.py`/`oci.py`),
   once there's an actual credential/secrets-manager story to hang them off
   of — currently all four correctly raise `NotImplementedError`.
3. Wire the new `routes`/`route_tables` inventory (below) into Path
   Analyzer's `_check_hop` sequence for real multi-hop, route-aware path
   computation — the data now exists; Path Analyzer still only reasons
   about `Network.firewall`, not the routing graph.
4. Alerts/incidents (Module 8's other half — connectivity monitoring
   itself is now delivered, see below) — a `Circuit`/`BgpSession` going
   `down`/`idle` has nowhere to raise a notification yet, it just shows
   red on the `/connectivity` page.
5. FortiGate/FortiManager deploy adapter (Phase 3 only covers Panorama);
   a one-time backfill of `cloud_network_interfaces.security_groups`'
   existing free-text names into real `SecurityGroup` rows, so Phase 6's
   redundancy analysis sees rules that predate this pipeline too, not only
   ones it created itself.
6. Terraform/Ansible execution for the SOP doc's cloud-network-deployment
   workflow — Phase 7's other still-unbuilt half (the firewall/cloud-policy
   half is now covered by fwauto, wired in below); a Terraform-apply state
   machine is a materially different problem (plan files, apply idempotency,
   state locking) from fwauto's rule-diffing pipeline, not a copy of it.
7. Extend an approval gate onto `PoaRun` generation, reusing fwauto's exact
   separation-of-duties convention (requester != approver) rather than a
   second one, if the team decides POA documents should require in-app
   sign-off before being handed to ServiceNow — deliberately not done yet
   this phase since the standalone tool's original design treats the POA as
   a document for manual approval outside the system (see "Automation
   module: Plan of Action (POA) generator" below).

## Just completed: RHEL production deployment kit

`docker-compose.prod.yml` (only nginx publishes ports, fully-qualified images,
`:Z` labels, compose-level healthchecks, restart policies), non-root
Dockerfiles, `deploy/install-rhel.sh` (preflight, Podman/Docker + compose
detection, random secrets into `deploy/.env.prod`, firewalld, systemd units,
smoke test), `deploy/netsphere` ops CLI (up/down/status/logs/backup/restore/
update/smoke/demo/bundle/load), offline amd64 image bundle, nginx HTTP/HTTPS
configs, and `docs/DEPLOYMENT_RHEL.md`. Backend now refuses to start in
`ENVIRONMENT=production` with default/short secrets or DEBUG on, supports
`SEED_DEMO_DATA=false`, and never logs the seeded admin password in
production. Verified here: compose config renders, scripts pass `bash -n`,
production-mode backend boots/migrates/seeds/logs in, 94 tests pass.
NOT verified here (no container daemon in the sandbox): actual image builds
and the full installer run on RHEL - first real run on the VM is the test.

## Just completed: Naming — one standard for every network component (cross-cutting)

Asked to "add a feature (tab) that helps the team build a name for each network
component, for all cloud and on-prem". New `/naming` page (nav: Network → Naming)
with three tabs: **Name builder**, **Check a name**, **Inventory audit**.

- **Convention (proposed default — BFL's real standard was not available, so
  this is a starting point to be replaced/adjusted, not a claim about current
  practice)**: lower-case, hyphen-separated, fixed segment order.
  Cloud: `{org}-{env}-{region}-{type}-{app}-{seq}` e.g. `bfl-prd-use1-vpc-payments-01`.
  On-prem device: `{site}-{role}-{type}-{seq}` e.g. `dc1-core-rtr-01`. VRF:
  `{site}-vrf-{app}`. `{type}` follows each cloud's own word (vpc/vnet/vcn,
  sg/nsg/fw/sl, dx/er/ic/fc, eni/nic/vnic). Eleven component types: network,
  subnet, route table, security group, peering, circuit, VPN, interface, device,
  VRF, MPLS circuit.
- **Where it lives**: `app/services/naming.py` is the single source of truth
  (pattern, env codes, region→short-code tables, provider limits). The frontend
  only collects choices and displays what the API returns, so the rule is never
  duplicated client-side. Changing the standard means editing the constants in
  that file.
- **API** (`/api/v1/naming/...`): `GET spec`, `POST generate`, `POST validate`,
  `GET audit`. Gated on `ipam:view` **or** `inventory:view` (the existing
  `require_any_permission` union) — deliberately **no new permission and no
  migration**, so an existing database/volume needs nothing applied for this to
  work (the lesson from the stale-volume problem on the Mac).
- **Builder**: picks the next free sequence number against the live inventory
  (networks, subnets, route tables, security groups, circuits, interfaces,
  devices), shows the name segment-by-segment, offers the next three alternatives,
  and reports every missing input at once instead of one at a time.
- **Provider hard limits apply on top of the convention** (GCP must start with a
  letter and be ≤63; Azure ≤64; etc.).
- **Validator**: says *which* segment is wrong ("type should be 'vnet' for
  Azure, found 'vpc'"), not just "doesn't match".
- **Audit**: scores every named object against the standard and proposes a
  replacement for non-compliant ones (environment/region/type inferred from the
  old name). Against the demo inventory, 52 of 53 names are non-compliant — the
  demo data predates the standard, which is exactly what the audit is for.
  Suggestions are a starting point: the `{app}` segment is a guess and renaming a
  live cloud object usually means recreating it.
- **Deliberately not done**: reserving a name (two engineers can still pick the
  same free name before either deploys it — the "builder + reserve" option was
  offered and not chosen); a UI to edit the convention (it is code-defined);
  subnet and interface-per-host auditing (names are often absent); writing
  names back to cloud resources or the inventory (read-only by design).
- **Verified**: 25 new backend tests (94 total, all passing — generator per
  provider, region resolution, tiers, next-free sequence and collision against
  discovered devices, 10-case validator table, provider limits, audit, RBAC
  200/403/401); `tsc` and `next build` clean; Playwright pass over all three
  tabs with zero console errors.

## Just completed: fwauto wired into the Automation module — unified change hub (Phase 7, partial)

Asked to "build Phase 7" — `docs/ROADMAP.md`'s own top "immediate next
session" priority at the time: "wire fwauto in as the Automation module's
execution engine... rather than writing a second Terraform/Ansible runner."
`ARCHITECTURE.md §1` frames this precisely as giving fwauto's existing
intent → plan → guardrails → PoA → approval → execute → verify → rollback
pipeline "a shared UI/RBAC/audit layer," not rebuilding it — so this is a
convergence delivery, not a new pipeline.

- **Read-only normalization, not a merged data model**: `app/services/
  automation_hub.py` reads the two pre-existing change-producing tables —
  `PoaRun` (the Automation module's own POA document generator) and
  `FwIntent` (fwauto's pipeline, generalized in Phase 6 to also cover cloud
  NSG/SG/SL targets) — and normalizes them into one feed, one set of
  summary counts, and one audit-trail view, without touching either
  table's own schema or lifecycle logic. A `PoaRun` and an `FwIntent` are
  deliberately not merged into a shared table: one is a finished document
  the moment it's generated, the other moves through a multi-stage
  lifecycle with separation-of-duties approval in between — collapsing
  them would blur that real difference, so a normalized read view earns
  its keep here instead (no migration needed this phase at all).
- **API** (`/api/v1/automation/...`, alongside the existing `poa.py`
  router's `/automation/poa/...` prefix): `GET changes` (merged,
  most-recent-first feed with a five-value shared status vocabulary —
  `in_progress`/`completed`/`rejected`/`rolled_back` — mapped from
  `FwIntent.status`'s own richer set), `GET changes/summary` (real counts:
  POA run total, fwauto intent total, in-progress/completed/rejected/
  rolled-back breakdown, firewall-vs-cloud target split), and `GET audit`
  — the first-ever reader of the `audit_logs` table (write-only since
  Phase 1), filtered to `fw_intent`/`poa_run` resource types.
- **RBAC convergence, done as a real union check, not a bypass**:
  `app/deps.py` gained `require_any_permission(*codes)` — passes if the
  user holds *any* of the listed permissions, unlike `require_permission`'s
  single-code AND check. The three new endpoints use
  `require_any_permission("automation:view", "firewall:view")` so a user
  who only holds one of the two resource areas still sees their slice of
  the combined hub, matching the "shared UI" framing, without touching
  either resource area's own existing endpoints. Verified live: the
  `approver@netsphere.local` test user (SECURITY_ENGINEER role — holds
  `firewall:view` but not `automation:view`) got `200` from all three hub
  endpoints but still correctly got `403` from the POA-only
  `/automation/poa/reference-files` endpoint — the union check adds
  access to the hub specifically, not a blanket permission merge.
- **UI**: the existing `/automation` page gained a two-tab layout — "All
  changes" (new default) and "POA generator" (the pre-existing reference-
  file/run-history UI, unchanged). The new tab shows real stat cards (POA
  document count, fwauto policy-change count, in-progress count,
  rejected+rolled-back count, firewall-vs-cloud-target split), a
  kind/status-badged, filterable (all/policy-changes/POA-documents) feed,
  and an on-demand audit-trail table.
- **Verified live** against this delivery's real accumulated data (not
  synthetic fixtures): `GET /automation/changes/summary` returned 1 POA
  run and 123 fwauto intents (114 in progress, 7 completed, 2 rejected)
  from every prior phase's live-verification testing; the RBAC union check
  was tested both ways as described above; `npm run build` and `tsc
  --noEmit` both pass clean; a Playwright pass (login → All-changes tab
  with real stat cards and feed rows → Policy-changes filter → audit
  trail opened showing real `audit_logs` rows → POA-generator tab still
  intact) found zero console/page errors. The full backend test suite (69
  tests) still passes with zero regressions — this phase added no
  migration and touched no existing endpoint's behavior.
- **Deliberately not done**: Terraform/Ansible execution for the SOP
  doc's cloud-network-deployment workflow (Phase 7's other half — a
  materially different problem from fwauto's rule-diffing pipeline, not
  attempted as a "second runner" here or elsewhere); an approval gate on
  `PoaRun` generation (the standalone tool's original design treats a POA
  as a document for manual approval outside the system — adding an
  in-app approval step would contradict that documented design choice,
  not just extend it, so it's left as an explicit future decision rather
  than assumed); a combined creation form (the hub is a unified *view*;
  creating a new fwauto intent still goes through `/fw-automation` or
  `/security-policies`' intake, and a new POA run through the generator
  tab — both already have complete, tested creation flows this phase
  didn't need to duplicate).
- **Pushed** to both `~/Projects/netsphere` and `~/Downloads/netsphere_2`
  via the established tar/device-bridge-commit/extract workflow;
  `ast.parse` confirmed clean on all new/changed backend files in the
  `netsphere_2` copy.

## Just completed: Security Policies — normalized cloud NSG/SG/SL + RITM sheet intake (Phase 6, partial)

Asked directly by the user, with a real ServiceNow RITM export
(`RITM1151021.ods`) supplied as the input format: turn the connectivity-
request spreadsheet the network team actually receives into firewall and
cloud NSG/SG/SL change requests automatically, deployed through the same
safety pipeline Phase 3's Panorama automation already built. This fills
`docs/ERD.md`'s long-reserved `security_groups`/`security_rules`
normalization (the free-text list `cloud_network_interfaces.security_groups`
carried since Phase 3) and the design doc's Appendix A "PHASE 0 — INTAKE"
CSV batch flow, generalized beyond Panorama-only.

- **Model**: `SecurityGroup` (one per network+provider — Azure NSG/AWS SG/
  GCP firewall/OCI Security List) and `SecurityRule` (a normalized 5-tuple:
  direction, priority, action, protocol, port range, single CIDR — one row
  per CIDR rather than modeling each vendor's list-valued native rule
  shape, the same "deliberately not a perfect universal abstraction" bet
  the firewall side already makes), plus `SecurityPolicyBatch` (one row per
  RITM sheet upload, carrying every unresolved row's reason so intake is
  never silently lossy). `FwIntent` (Phase 3's Panorama-only automation
  table) gained a `target_kind` discriminator and a `security_group_id`
  column alongside its original `integration_id`, with a real
  `CheckConstraint` (`ck_fw_intents_exactly_one_target`) requiring exactly
  one — migration `c4f8b2e6d915`.
- **Intake parser**: `app/services/security_policy_intake.py` reads
  `.xlsx`/`.csv`/`.ods` (the real RITM export's column set: Source IP,
  Destination IP, Destination FQDN, Destination Port, Technical
  Justification, ...), tolerant of header drift the same way
  `poa_firewall_parser.py` is, but deliberately a separate parser — this
  reads the raw pre-PoA connectivity *request*, not an already-authored
  Plan of Action, and the two column vocabularies don't overlap enough to
  share one synonym table. Verified against the actual uploaded file: 33
  rows → 55 created intents (multi-port rows expand to one intent per
  port) + 4 correctly flagged unresolved (three AD-identifier sources like
  `bfl\it_pennant_bfl` that aren't a CIDR, one FQDN destination) — nothing
  guessed, nothing silently dropped.
- **Resolution**: `app/services/security_policy_resolve.py` does a real
  CIDR-containment lookup against `networks.network_addr`/`broadcast_addr`
  to decide whether a destination lives in a known cloud network (→ that
  network's `SecurityGroup`, auto-created on first match, narrowest-match
  wins when networks overlap) or on-prem (→ the single active
  `FirewallIntegration`, left unresolved rather than guessed if there are
  zero or more than one).
- **Pipeline**: `app/services/security_policy_adapter.py` implements the
  same render/apply/verify shape as `fw_panorama_adapter.py`, so
  `fw_plan.py`/`fw_executor.py` branch on `target_kind` rather than forking
  into a second pipeline — guardrails, redundancy/shadow analysis, PoA
  generation, approval-binds-plan_hash, and the asymmetric allow/deny
  rollback policy all run unmodified for a cloud target. "Deploying" a
  cloud rule means writing the `SecurityRule` row that represents it — there
  is no live NSG/SG/SL API in this delivery (every cloud account is
  mock-discovered), matching how the rest of this platform treats cloud
  state. One real vendor constraint is enforced as a guardrail *and* an
  adapter-level hard stop (defence in depth): AWS Security Groups have no
  explicit deny, so `target_kind="aws_sg"` rejects a `deny` intent at plan
  time.
- **Live-verified end to end**, not just unit-tested: uploaded the real
  RITM file through `POST /security-policy/intake`; planned, generated a
  PoA, approved (separation-of-duties enforced — rejected the requester's
  own approval, succeeded from a second account), and executed a
  synthetic cloud-target row against a real AWS VPC CIDR already in
  inventory — the rule landed in `security_rules`, read back correctly,
  and a second identical submission correctly returned
  `no_change_required` via the existing redundancy analyzer.
- **Frontend**: `/security-policies` page (RITM upload + per-row
  resolution results + previous-upload history; a Security Groups browser
  with expandable per-group rule tables); `Firewall Automation` page's
  intent list gained a Target column so cloud and on-prem requests appear
  side by side in the same lifecycle view.
- **Deliberately not done**: FortiGate/FortiManager deploy (Phase 3 only
  wired Panorama; the design doc's own Phase 4), a backfill of existing
  `cloud_network_interfaces.security_groups` free-text names into real
  `SecurityGroup` rows (so today's redundancy analysis only sees rules
  this pipeline itself created), and DNS resolution for an FQDN
  destination (carried through as an unresolved row instead).

## Just completed: Connectivity — dedicated interconnects + on-prem MPLS/VRF + IPsec VPN backups (Phase 8, partial)

Asked directly by the user to model their real hybrid network: each cloud
reaches on-prem over its own dedicated interconnect — AWS Direct Connect,
Azure ExpressRoute, GCP Cloud Interconnect, OCI FastConnect — riding an
MPLS backbone with VRF-based segmentation, not a flat shared network. This
fills `docs/ERD.md`'s "designed, not yet migrated" `circuits`/
`bgp_sessions`/`connectivity_links`/`vpn_connections` quartet ("VPN/DX/ER/
Interconnect/FastConnect monitoring").

- **Model**: `Circuit` (owned by exactly one of a `CloudAccount` — the
  cloud side — or a `Device` — the on-prem side — a real `CheckConstraint`,
  `ck_circuits_exactly_one_owner`, same convention as `Route`'s own
  exactly-one-owner rule), `BgpSession` (circuit-scoped — the control
  plane actually carrying routes across a circuit), `ConnectivityLink`
  (which `Network` a cloud-side circuit attaches to), and `VpnConnection`
  (IPsec backup path, `Network`/`Device` exactly-one-owner, its own
  `CheckConstraint`) — migration `8a1d4e7f2b96`. **Deliberate design
  choice**: a real interconnect's two ends are two independently-
  discovered `Circuit` rows, not one shared row — each side is typically
  monitored by a different team anyway (the cloud account owner vs. the
  network team), and inventing a cross-provider matching step wasn't
  needed to get real value out of this phase. The mock data still makes
  the relationship visible: the on-prem MPLS circuit's BGP peer IP/ASN are
  deliberately mirrored from the matching cloud-side circuit's own values
  (local here = peer there), so a human reading both rows can see they
  describe the same physical link.
- **Discovery**: `app/providers/base.py` gained `DiscoveredCircuit`/
  `DiscoveredBgpSession`/`DiscoveredVpnConnection` dataclasses, plus
  non-abstract `discover_circuits()`/`discover_vpn_connections()` on
  `CloudProvider` (default `[]`, same rationale as `discover_peerings()`)
  and a non-abstract whole-run `discover_circuits()` on
  `NetworkDeviceProvider`. All four cloud mocks now return one dedicated
  interconnect per account (AWS: Direct Connect; Azure: ExpressRoute;
  GCP: Cloud Interconnect; OCI: FastConnect), each with a BGP session and
  attached to that account's own "prod" network; the AWS mock also
  returns one VPN backup for `vpc-shared-services`. The SNMP mock returns
  the on-prem side: two MPLS circuits (dc1's `core-rtr-01` toward AWS
  us-east-1, dc2's `dc2-edge-rtr-01` toward Azure westeurope), matching
  the cloud-side circuits' BGP values as described above.
- **Ingestion** (`app/services/connectivity.py`, new): circuits upsert by
  `external_id` scoped to their owner; BGP sessions upsert by
  `(circuit_id, peer_ip)`; a circuit's `attached_network_name` resolves a
  `ConnectivityLink` by `Network.name`, and `VpnConnection.network_name`
  resolves the same way — both skip-and-retry-idempotently when
  unresolved, the same contract `app/services/cloud_networks.py`'s
  peerings already established, not a fourth invented pattern. Wired into
  `app/services/discovery.py` (cloud circuits + VPNs, once per account,
  right after peerings) and `app/services/devices.py` (on-prem circuits,
  once per discovery run, using the hostname→device-id map that loop
  already builds).
- **API** (`/api/v1/connectivity/...`): `GET/POST circuits` (nested BGP
  sessions + connectivity links), `GET circuits/{id}`, `DELETE
  circuits/{id}`, `GET/POST vpn-connections`, `DELETE
  vpn-connections/{id}`. New `connectivity` RBAC resource area
  (`NETWORK_ENGINEER` view/create/update, `CLOUD_NETWORK_ENGINEER` also
  execute); every role with blanket `:view` picked it up automatically via
  the existing idempotent `app.seed`.
- **UI**: new `/connectivity` page — stat cards (circuit count, total
  bandwidth, down/decommissioned count, VPN connection count), an
  expandable cloud-side circuit list (provider-specific type badge,
  owner/VRF/bandwidth/location/attached-network detail line, per-circuit
  BGP session table), the same for on-prem MPLS handoffs, and a VPN
  connections table.
- **Verified live**: both exactly-one-owner `CheckConstraint`s were tested
  directly (a circuit with no owner, a circuit with both owners, and a VPN
  connection with no owner each raise `IntegrityError`, confirmed by
  constructing them and trying to commit); re-running discovery for all 11
  cloud accounts plus the SNMP device sweep twice confirmed full
  idempotency (13 circuits — 3 Direct Connect + 3 ExpressRoute + 3
  Interconnect + 2 FastConnect + 2 MPLS — 13 BGP sessions, 11 connectivity
  links, 1 VPN connection after the first pass; zero new rows on the
  second); manual circuit/VPN create and delete, plus the 422
  both-owners-or-neither error path, were exercised via `curl`; the full
  backend test suite (69 tests) still passes with zero regressions.
  Frontend verified with `tsc --noEmit`, a clean `next build`, and a
  Playwright pass (login → 13 expandable circuit sections found and
  toggled open → BGP session tables rendered with matching peer ASN/IP
  pairs → VPN table rendered → zero console/page errors).
- **Deliberately not done**: alerts/incidents when a circuit or BGP
  session goes down (Module 8's other half, still `⏳ Not started`); a
  formal cross-provider match between a cloud-side circuit and its
  on-prem-side counterpart (kept as two independently-discovered rows, per
  the design choice above); real interconnect discovery (all four cloud
  adapters' `discover_circuits()` still correctly raise
  `NotImplementedError` via the base real-provider classes, same as every
  other real adapter in this delivery).

## Just completed: Cloud Networks — ENIs/NICs/VNICs + VPC/VNet/VCN peering (Phase 3 close-out)

The `network_interfaces` table `docs/ERD.md`'s "designed, not yet migrated"
section reserved for this phase, plus a deliberate extension: peering
connections as first-class objects rather than only ever being implied by
a route's `vpc_peering` target (see Routing, just below).

- **Model**: `cloud_network_interfaces` (subnet-scoped ENI/NIC/VNIC — name,
  private/public IP, attached-to compute resource, status, `security_groups`
  as a free-text JSONB list — a deliberate simplification matching
  `Network.firewall`'s own free-text convention, normalized security-group
  modeling is Phase 6's job per the ERD reservation) and `network_peerings`
  (`network_a_id`/`network_b_id` FK `networks.id`, both CASCADE, a real
  `CheckConstraint` rejecting self-peering, and a unique `(network_a_id,
  network_b_id)` pair stored in canonical lower-id-first order so the same
  real-world connection discoverable from either side's account upserts to
  one row) — migration `5f8b2e6c1a04`.
- **Discovery**: all four mock cloud providers now return a
  `DiscoveredCloudInterface` per network (one representative ENI/NIC/VNIC in
  the network's first subnet, provider-appropriate naming — AWS's ENI,
  Azure's NIC, GCP's vNIC/firewall-tag terminology, OCI's VNIC/NSG); the AWS
  mock also returns `DiscoveredPeering` entries matching the `vpc_peering`
  routes Routing already creates toward `vpc-shared-services` (deliberately
  AWS-only in this delivery — GCP's routes-based model has no first-class
  peering object at all, so `CloudProvider.discover_peerings()` defaults to
  `[]` rather than forcing every provider to invent one).
  `app/services/cloud_networks.py` upserts interfaces by (subnet_id,
  external_id) and peerings by resolving both sides' `Network.name` (no
  queryable external_id column exists on `Network` today) — an unresolvable
  peering (the far side not discovered yet, since `discover_peerings()`
  isn't scoped to one account) is skipped and retried idempotently on the
  next discovery pass rather than erroring the whole run.
- **API** (`/api/v1/cloud-networks/...`): `GET/POST interfaces`, `DELETE
  interfaces/{id}`, `GET/POST peerings`, `DELETE peerings/{id}`. New
  `cloud_networks` RBAC resource area (`NETWORK_ENGINEER` gets view/create/
  update, `CLOUD_NETWORK_ENGINEER` also gets execute; every role with
  blanket `:view` picks it up automatically, reseeded via the existing
  idempotent `app.seed`).
- **UI**: new `/cloud-networks` page — stat cards (interface count,
  networks with interfaces, interfaces with a public IP, active peerings),
  an expandable per-network interface table (name, subnet, private/public
  IP, attached-to, security groups, status/source badges), and a peering
  connections table (both networks, status, source, external ID).
- **Verified live**: the DB-level `CheckConstraint` was tested directly (a
  self-peering row is rejected, confirmed via `IntegrityError`), re-running
  discovery for all 11 cloud accounts twice confirmed full idempotency
  (zero new rows on the second pass; 16 interfaces / 1 peering total,
  matching the AWS mock's one deliberately-non-prod/non-shared VPC), manual
  interface create/delete and peering create/delete (plus the 409 duplicate-
  pair and 422 self-peering error paths) were exercised via `curl`, and the
  full backend test suite (69 tests) still passes with zero regressions.
  Frontend verified with `tsc --noEmit`, `next build`, and a Playwright pass
  (login → 16 expandable network groups found and toggled → peering table
  rendered → zero console/page errors).
- **Deliberately not done**: Azure/GCP/OCI peering demo data (kept AWS-only,
  matching Routing's existing `vpc_peering` route data); normalized
  security-group/rule objects (Phase 6, per the ERD reservation already
  noted above).

## Just completed: Routing inventory — route tables + on-prem static routes (Phase 2/3 close-out)

The other half of "network source of truth" the original spec called for,
alongside IPAM and device/interface inventory — `docs/ERD.md`'s
"designed, not yet migrated" `route_tables`/`routes` pair, and the item
this roadmap's own priority list carried for a session.

- **Model**: `route_tables` (one per network — see the deliberate
  one-table-per-network simplification in `app/services/routing.py`'s
  docstring, the same kind of honest trade-off Path Analyzer's
  `Network.firewall` model already makes) and `routes` (owned by exactly
  one of a route table *or* a device — enforced with a real
  `CheckConstraint`, not just convention) — migration `781cba56ba2f`.
  `subnets` also gained a nullable `route_table_id` cross-link, same
  not-enforced-but-set-when-known convention as `interfaces.subnet_id`.
- **Discovery**: every mock cloud provider (AWS/Azure/GCP/OCI) now returns
  a `DiscoveredRouteTable` alongside each `DiscoveredNetwork` — a local/
  in-VPC route plus a provider-appropriate egress route (internet gateway,
  VPN gateway, or VPC peering, matched to what each cloud actually calls
  its default-route target). The SNMP mock's routers and firewall now
  return their own static routes too (`DiscoveredDevice.routes`).
  `app/services/routing.py` upserts both by natural key
  (destination_cidr, target_type) so re-running discovery updates in place
  rather than duplicating — verified live: a first pass created 16 route
  tables / 34 routes across all four clouds plus SNMP, a second pass
  against the same data updated all of them with zero new rows.
- **API** (`/api/v1/routing/...`): `GET/POST route-tables`,
  `GET route-tables/{id}`, `POST route-tables/{id}/routes`,
  `DELETE routes/{id}`, `GET device-routes` (on-prem, grouped by device).
  New `routing` RBAC resource area (`NETWORK_ENGINEER`/
  `CLOUD_NETWORK_ENGINEER` get view/create/update; every role that gets
  blanket `:view` picks it up automatically since it's just another entry
  in `RESOURCE_AREAS` — reseeded via the existing idempotent `app.seed`,
  no migration needed for that part).
- **UI**: new `/routing` page — stat cards (route table count, devices
  with static routes, total routes, internet/NAT egress route count), an
  expandable list of cloud route tables (network name/CIDR, main/
  discovered badges, per-route destination/target/state), and the same
  for on-prem device static routes.
- **Verified live**: the DB-level `CheckConstraint` was tested directly
  (a route with neither `route_table_id` nor `device_id` set is rejected,
  confirmed via `IntegrityError`), the manual create → add-route → detail
  flow was exercised end-to-end via `curl`, and the full backend test
  suite (69 tests) still passes with zero regressions. Frontend verified
  with `tsc --noEmit`, `next build`, and a Playwright pass (login → 19
  expandable sections found and toggled → zero console/page errors).
- **Deliberately not done**: Path Analyzer does not yet consume this data
  (still reasons only about `Network.firewall`, per its own documented
  follow-up) — wiring the two together for real multi-hop path
  computation is next on this list, above.

## Just completed: Path Analyzer — read-only path/reachability check (Phase 5, partial)

Delivers the single highest-value, lowest-risk item both this roadmap and
`firewall-policy-automation-design.md` §3.8 called out as "ship it first":
a read-only "would this traffic be allowed today?" check that needs no
write access to any firewall.

- **Model**: `path_simulation_runs` (migration `b91e4d7a3c58`) — one row
  per check, storing the resolved source/destination networks, the
  per-hop verdicts as JSONB, the overall verdict, and who ran it.
- **Service** (`app/services/path_analyzer.py`): resolves source/
  destination addresses to known `Network` rows by CIDR containment
  (longest-prefix-match, same pattern as `ipam.search_ip`), collects the
  distinct firewall names recorded against each side (`Network.firewall`
  is free text, so a path crosses at most two enforcement points today —
  a real, documented simplification, not a gap papered over), and for each
  one either matches a credentialed, active `FirewallIntegration` by name
  and checks the live rulebase (reusing `fw_panorama_adapter.fetch_rulebase`
  + `fw_redundancy.analyze`, the exact primitives Policy Optimizer already
  uses) or reports `unknown` with a real reason. Nothing is guessed: an
  unmatched integration, a missing credential, or an unreachable device
  each surface as `unknown` with an explicit message, never a fabricated
  allow/block.
- **API**: `POST /api/v1/path/simulate` (`path:create`) runs a check and
  persists it; `GET /api/v1/path/runs` (`path:view`) lists the last 100
  with resolved network references, batch-fetched to avoid N+1 queries.
  Reuses the pre-existing `path` RBAC resource area (already granted to
  `NETWORK_ENGINEER`/`SECURITY_ENGINEER`, previously unwired).
- **UI**: new `/path-analyzer` page (nav flipped from "not implemented" to
  live) — a source/destination/protocol/port form, a result panel with an
  overall verdict badge and a per-hop breakdown (firewall, verdict,
  covering/blocking rule, notes/errors), and a recent-checks history table.
- **Verified live** against the seeded demo data: a zero-hop case (no
  firewall recorded on either side → `allowed`, empty hop list), an
  unmatched-integration case (`Network.firewall` name with no matching
  credentialed integration → `unknown`), and a matched-integration case
  where the live Panorama call itself fails (`unknown` with the real
  connection error surfaced, not swallowed).
- **Deliberately not done**: multi-hop route-aware path computation
  (still a static two-hop-max model per `Network.firewall`); no frontend
  test suite added this session (verified via `tsc --noEmit`, `next build`,
  and a Playwright pass with zero console/page errors instead).

## Just completed: Automation module — Plan of Action (POA) generator

Ported a standalone Python tool ("RITM-POA Automation," built independently
for generating the Plan of Action document an engineer writes by hand for
each firewall/NSG/security-list change request) into NetSphere as the
Automation module — filling the `automation` RBAC resource area and the
`/automation` nav slot the platform already reserved for it, and giving
`firewall-policy-automation-design.md`'s "the system should generate a PoA,
not bypass it" recommendation a real implementation for the OCI/BFL
environment (Word + Excel output, rather than fwauto's API-driven
ServiceNow-attachment flow — the two approaches converge under one
Automation module now that both exist; see ARCHITECTURE §1).

- **`backend/app/poa/`**: a faithful, logic-preserving port of the
  standalone tool's five modules — `lookup.py` (CIDR/IP matching against
  OCI subnet inventory, merged CIDR->Firewall map, on-prem Network IPAM,
  NSG/Security-List host reports, and a security-list rule-count audit;
  most-specific-network-wins matching), `enrich.py` (per-row enrichment:
  location, firewall whitelisting, security-list/NSG resolution, routing
  classification), `excel_writer.py` and `word_writer.py` (the generated
  `.xlsx`/10-section branded `.docx`), `loader.py` (RITM input parsing:
  CSV/XLSX/XLS/ODS/ODT, with header-row auto-detection), and
  `generator.py` (the orchestrating `generate_poa()` call). Only the I/O
  layer changed from the original — filesystem paths became in-memory
  bytes (`ReferenceFile`, `BytesIO`) so the module stays a stateless
  service per ARCHITECTURE.md, and `print()` diagnostics became a
  `warnings` list returned to the caller instead of going to stdout.
- **Model**: `poa_reference_files` (one row per reference-inventory kind,
  replaced in place on re-upload) and `poa_runs` (one row per generation:
  the enriched rows as JSONB, plus the generated `.xlsx`/`.docx` as
  `LargeBinary`) — migration `a1b2c3d4e5f6`. Both stored in Postgres, not
  a mounted volume, matching the existing stateless-service principle.
- **API** (`/api/v1/automation/poa/...`): `GET/PUT/DELETE
  reference-files/{kind}` for the 7 reference inventories, `POST runs`
  (multipart: a RITM input file + JSON run metadata) to generate a POA,
  `GET runs` / `GET runs/{id}` for history/detail, `GET
  runs/{id}/excel|docx` to download. Gated on the pre-existing `automation`
  RBAC area (`view`/`create`/`execute`/`export`) — granted to
  `NETWORK_ENGINEER` and `CLOUD_NETWORK_ENGINEER` in `rbac_seed.py`.
- **UI**: new `/automation` page (nav flipped from "not implemented" to
  live) — a reference-inventory upload/replace/remove checklist, a "new
  POA run" form (input file + RITM number + description/change-owner),
  run history with Excel/Word download buttons, and an enriched-rows
  table for the selected run with invalid rows highlighted.
- **Tests**: 7 new tests using small synthetic reference/input data
  constructed in-test (not the uploaded tool's real BFL/Bajaj production
  inventories, so no customer data ended up in the repo) — reference-file
  upload/replace/delete, unknown-kind 404, a full run with no reference
  files uploaded (on-prem fallback path), a full run with an uploaded OCI
  inventory (subnet match path), RBAC gating (403 on `automation:execute`
  without it), and empty-file rejection — 69 total, all passing against a
  real Postgres. Also verified live via `curl` against a running server:
  reference-file upload, a full run against the seeded admin, and
  downloading both the generated `.xlsx` (opens in openpyxl, 19 columns)
  and `.docx` (opens in python-docx, 10 tables matching the 10 sections).
- **Deliberately not done**: the uploaded tool's real reference inventories
  (OCI subnet exports, CIDR/firewall map, on-prem IPAM, NSG/SL host
  reports, security-list audit — all real BFL/Bajaj production data) were
  not seeded into the new tables. They stay local to the user's own
  upload via the new UI rather than being baked into the repo or test
  fixtures.

## Just completed: IPAM CSV import/export + duplicate/overlap alerts on create, update, and import

- **Overlap probe service**: `app/services/ipam.py`'s new `overlaps_for_cidr()`
  runs the same duplicate/nested classification `find_overlapping_networks()`
  uses for the whole-table sweep, but against a single CIDR — usable right
  after a network is created, edited, or imported, without a second stored
  row to pair it against. Wired into `POST /ipam/networks`, `PATCH
  /ipam/networks/{id}`, and each row of the CSV import: every one returns
  an `overlap_warnings` list (empty/null when clean) rather than blocking —
  the per-account (cloud_account_id, cidr) uniqueness check is still a hard
  409, but a cross-account/cross-provider overlap is now surfaced instead
  of silently allowed the way it was before this change. New `GET
  /ipam/networks/{id}/overlaps` for an on-demand check outside those flows.
- **CSV export/import**: `GET /ipam/networks/export` streams the (optionally
  filtered) network list as a CSV; `POST /ipam/networks/import` reads one
  back, upserting by (cloud_account_id, cidr) — a CIDR already on that
  account updates in place instead of erroring, so re-importing a
  previously exported (and edited) file is the expected workflow, not an
  edge case. Each row resolves its cloud account by UUID or by
  provider+account_identifier, and runs in its own savepoint so one bad
  row doesn't sink the batch — the response's per-row `rows[]` list says
  created/updated/error for each one, plus that row's own
  `overlap_warnings`.
- **UI**: IPAM page's Networks panel header gained "Export CSV" (downloads
  via an authenticated blob fetch, not a plain link — the API needs the
  bearer token) and "Import CSV" (file input, multipart upload) buttons;
  an import-result panel lists created/updated/error counts and the
  specific rows with errors or overlaps. The network edit form now shows
  an amber alert listing any overlaps introduced by a saved CIDR change.
- **Tests**: 11 new tests (create/update overlap-warning presence and
  absence, the standalone `/overlaps` endpoint + 404, CSV export shape,
  CSV import create-then-update round-trip, import by
  provider+account_identifier, a bad row not aborting a good row in the
  same batch, missing-required-column 400, and an imported row correctly
  flagging an overlap) — 62 total, all passing against a real Postgres.

## Just completed: editable IPAM networks (CIDR/Name/Firewall/Environment)

- **Model**: `networks.firewall` column added (migration `9c2a7e5f1b3d`) —
  a free-text reference field (e.g. a firewall/appliance name), same style
  as `owner_team`/`vrf`, not yet FK'd to a device record.
- **API**: `PATCH /api/v1/ipam/networks/{id}` (new `NetworkUpdate` schema,
  `ipam:update` permission — already existed in `RESOURCE_AREAS`/`ROLE_GRANTS`,
  wasn't wired to an endpoint before). Partial update via
  `model_dump(exclude_unset=True)`; editing `cidr` re-parses, re-checks the
  per-account uniqueness constraint (409 on collision), and recomputes the
  stored network/broadcast/prefix columns. `GET /networks` and `POST
  /networks` responses now also include `firewall`.
- **UI**: IPAM page's Networks table gained Name/Firewall/Environment
  columns alongside CIDR/Provider/Subnets; the network detail pane gained
  an "Edit network" toggle with a CIDR/Name/Firewall/Environment form that
  PATCHes and refreshes the list + overlap check on save.
- **Tests**: 4 new tests (full update, partial update leaves other fields
  alone, duplicate-CIDR 409, unknown-network 404) — 51 total, all passing
  against a real Postgres.

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
