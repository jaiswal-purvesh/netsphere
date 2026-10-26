# Mock providers

Every cloud the product spec names now has a complete mock: deterministic
demo VPCs/VNets/subnets, used by the discovery endpoints and the
docker-compose default seed so the whole platform demos without any real
cloud credentials.

| Provider | File | Accounts (fake) | Networks | Subnets |
|---|---|---|---|---|
| AWS | `aws.py` | 3 accounts | 5 VPCs | 15 |
| Azure | `azure.py` | 3 subscriptions | 4 VNets | 12 |
| GCP | `gcp.py` | 3 projects | 4 VPCs | 10 |
| OCI | `oci.py` | 2 compartments | 3 VCNs | 8 |

`snmp.py` is the same idea for the device/interface side of Phase 2: 4
demo devices / 8 interfaces across 2 sites, no real SNMP access needed.

All five are wired into `app/seed.py`, which auto-runs discovery for every
one of them right after creating the matching demo cloud accounts /
environment, so `docker compose up` leaves the Dashboard, IPAM, and
Network Inventory pages fully populated with zero manual API calls.

Address ranges are kept disjoint on purpose so the overlap detector
(`GET /api/v1/ipam/overlaps`) never false-flags the demo data against
itself: AWS uses `10.10.0.0/16`-`10.30.0.0/16`, Azure `172.16.0.0/16`-
`172.19.0.0/16`, GCP `10.50.0.0/16`-`10.53.0.0/16`, OCI `10.60.0.0/16`-
`10.62.0.0/16`, and the SNMP mock's on-prem devices sit in `10.99.0.0/16`.

Adding a fifth mock provider (for a cloud the spec doesn't currently name,
or a second on-prem discovery method) is mechanical — copy whichever
existing file is the closer shape: a `_DEMO_*` data table + a
`discover_networks()`/`discover_devices()` that filters by
`account_identifier` (cloud) or `site` (device), pick a CIDR range nothing
else uses, and wire it into `discovery.py` and `seed.py`'s
`_CLOUD_PROVIDERS` list the same way the four here are.
