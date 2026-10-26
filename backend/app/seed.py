"""Idempotent local-dev seed: roles, permissions, one admin user, a demo org
hierarchy (Organization -> BusinessUnit -> Environment -> CloudAccount)
matching every mock cloud provider's fake account IDs (AWS/Azure/GCP/OCI),
and mock discovery run for all four clouds plus SNMP (on-prem
devices/interfaces) so the Dashboard/IPAM/Network Inventory pages are
populated immediately after `docker compose up` with zero manual API
calls. Run with `python -m app.seed`.
"""
from __future__ import annotations

from app.core.rbac_seed import ALL_PERMISSION_CODES, ROLE_GRANTS
from app.db import SessionLocal
from app.models.org import BusinessUnit, CloudAccount, Environment, Organization
from app.models.user import ALL_ROLES, Permission, Role, User
from app.providers.mock.aws import MockAWSProvider
from app.providers.mock.azure import MockAzureProvider
from app.providers.mock.gcp import MockGCPProvider
from app.providers.mock.oci import MockOCIProvider
from app.providers.mock.snmp import MockSNMPProvider
from app.security import hash_password
from app.services.devices import run_device_discovery
from app.services.discovery import run_discovery
from app.config import settings

# (provider name, mock provider class, a plausible default region for the
# cloud_accounts row). One entry per cloud the product spec names — see
# providers/mock/README.md for why each one's demo data looks the way it does.
_CLOUD_PROVIDERS = [
    ("aws", MockAWSProvider, "us-east-1"),
    ("azure", MockAzureProvider, "eastus"),
    ("gcp", MockGCPProvider, "us-central1"),
    ("oci", MockOCIProvider, "us-ashburn-1"),
]


def seed() -> None:
    db = SessionLocal()
    try:
        # --- permissions ---
        existing_perms = {p.code: p for p in db.query(Permission).all()}
        for code in ALL_PERMISSION_CODES:
            if code not in existing_perms:
                p = Permission(code=code, description=code.replace(":", " "))
                db.add(p)
                existing_perms[code] = p
        db.commit()

        # --- roles + grants ---
        existing_roles = {r.name: r for r in db.query(Role).all()}
        for name in ALL_ROLES:
            if name not in existing_roles:
                r = Role(name=name, description=name.replace("_", " ").title())
                db.add(r)
                existing_roles[name] = r
        db.commit()

        for role_name, codes in ROLE_GRANTS.items():
            role = existing_roles[role_name]
            granted_codes = {p.code for p in role.permissions}
            for code in codes:
                if code not in granted_codes:
                    role.permissions.append(existing_perms[code])
        db.commit()

        # --- admin user ---
        admin = db.query(User).filter(User.email == settings.seed_admin_email).first()
        if not admin:
            admin = User(
                email=settings.seed_admin_email, full_name="NetSphere Admin",
                hashed_password=hash_password(settings.seed_admin_password), is_active=True,
            )
            admin.roles.append(existing_roles["SUPER_ADMIN"])
            db.add(admin)
            db.commit()
            if settings.is_production:
                print(f"seeded admin user: {settings.seed_admin_email} (password from SEED_ADMIN_PASSWORD)")
            else:
                print(f"seeded admin user: {settings.seed_admin_email} / {settings.seed_admin_password}")
        else:
            print(f"admin user already exists: {settings.seed_admin_email}")

        # --- demo org hierarchy + cloud accounts (for the AWS mock provider) ---
        org = db.query(Organization).filter(Organization.name == "Agentic Humans (Demo)").first()
        if not settings.seed_demo_data:
            print("SEED_DEMO_DATA=false: skipping demo org + mock discovery")
        elif not org:
            org = Organization(name="Agentic Humans (Demo)")
            db.add(org)
            db.commit()

            bu = BusinessUnit(organization_id=org.id, name="Cloud Network Security")
            db.add(bu)
            db.commit()

            env = Environment(business_unit_id=bu.id, name="prod")
            db.add(env)
            db.commit()

            cloud_accounts = []  # (provider_name, ProviderClass, CloudAccount row)
            for provider_name, provider_cls, default_region in _CLOUD_PROVIDERS:
                for account_id in provider_cls.demo_accounts():
                    ca = CloudAccount(
                        environment_id=env.id, provider=provider_name, account_identifier=account_id,
                        region_default=default_region, credential_ref=None, status="active",
                    )
                    db.add(ca)
                    cloud_accounts.append((provider_name, provider_cls, ca))
            db.commit()
            print(f"seeded demo org hierarchy + {len(cloud_accounts)} mock cloud accounts across {len(_CLOUD_PROVIDERS)} providers")

            # Auto-run mock discovery for each seeded account so a fresh
            # `docker compose up` shows real networks/subnets in the
            # Dashboard/IPAM immediately, not just empty cloud-account
            # rows waiting on a manual `POST /discovery/{provider}` call.
            # This is safe and deterministic (no real credentials or
            # network calls involved) -- see providers/mock/*.py.
            for provider_name, provider_cls, ca in cloud_accounts:
                provider = provider_cls(account_identifier=ca.account_identifier, region=ca.region_default)
                result = run_discovery(db, provider, ca.id)
                print(f"  discovered {provider_name}/{ca.account_identifier}: {result}")

            # Same idea, for the device/interface side of Phase 2: seed the
            # on-prem inventory demo data into the same "prod" environment
            # via the mock SNMP provider, so Network Inventory isn't empty
            # either. Safe/deterministic — see providers/mock/snmp.py.
            device_result = run_device_discovery(db, MockSNMPProvider(), env.id)
            print(f"  discovered devices: {device_result}")
        else:
            print("demo org hierarchy already exists")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
