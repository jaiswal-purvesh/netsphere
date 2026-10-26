"""Mock GCP provider — deterministic demo data, no network calls. Same
role as providers/mock/aws.py: proves the provider adapter pattern for a
third cloud without needing real GCP credentials.

Demo shape follows providers/mock/README.md's numbers for GCP: 3 projects,
4 VPCs total, 10 subnets total (uneven per-VPC counts, unlike AWS/Azure's
uniform 3-per-network — GCP VPCs commonly have a different subnet per
region rather than a fixed count, which this mirrors).
"""
from __future__ import annotations

from app.providers.base import CloudProvider, DiscoveredNetwork, DiscoveredSubnet

_DEMO_PROJECTS = ["netsphere-demo-prod", "netsphere-demo-staging", "netsphere-demo-shared"]

# (project_index, vpc_suffix, cidr, region, subnet_count)
_DEMO_VPCS = [
    (0, "prod-vpc", "10.50.0.0/16", "us-central1", 3),
    (0, "prod-vpc-euw", "10.51.0.0/16", "europe-west1", 3),
    (1, "staging-vpc", "10.52.0.0/16", "us-central1", 2),
    (2, "shared-vpc", "10.53.0.0/16", "us-central1", 2),
]


def _subnets_for(cidr_base: str, count: int) -> list[DiscoveredSubnet]:
    prefix = cidr_base.split(".")[0:2]
    return [
        DiscoveredSubnet(
            external_id=f"subnet-{prefix[0]}{prefix[1]}0{i}",
            cidr=f"{prefix[0]}.{prefix[1]}.{i}.0/24",
            availability_zone=f"{cidr_base.split('.')[0]}-zone-{chr(97 + i)}",
            name=f"subnet-{i + 1}",
        )
        for i in range(count)
    ]


class MockGCPProvider(CloudProvider):
    provider_name = "gcp"

    def discover_networks(self) -> list[DiscoveredNetwork]:
        networks = []
        for idx, suffix, cidr, region, subnet_count in _DEMO_VPCS:
            project = _DEMO_PROJECTS[idx]
            if project != self.account_identifier and self.account_identifier != "*":
                continue
            networks.append(DiscoveredNetwork(
                external_id=f"vpc-{suffix}",
                name=f"vpc-{suffix}",
                cidr=cidr,
                region=region,
                account_identifier=project,
                subnets=_subnets_for(cidr, subnet_count),
                tags={"ManagedBy": "netsphere-mock", "Environment": suffix.split("-")[0]},
            ))
        return networks

    @staticmethod
    def demo_accounts() -> list[str]:
        return list(_DEMO_PROJECTS)
