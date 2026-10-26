"""Mock SNMP provider — deterministic demo data, no network calls. Same
role as providers/mock/aws.py but for the device/interface inventory side
of Phase 2: proves discover -> normalize -> ingest -> show in
Dashboard/Network Inventory end to end without needing real SNMP access
to anything.

One interface (core-rtr-01's Gi0/1, 10.10.0.5) is deliberately inside the
AWS mock's prod-use1 VPC's first subnet (10.10.0.0/24) so that
app/services/devices.py's best-effort subnet cross-link has something real
to find in the seeded demo data, not just an always-empty code path.
"""
from __future__ import annotations

from app.providers.base import (
    DiscoveredBgpSession,
    DiscoveredCircuit,
    DiscoveredDevice,
    DiscoveredInterface,
    DiscoveredRoute,
    NetworkDeviceProvider,
)

# The on-prem side of the exact same physical interconnects the cloud
# mocks report from their own side (see providers/mock/aws.py's/azure.py's
# own _DEMO_DIRECT_CONNECTS/_DEMO_EXPRESSROUTES) — core-rtr-01 (dc1) is
# already the router with the "uplink to prod-use1" interface, so it's the
# natural MPLS PE-facing handoff for AWS's Direct Connect; dc2-edge-rtr-01
# plays the same role for Azure's ExpressRoute. BGP local/peer ASN and IP
# are each mirrored from the matching cloud-side circuit (local here =
# peer there, and vice versa) so the two independently-discovered Circuit
# rows describe the two ends of one real link, not two unrelated ones.
_DEMO_CIRCUITS = [
    DiscoveredCircuit(
        external_id="dc1-mpls-use1", name="MPLS handoff to AWS us-east-1", circuit_type="mpls",
        vrf="vrf-prod", bandwidth_mbps=1000, location="dc1 MPLS PE", status="active",
        attached_device_hostname="core-rtr-01",
        bgp_sessions=[DiscoveredBgpSession(
            local_asn=64512, peer_asn=65000, local_ip="169.254.1.2", peer_ip="169.254.1.1",
            external_id="dc1-mpls-use1-bgp",
        )],
    ),
    DiscoveredCircuit(
        external_id="dc2-mpls-westeu", name="MPLS handoff to Azure westeurope", circuit_type="mpls",
        vrf="vrf-prod-eu", bandwidth_mbps=1000, location="dc2 MPLS PE", status="active",
        attached_device_hostname="dc2-edge-rtr-01",
        bgp_sessions=[DiscoveredBgpSession(
            local_asn=64512, peer_asn=65010, local_ip="169.254.11.2", peer_ip="169.254.11.1",
            external_id="dc2-mpls-westeu-bgp",
        )],
    ),
]

