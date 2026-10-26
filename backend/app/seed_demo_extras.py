"""Idempotent demo-data filler, run AFTER `python -m app.seed` (and after at
least one discovery pass has populated networks/subnets/devices).

`app.seed` gives every module a live backend and the four-cloud + on-prem
mock inventory, but a handful of modules were built to be populated by a
real user action (upload a reference file, configure a TCPWave connection,
create a few accounts) rather than by discovery — so on a fresh install
they render correctly but empty: `/ipam-sync` with no integration configured,
`/automation`'s POA-generator tab with "0/7 reference files uploaded",
`/security-policies`' Security Groups tab with only whatever fwauto itself
has created, and a single demo admin account to show off RBAC with.

This script fills exactly those gaps with clearly-labeled demo content, so a
fresh `docker compose up` + `python -m app.seed` + `python -m
app.seed_demo_extras` gives a reviewer something to look at in every module
without having to manually configure anything first. It does not touch any
table `app.seed` or a discovery pass already populates (networks, subnets,
devices, circuits, etc.) — see each section below for exactly what it adds
and why that table was previously left for a real user action.

Idempotent: every section checks for its own marker (a fixed name, a fixed
`(subnet, ip)` pair, a fixed PoaReferenceFile.kind) before inserting, so
re-running this after it already ran, or after `app.seed` reseeds roles, is
a no-op rather than a pile of duplicates. Safe to run against the same
database `app.seed` just populated, or hours/days later.

Run with: `python -m app.seed_demo_extras`
"""
from __future__ import annotations

import io
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.integration import FirewallIntegration
from app.models.ipam_integration import IpamIntegration, IpamSyncRun
from app.models.network import IPAddress, Network, Subnet
from app.models.poa import PoaReferenceFile
from app.models.security_policy import SecurityGroup, SecurityRule
from app.models.user import Role, User
from app.security import hash_password
from app.services import secrets as secretsvc

_NOW = datetime.now(timezone.utc)


def _rand_ip(cidr_base: str, host: int) -> str:
    """cidr_base like '10.60.0' -> '10.60.0.<host>'."""
    return f"{cidr_base}.{host}"


# ---------------------------------------------------------------------------
# 1. A few more demo users, one per role not already represented, so the
#    RBAC model (8 seeded roles) has more than the one admin + one approver
#    test account to show off. `app.seed` only ever creates the admin;
#    `approver@netsphere.local` was created ad hoc during Phase 6 testing —
#    neither covers NOC_OPERATOR, AUDITOR, READ_ONLY, or a second
#    NETWORK_ENGINEER, which is the set this adds.
# ---------------------------------------------------------------------------
_DEMO_USERS = [
    ("engineer2@netsphere.local", "Priya Nair", "NETWORK_ENGINEER"),
    ("noc@netsphere.local", "Sam Okafor", "NOC_OPERATOR"),
    ("auditor@netsphere.local", "Jordan Blake", "AUDITOR"),
    ("viewer@netsphere.local", "Taylor Reyes", "READ_ONLY"),
]
_DEMO_PASSWORD = "ChangeMe123!"


def _seed_users(db: Session) -> None:
    roles_by_name = {r.name: r for r in db.query(Role).all()}
    existing_emails = {u.email for u in db.query(User).all()}
    for email, full_name, role_name in _DEMO_USERS:
        if email in existing_emails:
            continue
        role = roles_by_name.get(role_name)
        if not role:
            continue  # role set changed upstream; don't guess
        user = User(email=email, full_name=full_name, hashed_password=hash_password(_DEMO_PASSWORD), is_active=True)
        user.roles.append(role)
        db.add(user)
    db.commit()


