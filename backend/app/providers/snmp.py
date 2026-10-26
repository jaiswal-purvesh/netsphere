"""Real SNMP/SSH device-discovery adapter — NOT IMPLEMENTED. Intentional,
same rationale as providers/aws.py: see ARCHITECTURE.md §3. Wiring this up
for real is a Phase 3 task: `pip install pysnmp`, walk the standard
IF-MIB (ifTable/ifXTable) for interfaces plus SNMPv2-MIB (sysName,
sysDescr) for device identity, against a community string or SNMPv3
credential per device/site (see SECURITY.md for where that credential
would need to live — nothing in this delivery reads one).
"""
from __future__ import annotations

from app.providers.base import DiscoveredDevice, NetworkDeviceProvider


class SNMPProvider(NetworkDeviceProvider):
    provider_name = "snmp"

    def __init__(self, site: str | None = None) -> None:
        self.site = site

    def discover_devices(self) -> list[DiscoveredDevice]:
        raise NotImplementedError(
            "SNMPProvider requires pysnmp and a community string/SNMPv3 "
            f"credential for site {self.site!r} — not configured in this "
            "deployment. Use providers.mock.snmp.MockSNMPProvider for local "
            "development and demos.",
        )
