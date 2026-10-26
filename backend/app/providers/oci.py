"""Real OCI adapter. Phase 3: the `oci` SDK + a user/API-key signing
credential sourced from a CloudIntegration credential
(app/models/cloud_integration.py) — the private key is passed in-memory via
`key_content` (never written to disk). Only this file may import `oci` —
see providers/base.py's rule.

`account_identifier` here is an OCI compartment OCID (matching
cloud_accounts.account_identifier per docs/ERD.md's "2 compartments" demo
note), which is what `list_vcns`/`list_subnets` are scoped by.
"""
from __future__ import annotations

import oci
from oci.exceptions import ServiceError

from app.providers.base import CloudProvider, DiscoveredNetwork, DiscoveredSubnet


class OCIProvider(CloudProvider):
    provider_name = "oci"

    def _client(self) -> "oci.core.VirtualNetworkClient":
        if not self.credentials:
            raise NotImplementedError(
                f"OCIProvider requires a configured, active OCI integration for compartment "
                f"{self.account_identifier} (Integrations tab) — none found. Use "
                "providers.mock.oci.MockOCIProvider for local development and demos.",
            )
        config = {
            "user": self.credentials["user_ocid"],
            "tenancy": self.credentials["tenancy_ocid"],
            "fingerprint": self.credentials["fingerprint"],
            "key_content": self.credentials["private_key_pem"],
            "region": self.region or self.credentials.get("region") or "us-ashburn-1",
        }
        return oci.core.VirtualNetworkClient(config)

    def discover_networks(self) -> list[DiscoveredNetwork]:
        try:
            client = self._client()
        except (oci.exceptions.InvalidConfig, oci.exceptions.InvalidPrivateKey, ValueError) as e:
            raise RuntimeError(f"OCI config/key invalid: {e}") from e

        compartment_id = self.account_identifier
        try:
            vcns = client.list_vcns(compartment_id=compartment_id).data
        except ServiceError as e:
            raise RuntimeError(f"OCI list_vcns failed: {e.message}") from e

        networks: list[DiscoveredNetwork] = []
        for vcn in vcns:
            cidr_blocks = getattr(vcn, "cidr_blocks", None) or ([vcn.cidr_block] if vcn.cidr_block else [])
            try:
                subnets_data = client.list_subnets(compartment_id=compartment_id, vcn_id=vcn.id).data
            except ServiceError as e:
                raise RuntimeError(f"OCI list_subnets failed for {vcn.id}: {e.message}") from e

            subnets = [
                DiscoveredSubnet(
                    external_id=s.id, cidr=s.cidr_block,
                    availability_zone=s.availability_domain, name=s.display_name,
                )
                for s in subnets_data
            ]
            tags = dict(getattr(vcn, "freeform_tags", None) or {})
            networks.append(DiscoveredNetwork(
                external_id=vcn.id, name=vcn.display_name, cidr=cidr_blocks[0] if cidr_blocks else "0.0.0.0/32",
                region=self.region or "", account_identifier=compartment_id,
                subnets=subnets, tags=tags,
            ))
        return networks