# ---------------------------------------------------------------------------
# 2. A demo TCPWave integration + sync history + synced IP addresses.
#    `app/services/ipam_sync.py` only ever writes `ip_addresses` rows when a
#    real sync against a real TCPWave server runs — correctly, since faking
#    that would misrepresent a live integration as working. For a demo,
#    that leaves `/ipam-sync` completely empty on a fresh install. This adds
#    one integration record (clearly a demo host) and a believable sync
#    history + resulting synced IPs, exactly the *shape* `run_sync()` would
#    have produced, without claiming a real server was ever contacted.
# ---------------------------------------------------------------------------
def _seed_tcpwave(db: Session) -> IpamIntegration | None:
    existing = db.execute(select(IpamIntegration).where(IpamIntegration.name == "TCPWave - ONPREM (demo)")).scalar_one_or_none()
    if existing:
        return existing

    token_ciphertext = secretsvc.encrypt("demo-token-not-a-real-credential")
    integ = IpamIntegration(
        vendor="tcpwave",
        name="TCPWave - ONPREM (demo)",
        host="tcpwave-demo.internal.example",
        port=7443,
        verify_tls=True,
        auth_mode="token",
        token_ciphertext=token_ciphertext,
        token_last4="demo",
        organization_name="BFL-ONPREM",
    )
    db.add(integ)
    db.commit()
    db.refresh(integ)

    # Three historical sync runs: an initial full pull, a routine incremental
    # sync, and one that hit a transient error - the same "flaky link stays
    # visible, not silently a no-op" shape ipam_sync.py's docstring describes.
    runs = [
        dict(status="ok", networks_seen=19, networks_created=19, networks_updated=0,
             subnets_seen=45, subnets_created=45, subnets_updated=0,
             ips_seen=40, ips_created=40, ips_updated=0,
             started_delta=timedelta(days=6), finished_delta=timedelta(days=6, minutes=-4)),
        dict(status="ok", networks_seen=19, networks_created=0, networks_updated=2,
             subnets_seen=45, subnets_created=0, subnets_updated=3,
             ips_seen=42, ips_created=2, ips_updated=5,
             started_delta=timedelta(days=2), finished_delta=timedelta(days=2, minutes=-2)),
        dict(status="error", networks_seen=0, networks_created=0, networks_updated=0,
             subnets_seen=0, subnets_created=0, subnets_updated=0,
             ips_seen=0, ips_created=0, ips_updated=0,
             error_message="Connection timed out after 30s contacting tcpwave-demo.internal.example:7443",
             started_delta=timedelta(hours=6), finished_delta=timedelta(hours=6, minutes=-1)),
    ]
    for r in runs:
        created_at = _NOW - r.pop("started_delta")
        finished_at = _NOW - r.pop("finished_delta") if "finished_delta" in r else None
        run = IpamSyncRun(integration_id=integ.id, finished_at=finished_at, **r)
        run.created_at = created_at
        db.add(run)
    db.commit()
    return integ


def _seed_synced_ips(db: Session, integ: IpamIntegration | None) -> None:
    if integ is None:
        return
    # Pick a handful of real subnets already in inventory (from app.seed's
    # discovery pass) and populate a few allocated IPs in each, tagged as
    # though TCPWave had synced them - the exact shape ipam_sync.run_sync()
    # upserts, just without a live server behind it.
    subnets = db.execute(select(Subnet).order_by(Subnet.cidr).limit(8)).scalars().all()
    if not subnets:
        return
    hostnames = ["app01", "app02", "db01", "lb01", "cache01", "bastion01", "jump01", "web01"]
    existing_pairs = {(row.subnet_id, row.ip_address) for row in db.execute(select(IPAddress.subnet_id, IPAddress.ip_address)).all()}
    rnd = random.Random(42)  # deterministic demo data, not meant to vary run to run
    for subnet in subnets:
        base = ".".join(subnet.cidr.split("/")[0].split(".")[:3])
        for i, host_label in enumerate(hostnames[: rnd.randint(3, 5)], start=10):
            ip_str = _rand_ip(base, i)
            if (subnet.id, ip_str) in existing_pairs:
                continue
            ip_int = int.from_bytes(bytes(int(o) for o in ip_str.split(".")), "big")
            db.add(IPAddress(
                subnet_id=subnet.id, ip_address=ip_str, ip_int=ip_int,
                status="allocated", assigned_to=f"{host_label}.{subnet.name}.internal",
                hostname=f"{host_label}-{subnet.name}",
                external_source="tcpwave", external_ref=f"demo-{uuid.uuid4().hex[:8]}",
                last_synced_at=_NOW - timedelta(days=2),
            ))
    db.commit()


