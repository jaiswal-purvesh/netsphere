"""Real GCP adapter. Phase 3: google-cloud-compute + a service account key
sourced from a CloudIntegration credential (app/models/cloud_integration.py,
stored as the full JSON key file content under "service_account_json").
Only this file may import google.* — see providers/base.py's rule.

GCP CIDRs live on the (regional) Subnetwork resource, not on the Network
resource itself (a VPC is global and CIDR-less in "custom subnet mode",
which is what every project actually uses today) — so this discovers
subnetworks first via an aggregated list, then groups them by their parent
network to build one DiscoveredNetwork per VPC.
"""
from __future__ import annotations

import json

from google.api_core.exceptions import GoogleAPIError
from google.cloud.compute_v1 import NetworksClient, SubnetworksClient
from google.oauth2 import service_account

from app.providers.base import CloudProvider, DiscoveredNetwork, DiscoveredSubnet
from app.services.cidr import CidrError, int_to_ip, parse_cidr


def _enclosing_cidr(subnet_cidrs: list[str]) -> str:
    """GCP VPCs are global and have no CIDR of their own in custom-subnet
    mode (every project in practice) — only their regional Subnetworks do.
    Rather than inventing a sentinel value the rest of the schema doesn't
    expect (Network.cidr is NOT NULL, see app/models/network.py), compute
    the smallest CIDR block that contains every discovered subnet, which is
    a genuinely meaningful "network footprint" figure. Falls back to a
    degenerate /32 at 0.0.0.0 only for a brand-new VPC with zero subnets."""
    parsed = []
    for c in subnet_cidrs:
        try:
            parsed.append(parse_cidr(c))
        except CidrError:
            continue
    if not parsed:
        return "0.0.0.0/32"

    lo = min(p.network for p in parsed)
    hi = max(p.broadcast for p in parsed)
    for prefix_len in range(32, -1, -1):
        host_bits = 32 - prefix_len
        mask = 0 if host_bits == 32 else (0xFFFFFFFF << host_bits) & 0xFFFFFFFF
        block_start = lo & mask
        block_end = block_start | (~mask & 0xFFFFFFFF)
        if block_start <= lo and block_end >= hi:
            return f"{int_to_ip(block_start)}/{prefix_len}"
    return "0.0.0.0/0"


class GCPProvider(CloudProvider):
    provider_name = "gcp"

    def _credentials(self) -> service_account.Credentials:
        if not self.credentials:
            raise NotImplementedError(
                f"GCPProvider requires a configured, active GCP integration for project "
                f"{self.account_identifier} (Integrations tab) — none found. Use "
                "providers.mock.gcp.MockGCPProvider for local development and demos.",
            )
        info = json.loads(self.credentials["service_account_json"])
        return service_account.Credentials.from_service_account_info(info)

    def discover_networks(self) -> list[DiscoveredNetwork]:
        creds = self._credentials()
        project = self.account_identifier
        try:
            networks = list(NetworksClient(credentials=creds).list(project=project))
            subnet_pages = SubnetworksClient(credentials=creds).aggregated_list(project=project)
        except GoogleAPIError as e:
            raise RuntimeError(f"GCP compute API call failed: {e}") from e

        by_network_url: dict[str, list[DiscoveredSubnet]] = {}
        for _scope, scoped_list in subnet_pages:
            for sub in getattr(scoped_list, "subnetworks", []) or []:
                if self.region and self.region not in (sub.region or ""):
                    continue
                by_network_url.setdefault(sub.network, []).append(DiscoveredSubnet(
                    external_id=str(sub.id), cidr=sub.ip_cidr_range or "",
                    availability_zone=sub.region.rsplit("/", 1)[-1] if sub.region else None,
                    name=sub.name,
                ))

        out: list[DiscoveredNetwork] = []
        for net in networks:
            subnets = by_network_url.get(net.self_link, [])
            out.append(DiscoveredNetwork(
                external_id=str(net.id), name=net.name,
                cidr=_enclosing_cidr([s.cidr for s in subnets]),
                region=self.region or "global", account_identifier=project,
                subnets=subnets,
                tags={},
            ))
        return out