_DEMO_DEVICES = [
    DiscoveredDevice(
        external_id="dc1-core-rtr-01", hostname="core-rtr-01", device_type="router",
        vendor="cisco", mgmt_ip="10.99.0.1", site="dc1",
        interfaces=[
            DiscoveredInterface(
                external_id="dc1-core-rtr-01:Gi0/0", name="GigabitEthernet0/0",
                description="mgmt", ip_address="10.99.0.1", mac_address="00:1a:2b:00:00:01",
                speed_mbps=1000,
            ),
            DiscoveredInterface(
                external_id="dc1-core-rtr-01:Gi0/1", name="GigabitEthernet0/1",
                description="uplink to prod-use1", ip_address="10.10.0.5", mac_address="00:1a:2b:00:00:02",
                speed_mbps=1000, vlan_id=10,
            ),
        ],
        routes=[
            DiscoveredRoute(destination_cidr="10.99.0.0/16", target_type="local", target_ref="connected"),
            DiscoveredRoute(
                destination_cidr="10.10.0.0/16", target_type="next_hop", target_ref="10.10.0.1",
                external_id="dc1-core-rtr-01:static-1",
            ),
            DiscoveredRoute(
                destination_cidr="0.0.0.0/0", target_type="interface", target_ref="GigabitEthernet0/0",
                external_id="dc1-core-rtr-01:static-default",
            ),
        ],
    ),
    DiscoveredDevice(
        external_id="dc1-core-sw-01", hostname="core-sw-01", device_type="switch",
        vendor="cisco", mgmt_ip="10.99.0.2", site="dc1",
        interfaces=[
            DiscoveredInterface(
                external_id="dc1-core-sw-01:Gi1/0/1", name="GigabitEthernet1/0/1",
                description="access", ip_address=None, mac_address="00:1a:2b:00:01:01",
                speed_mbps=1000, vlan_id=20,
            ),
            DiscoveredInterface(
                external_id="dc1-core-sw-01:Gi1/0/2", name="GigabitEthernet1/0/2",
                description="access", ip_address=None, mac_address="00:1a:2b:00:01:02",
                speed_mbps=1000, vlan_id=20,
            ),
            DiscoveredInterface(
                external_id="dc1-core-sw-01:Po1", name="Port-channel1",
                description="trunk to core-rtr-01", ip_address=None, mac_address="00:1a:2b:00:01:ff",
                speed_mbps=2000, vlan_id=None,
            ),
        ],
    ),
    DiscoveredDevice(
        external_id="dc1-edge-fw-01", hostname="edge-fw-01", device_type="firewall",
        vendor="paloalto", mgmt_ip="10.99.0.3", site="dc1",
        interfaces=[
            DiscoveredInterface(
                external_id="dc1-edge-fw-01:eth1/1", name="ethernet1/1",
                description="untrust", ip_address="10.99.1.1", mac_address="00:1a:2b:00:02:01",
                speed_mbps=1000,
            ),
            DiscoveredInterface(
                external_id="dc1-edge-fw-01:eth1/2", name="ethernet1/2",
                description="trust", ip_address="10.99.1.2", mac_address="00:1a:2b:00:02:02",
                speed_mbps=1000,
            ),
        ],
        routes=[
            DiscoveredRoute(destination_cidr="10.99.1.0/24", target_type="local", target_ref="connected"),
            DiscoveredRoute(
                destination_cidr="0.0.0.0/0", target_type="next_hop", target_ref="10.99.1.254",
                external_id="dc1-edge-fw-01:static-default",
            ),
        ],
    ),
    DiscoveredDevice(
        external_id="dc2-edge-rtr-01", hostname="dc2-edge-rtr-01", device_type="router",
        vendor="juniper", mgmt_ip="10.99.10.1", site="dc2",
        interfaces=[
            DiscoveredInterface(
                external_id="dc2-edge-rtr-01:ge-0/0/0", name="ge-0/0/0",
                description="mgmt", ip_address="10.99.10.1", mac_address="00:1a:2b:00:03:01",
                speed_mbps=1000,
            ),
        ],
        routes=[
            DiscoveredRoute(destination_cidr="10.99.10.0/24", target_type="local", target_ref="connected"),
            DiscoveredRoute(
                destination_cidr="10.99.0.0/16", target_type="next_hop", target_ref="10.99.10.254",
                external_id="dc2-edge-rtr-01:static-dc1",
            ),
        ],
    ),
]


class MockSNMPProvider(NetworkDeviceProvider):
    provider_name = "snmp"

    def __init__(self, site: str | None = None) -> None:
        self.site = site

    def discover_devices(self) -> list[DiscoveredDevice]:
        if self.site is None:
            return list(_DEMO_DEVICES)
        return [d for d in _DEMO_DEVICES if d.site == self.site]

    def discover_circuits(self) -> list[DiscoveredCircuit]:
        if self.site is None:
            return list(_DEMO_CIRCUITS)
        sites = {d.hostname: d.site for d in _DEMO_DEVICES}
        return [c for c in _DEMO_CIRCUITS if sites.get(c.attached_device_hostname) == self.site]