# ---------------------------------------------------------------------------
# 3. A few more normalized cloud security groups/rules, beyond the one
#    fwauto has already created through the live Security Policies pipeline
#    testing. These are marked source="discovered" / managed_by_fwauto=False
#    - representing pre-existing baseline rules an organization would already
#    have, exactly the category SecurityRule's own docstring describes for a
#    future backfill from `cloud_network_interfaces.security_groups`'
#    free-text data (ROADMAP's still-open backfill item) - this is demo
#    content in that same shape, not a claim that the real backfill ran.
# ---------------------------------------------------------------------------
_DEMO_SECURITY_GROUPS = [
    # (network_name, provider, group_name, rules: list of (direction, action, protocol, port_low, port_high, cidr, priority))
    ("vpc-prod-use1", "aws_sg", "prod-use1-web-sg", [
        ("inbound", "allow", "tcp", 443, 443, "0.0.0.0/0", None),
        ("inbound", "allow", "tcp", 80, 80, "0.0.0.0/0", None),
        ("inbound", "allow", "tcp", 22, 22, "10.0.0.0/8", None),
        ("outbound", "allow", "tcp", 1, 65535, "0.0.0.0/0", None),
    ]),
    ("vnet-prod-eastus", "azure_nsg", "prod-eastus-app-nsg", [
        ("inbound", "allow", "tcp", 443, 443, "10.0.0.0/8", 100),
        ("inbound", "deny", "tcp", 3389, 3389, "0.0.0.0/0", 110),
        ("inbound", "allow", "tcp", 8080, 8080, "172.16.0.0/16", 120),
    ]),
    ("vpc-prod-vpc", "gcp_firewall", "prod-vpc-default-allow", [
        ("inbound", "allow", "tcp", 22, 22, "10.50.0.0/16", 1000),
        ("inbound", "allow", "icmp", None, None, "10.50.0.0/16", 1000),
        ("inbound", "allow", "tcp", 3306, 3306, "10.50.1.0/24", 900),
    ]),
    ("vcn-prod-vcn", "oci_security_list", "prod-vcn-default-sl", [
        ("inbound", "allow", "tcp", 443, 443, "0.0.0.0/0", None),
        ("inbound", "allow", "tcp", 22, 22, "10.60.0.0/16", None),
        ("outbound", "allow", "tcp", 1, 65535, "0.0.0.0/0", None),
    ]),
]


def _seed_security_groups(db: Session) -> None:
    for network_name, provider, group_name, rules in _DEMO_SECURITY_GROUPS:
        existing = db.execute(select(SecurityGroup).where(SecurityGroup.name == group_name)).scalar_one_or_none()
        if existing:
            continue
        network = db.execute(select(Network).where(Network.name == network_name)).scalar_one_or_none()
        if not network:
            continue  # discovery hasn't created this network in this environment - skip rather than guess
        sg = SecurityGroup(
            network_id=network.id, cloud_account_id=network.cloud_account_id,
            provider=provider, name=group_name, description="Pre-existing baseline rules (demo data)",
            source="discovered",
        )
        db.add(sg)
        db.commit()
        db.refresh(sg)
        for direction, action, protocol, port_low, port_high, cidr, priority in rules:
            db.add(SecurityRule(
                security_group_id=sg.id, direction=direction, action=action, protocol=protocol,
                port_low=port_low, port_high=port_high, cidr=cidr, priority=priority,
                status="active", source="discovered", managed_by_fwauto=False,
            ))
        db.commit()


# ---------------------------------------------------------------------------
# 4. POA reference files - seven small, structurally-valid synthetic sheets
#    (correct columns for app/poa/lookup.py's loaders, demo values matching
#    this delivery's own OCI mock inventory) so `/automation`'s POA-generator
#    tab shows "7 / 7 uploaded" and a demo POA run can actually be generated
#    end to end, instead of every row reading "not uploaded - manual entry
#    required". Not real BFL/Bajaj inventory data (same rule `app/poa/
#    README.md` and the POA generator's own "deliberately not done" note
#    already established - see claude/netsphere-platform.md).
# ---------------------------------------------------------------------------
def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    for row in rows:
        buf.write(",".join(row) + "\r\n")
    return buf.getvalue().encode("utf-8")


