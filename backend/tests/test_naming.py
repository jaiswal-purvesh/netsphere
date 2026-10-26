"""Naming standard: generator, validator, audit and access control."""
from __future__ import annotations

import pytest


def _gen(client, headers, **body):
    r = client.post("/api/v1/naming/generate", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _val(client, headers, name, component, provider=None):
    r = client.post("/api/v1/naming/validate", headers=headers,
                    json={"name": name, "component": component, "provider": provider})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("provider,expected_type", [("aws", "vpc"), ("azure", "vnet"), ("gcp", "vpc"), ("oci", "vcn")])
def test_network_type_segment_follows_the_provider(client, admin_headers, provider, expected_type):
    region = {"aws": "us-east-1", "azure": "eastus", "gcp": "us-central1", "oci": "us-ashburn-1"}[provider]
    out = _gen(client, admin_headers, component="network", provider=provider, env="prd", region=region, app="Payments")
    assert out["issues"] == []
    assert out["parts"]["type"] == expected_type
    assert out["name"].startswith(f"bfl-prd-") and out["name"].endswith("-payments-01")


def test_region_name_is_resolved_to_its_short_code(client, admin_headers):
    out = _gen(client, admin_headers, component="subnet", provider="oci", env="prd", region="uk-london-1", app="core")
    assert out["parts"]["region"] == "lhr"
    assert out["name"] == "bfl-prd-lhr-snet-core-01"


def test_application_may_carry_a_tier(client, admin_headers):
    out = _gen(client, admin_headers, component="subnet", provider="aws", env="prd", region="use1", app="Payments Web")
    assert out["parts"]["app"] == "payments-web"
    assert _val(client, admin_headers, out["name"], "subnet", "aws")["compliant"] is True


def test_missing_inputs_are_all_reported_at_once(client, admin_headers):
    out = _gen(client, admin_headers, component="network", provider="gcp", env="qa", region="", app="")
    assert out["name"] is None
    assert len(out["issues"]) == 3


def test_unknown_component_and_provider(client, admin_headers):
    assert _gen(client, admin_headers, component="toaster")["name"] is None
    assert _gen(client, admin_headers, component="network", provider="ibm", env="prd", region="x1", app="a")["name"] is None


def test_sequence_skips_names_already_in_the_inventory(client, admin_headers):
    org = client.post("/api/v1/orgs/organizations", headers=admin_headers, json={"name": "O"}).json()
    bu = client.post("/api/v1/orgs/business-units", headers=admin_headers, json={"organization_id": org["id"], "name": "B"}).json()
    env = client.post("/api/v1/orgs/environments", headers=admin_headers, json={"business_unit_id": bu["id"], "name": "prod"}).json()
    client.post(f"/api/v1/discovery/snmp?environment_id={env['id']}", headers=admin_headers)  # creates dc2-edge-rtr-01

    nxt = _gen(client, admin_headers, component="device", site="dc2", role="edge", kind="router")
    assert nxt["name"] == "dc2-edge-rtr-02" and nxt["unique"] is True

    forced = _gen(client, admin_headers, component="device", site="dc2", role="edge", kind="router", seq=1)
    assert forced["unique"] is False
    assert forced["collisions"][0]["name"] == "dc2-edge-rtr-01"
    assert any("already in use" in i for i in forced["issues"])


def test_collision_check_is_case_insensitive_and_scoped_to_the_component(client, admin_headers):
    # a firewall named like an existing router must not collide: different {type}
    out = _gen(client, admin_headers, component="device", site="dc2", role="edge", kind="firewall")
    assert out["name"] == "dc2-edge-fw-01"


@pytest.mark.parametrize("name,component,provider,ok", [
    ("bfl-prd-use1-vpc-payments-01", "network", "aws", True),
    ("bfl-prd-eus-vnet-payments-01", "network", "azure", True),
    ("bfl-prd-eus-vpc-payments-01", "network", "azure", False),     # wrong type for the cloud
    ("bfl-qa-use1-vpc-payments-01", "network", "aws", False),       # unknown environment
    ("bfl-prd-use1-vpc-payments", "network", "aws", False),         # no sequence
    ("BFL-PRD-USE1-VPC-PAYMENTS-01", "network", "aws", False),      # upper case
    ("bfl_prd_use1_vpc_payments_01", "network", "aws", False),      # underscores
    ("dc1-core-rtr-01", "device", None, True),
    ("core-rtr-01", "device", None, False),
    ("dc1-vrf-payments", "vrf", None, True),
])
def test_validate(client, admin_headers, name, component, provider, ok):
    assert _val(client, admin_headers, name, component, provider)["compliant"] is ok


def test_provider_hard_limits_apply_on_top_of_the_convention(client, admin_headers):
    long_app = "a" * 60
    out = _gen(client, admin_headers, component="network", provider="azure", env="prd", region="eus", app=long_app)
    assert any("at most 64" in i for i in out["issues"])           # Azure length cap
    gcp = _val(client, admin_headers, "1-starts-with-digit", "network", "gcp")
    assert gcp["compliant"] is False and any("GCP" in i for i in gcp["issues"])


def test_validate_explains_which_segment_is_wrong(client, admin_headers):
    out = _val(client, admin_headers, "bfl-prd-eus-vpc-payments-01", "network", "azure")
    assert any("should be 'vnet'" in i for i in out["issues"])


def test_audit_scores_the_inventory_and_suggests_replacements(client, admin_headers):
    org = client.post("/api/v1/orgs/organizations", headers=admin_headers, json={"name": "O"}).json()
    bu = client.post("/api/v1/orgs/business-units", headers=admin_headers, json={"organization_id": org["id"], "name": "B"}).json()
    env = client.post("/api/v1/orgs/environments", headers=admin_headers, json={"business_unit_id": bu["id"], "name": "prod"}).json()
    client.post(f"/api/v1/discovery/snmp?environment_id={env['id']}", headers=admin_headers)

    audit = client.get("/api/v1/naming/audit", headers=admin_headers).json()
    assert audit["total"] == audit["compliant"] + audit["non_compliant"]
    devices = next(s for s in audit["sections"] if s["component"] == "device")
    by_name = {i["name"]: i for i in devices["items"]}
    assert by_name["dc2-edge-rtr-01"]["compliant"] is True
    assert by_name["dc2-edge-rtr-01"]["suggestion"] is None          # compliant names get no suggestion
    assert by_name["core-rtr-01"]["compliant"] is False
    assert by_name["core-rtr-01"]["suggestion"] == "dc1-core-rtr-01"


def test_spec_lists_every_component_with_scope(client, admin_headers):
    spec = client.get("/api/v1/naming/spec", headers=admin_headers).json()
    scopes = {c["scope"] for c in spec["components"]}
    assert scopes == {"cloud", "onprem"}
    assert {"network", "subnet", "device", "vrf"} <= {c["id"] for c in spec["components"]}
    assert spec["rules"]


def test_access_follows_inventory_view_permission(client, auth_headers_factory):
    ro, _ = auth_headers_factory("READ_ONLY")
    assert client.get("/api/v1/naming/spec", headers=ro).status_code == 200
    nobody, _ = auth_headers_factory("NO_SUCH_ROLE", email="nobody@test.local")   # no roles at all
    assert client.get("/api/v1/naming/spec", headers=nobody).status_code == 403
    assert client.post("/api/v1/naming/generate", headers=nobody, json={"component": "network"}).status_code == 403
    assert client.get("/api/v1/naming/spec").status_code == 401
