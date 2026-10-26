"""Mock OCI provider — deterministic demo data, no network calls. Same
role as providers/mock/aws.py: proves the provider adapter pattern for a
fourth cloud without needing real OCI credentials.

Demo shape follows providers/mock/README.md's numbers for OCI: 2
compartments, 3 VCNs total, 8 subnets total (uneven per-VCN counts).
"""
from __future__ import annotations

from app.providers.base import CloudProvider, DiscoveredNetwork, DiscoveredSubnet

_DEMO_COMPARTMENTS = ["ocid1.compartment.oc1..demoprod", "ocid1.compartment.oc1..demoshared"]

# (compartment_index, vcn_suffix, cidr, region, subnet_count)
_DEMO_VCNS = [
    (0, "prod-vcn", "10.60.0.0/16", "us-ashburn-1", 3),
    (0, "prod-vcn-uk", "10.61.0.0/16", "uk-london-1", 3),
    (1, "shared-vcn", "10.62.0.0/16", "us-ashburn-1", 2),
]


def _subnets_for(cidr_base: str, count: int) -> list[DiscoveredSubnet]:
    prefix = cidr_base.split(".")[0:2]
    return [
        DiscoveredSubnet(
            external_id=f"subnet-{prefix[0]}{prefix[1]}0{i}",
            cidr=f"{prefix[0]}.{prefix[1]}.{i}.0/24",
            availability_zone=f"{cidr_base.split('.')[0]}-ad-{i + 1}",
            name=f"subnet-{i + 1}",
        )
        for i in range(count)
    ]


class MockOCIProvider(CloudProvider):
    provider_name = "oci"

    def discover_networks(self) -> list[DiscoveredNetwork]:
        networks = []
        for idx, suffix, cidr, region, subnet_count in _DEMO_VCNS:
            compartment = _DEMO_COMPARTMENTS[idx]
            if compartment != self.account_identifier and self.account_identifier != "*":
                continue
            networks.append(DiscoveredNetwork(
                external_id=f"vcn-{suffix}",
                name=f"vcn-{suffix}",
                cidr=cidr,
                region=region,
                account_identifier=compartment,
                subnets=_subnets_for(cidr, subnet_count),
                tags={"ManagedBy": "netsphere-mock", "Environment": suffix.split("-")[0]},
            ))
        return networks

    @staticmethod
    def demo_accounts() -> list[str]:
        return list(_DEMO_COMPARTMENTS)