_REFERENCE_FILES: dict[str, bytes] = {
    "oci_uat_inventory": _csv([
        ["Subnet_CIDR", "Subnet_Name", "VCN_Name", "VCN_CIDR", "Compartment_Name", "Region", "Route_Table", "Security_Lists", "NSG_Count"],
        ["10.62.0.0/24", "subnet-1", "vcn-shared-vcn", "10.62.0.0/16", "shared-services", "us-ashburn-1", "Default Route Table for vcn-shared-vcn", "Default Security List for vcn-shared-vcn,InfraTool_SL", "1"],
        ["10.62.1.0/24", "subnet-2", "vcn-shared-vcn", "10.62.0.0/16", "shared-services", "us-ashburn-1", "Default Route Table for vcn-shared-vcn", "Default Security List for vcn-shared-vcn", "0"],
    ]),
    "oci_prod_inventory": _csv([
        ["Subnet_CIDR", "Subnet_Name", "VCN_Name", "VCN_CIDR", "Compartment_Name", "Region", "Route_Table", "Security_Lists", "NSG_Count"],
        ["10.60.0.0/24", "subnet-1", "vcn-prod-vcn", "10.60.0.0/16", "prod", "us-ashburn-1", "Default Route Table for vcn-prod-vcn", "Default Security List for vcn-prod-vcn,InfraTool_SL", "2"],
        ["10.60.1.0/24", "subnet-2", "vcn-prod-vcn", "10.60.0.0/16", "prod", "us-ashburn-1", "Default Route Table for vcn-prod-vcn", "Default Security List for vcn-prod-vcn", "1"],
        ["10.61.0.0/24", "subnet-1", "vcn-prod-vcn-uk", "10.61.0.0/16", "prod-uk", "uk-london-1", "Default Route Table for vcn-prod-vcn-uk", "Default Security List for vcn-prod-vcn-uk,InfraTool_SL", "1"],
    ]),
    "cidr_firewall_inventory": _csv([
        ["CIDR", "Firewall", "Name", "Environment"],
        ["10.60.0.0/16", "BFL-OCI-MUM-PROD-DG", "vcn-prod-vcn", "PROD"],
        ["10.61.0.0/16", "BFL-OCI-HYD-DR-DG", "vcn-prod-vcn-uk", "PROD"],
        ["10.62.0.0/16", "BFLIUAT-OCI-PA-NGFW", "vcn-shared-vcn", "UAT"],
        ["10.99.0.0/24", "edge-fw-01", "DC1-Core", "ONPREM"],
        ["10.99.1.0/24", "edge-fw-01", "DC1-Edge", "ONPREM"],
        ["10.99.10.0/24", "dc2-edge-rtr-01", "DC2-Edge", "ONPREM"],
    ]),
    "network_ipam": _csv([
        ["Address", "Name", "VRF"],
        ["10.99.0.0/24", "DC1-Core", "DC1"],
        ["10.99.1.0/24", "DC1-Edge", "DC1"],
        ["10.99.10.0/24", "DC2-Edge", "DC2"],
        ["10.10.0.0/16", "DC1-Prod-Legacy", "DC1"],
    ]),
    "oci_uat_nsg_sl_report": _csv([
        ["IP_Address", "Resource_Name", "Resource_Type", "Attached_NSGs", "Subnet_Security_Lists", "VCN_Name", "Subnet_Name"],
        ["10.62.0.10", "shared-bastion-01", "Instance", "InfraTools_NSG,shared-bastion-nsg", "Default Security List for vcn-shared-vcn,InfraTool_SL", "vcn-shared-vcn", "subnet-1"],
        ["10.62.1.10", "shared-cache-01", "Instance", "InfraTools_NSG", "Default Security List for vcn-shared-vcn", "vcn-shared-vcn", "subnet-2"],
    ]),
    "oci_prod_nsg_sl_report": _csv([
        ["IP_Address", "Resource_Name", "Resource_Type", "Attached_NSGs", "Subnet_Security_Lists", "VCN_Name", "Subnet_Name"],
        ["10.60.0.10", "prod-app-01", "Instance", "InfraTools_NSG,prod-app-nsg", "Default Security List for vcn-prod-vcn,InfraTool_SL", "vcn-prod-vcn", "subnet-1"],
        ["10.60.1.10", "prod-db-01", "Instance", "InfraTools_NSG,prod-db-nsg", "Default Security List for vcn-prod-vcn", "vcn-prod-vcn", "subnet-2"],
        ["10.61.0.10", "prod-uk-lb-01", "LoadBalancer", "InfraTools_NSG", "Default Security List for vcn-prod-vcn-uk,InfraTool_SL", "vcn-prod-vcn-uk", "subnet-1"],
    ]),
    "security_list_audit": _csv([
        ["SecurityList", "TotalRules", "VCN", "RuleLimit", "RemainingHeadroom"],
        ["Default Security List for vcn-prod-vcn", "94", "vcn-prod-vcn", "120", "26"],
        ["Default Security List for vcn-prod-vcn-uk", "61", "vcn-prod-vcn-uk", "120", "59"],
        ["Default Security List for vcn-shared-vcn", "15", "vcn-shared-vcn", "120", "105"],
    ]),
}


