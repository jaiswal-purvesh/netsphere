"""Real Azure adapter. Phase 3: azure-identity + azure-mgmt-network, a
Service Principal sourced from a CloudIntegration credential
(app/models/cloud_integration.py). Only this file may import the azure-*
SDKs — see providers/base.py's rule.
"""
from __future__ import annotations

from azure.core.exceptions import AzureError
from azure.identity import ClientSecretCredential
from azure.mgmt.network import NetworkManagementClient

from app.providers.base import CloudProvider, DiscoveredNetwork, DiscoveredSubnet


class AzureProvider(CloudProvider):
    provider_name = "azure"

    def _client(self) -> NetworkManagementClient:
        if not self.credentials:
            raise NotImplementedError(
                f"AzureProvider requires a configured, active Azure integration for subscription "
                f"{self.account_identifier} (Integrations tab) — none found. Use "
                "providers.mock.azure.MockAzureProvider for local development and demos.",
            )
        credential = ClientSecretCredential(
            tenant_id=self.credentials["tenant_id"],
            client_id=self.credentials["client_id"],
            client_secret=self.credentials["client_secret"],
        )
        return NetworkManagementClient(credential, self.credentials["subscription_id"])

    def discover_networks(self) -> list[DiscoveredNetwork]:
        client = self._client()
        try:
            vnets = list(client.virtual_networks.list_all())
        except AzureError as e:
            raise RuntimeError(f"Azure virtual_networks.list_all failed: {e}") from e

        networks: list[DiscoveredNetwork] = []
        for vnet in vnets:
            cidr = (vnet.address_space.address_prefixes or [""])[0] if vnet.address_space else ""
            region = vnet.location or self.region or ""
            if self.region and region != self.region:
                continue
            subnets = [
                DiscoveredSubnet(
                    external_id=s.id or s.name, cidr=s.address_prefix or "", name=s.name,
                )
                for s in (vnet.subnets or [])
                if s.address_prefix
            ]
            tags = dict(vnet.tags or {})
            networks.append(DiscoveredNetwork(
                external_id=vnet.id or vnet.name, name=vnet.name, cidr=cidr,
                region=region, account_identifier=self.account_identifier,
                subnets=subnets, tags=tags,
            ))
        return networks