def _seed_poa_reference_files(db: Session) -> None:
    existing_kinds = {row.kind for row in db.execute(select(PoaReferenceFile)).scalars().all()}
    admin = db.query(User).filter(User.email == "admin@netsphere.local").first()
    for kind, content in _REFERENCE_FILES.items():
        if kind in existing_kinds:
            continue
        db.add(PoaReferenceFile(
            kind=kind, filename=f"{kind}-demo.csv", content=content, size_bytes=len(content),
            uploaded_by_id=admin.id if admin else None,
        ))
    db.commit()


# ---------------------------------------------------------------------------
# 5. A couple more Firewalls/Integrations rows, beyond the single
#    "Fake Panorama Test" row created during earlier phase testing. The
#    live `security_policy_resolve.resolve_destination()` requires *exactly
#    one* active, root (parent_id is NULL) FirewallIntegration to resolve an
#    on-prem destination - verified live in Phase 6 - so this deliberately
#    does NOT add a second active root. Instead it adds: (a) a standalone
#    FortiGate root that is inactive (a believable "DR standby, not yet
#    cut over" demo row, is_active=False so it can never be picked up by
#    resolve_destination's exactly-one-active-root query), and (b) an
#    "ngfw" child row under the existing active Panorama root, showing the
#    device-group hierarchy the model's own docstring describes (holds no
#    secret of its own - device_group/serial only).
# ---------------------------------------------------------------------------
def _seed_firewall_integrations(db: Session) -> None:
    existing_names = {row.name for row in db.execute(select(FirewallIntegration)).scalars().all()}

    if "FortiGate DR - standby (demo)" not in existing_names:
        secret_ciphertext = secretsvc.encrypt("demo-token-not-a-real-credential")
        db.add(FirewallIntegration(
            vendor="fortigate",
            name="FortiGate DR - standby (demo)",
            host="fortigate-dr-demo.internal.example",
            port=443,
            verify_tls=True,
            auth_type="api_key",
            secret_ciphertext=secret_ciphertext,
            secret_last4="demo",
            is_active=False,
            notes="Demo data - DR standby, not cut over. Deliberately inactive so it never "
                  "competes with the single active root integration resolve_destination() requires.",
        ))
        db.commit()

    if "BFL-OCI-MUM-PROD-DG (demo)" not in existing_names:
        panorama_root = db.execute(
            select(FirewallIntegration).where(FirewallIntegration.vendor == "panorama", FirewallIntegration.parent_id.is_(None))
        ).scalars().first()
        if panorama_root:
            db.add(FirewallIntegration(
                vendor="ngfw",
                name="BFL-OCI-MUM-PROD-DG (demo)",
                parent_id=panorama_root.id,
                device_group="BFL-OCI-MUM-PROD-DG",
                serial="007DEMO0001",
                is_active=True,
                secret_last4="",
                notes="Demo data - device group reference only, no credentials of its own "
                      "(managed via its parent Panorama root).",
            ))
            db.commit()


def seed_demo_extras() -> None:
    db = SessionLocal()
    try:
        _seed_users(db)
        integ = _seed_tcpwave(db)
        _seed_synced_ips(db, integ)
        _seed_security_groups(db)
        _seed_poa_reference_files(db)
        _seed_firewall_integrations(db)
        print("Demo extras seeded (or already present).")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_extras()
