import uuid


def _bootstrap_environment(client, headers) -> str:
    org = client.post("/api/v1/orgs/organizations", headers=headers, json={"name": "TestOrg"}).json()
    bu = client.post("/api/v1/orgs/business-units", headers=headers, json={"organization_id": org["id"], "name": "TestBU"}).json()
    env = client.post("/api/v1/orgs/environments", headers=headers, json={"business_unit_id": bu["id"], "name": "prod"}).json()
    return env["id"]


def test_snmp_discovery_ingests_mock_devices(client, admin_headers):
    env_id = _bootstrap_environment(client, admin_headers)
    resp = client.post(f"/api/v1/discovery/snmp?environment_id={env_id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["devices_discovered"] == 4
    assert body["devices_created"] == 4
    assert body["interfaces_created"] == 8

    devices = client.get("/api/v1/devices", headers=admin_headers).json()
    assert len(devices) == 4
    hostnames = {d["hostname"] for d in devices}
    assert hostnames == {"core-rtr-01", "core-sw-01", "edge-fw-01", "dc2-edge-rtr-01"}


def test_snmp_discovery_is_idempotent(client, admin_headers):
    env_id = _bootstrap_environment(client, admin_headers)
    client.post(f"/api/v1/discovery/snmp?environment_id={env_id}", headers=admin_headers)
    second = client.post(f"/api/v1/discovery/snmp?environment_id={env_id}", headers=admin_headers)
    body = second.json()
    assert body["devices_created"] == 0
    assert body["devices_updated"] == 4
    assert body["interfaces_created"] == 0
    assert body["interfaces_updated"] == 8

    devices = client.get("/api/v1/devices", headers=admin_headers).json()
    assert len(devices) == 4  # re-running never duplicates rows


def test_snmp_discovery_site_filter(client, admin_headers):
    env_id = _bootstrap_environment(client, admin_headers)
    resp = client.post(f"/api/v1/discovery/snmp?environment_id={env_id}&site=dc2", headers=admin_headers)
    assert resp.json()["devices_discovered"] == 1
    devices = client.get("/api/v1/devices", headers=admin_headers).json()
    assert len(devices) == 1
    assert devices[0]["hostname"] == "dc2-edge-rtr-01"


def test_snmp_discovery_unknown_environment_404s(client, admin_headers):
    resp = client.post(f"/api/v1/discovery/snmp?environment_id={uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


def test_interface_gets_ipam_subnet_cross_link(client, admin_headers):
    # Discover the AWS demo networks first so a real subnet exists for
    # core-rtr-01's Gi0/1 (10.10.0.5) to land in.
    org = client.post("/api/v1/orgs/organizations", headers=admin_headers, json={"name": "TestOrg2"}).json()
    bu = client.post("/api/v1/orgs/business-units", headers=admin_headers, json={"organization_id": org["id"], "name": "BU"}).json()
    env = client.post("/api/v1/orgs/environments", headers=admin_headers, json={"business_unit_id": bu["id"], "name": "prod"}).json()
    acct = client.post(
        "/api/v1/orgs/cloud-accounts", headers=admin_headers,
        json={"environment_id": env["id"], "provider": "aws", "account_identifier": "111111111111"},
    ).json()
    client.post(
        f"/api/v1/discovery/aws?cloud_account_id={acct['id']}&account_identifier=111111111111",
        headers=admin_headers,
    )

    client.post(f"/api/v1/discovery/snmp?environment_id={env['id']}", headers=admin_headers)
    devices = client.get("/api/v1/devices", headers=admin_headers).json()
    rtr = next(d for d in devices if d["hostname"] == "core-rtr-01")
    interfaces = client.get(f"/api/v1/devices/{rtr['id']}/interfaces", headers=admin_headers).json()
    uplink = next(i for i in interfaces if i["ip_address"] == "10.10.0.5")
    assert uplink["subnet_id"] is not None


def test_devices_list_requires_inventory_permission(client, auth_headers_factory):
    headers, _ = auth_headers_factory("SECURITY_ENGINEER")  # no inventory grant
    resp = client.get("/api/v1/devices", headers=headers)
    assert resp.status_code == 403


def test_devices_list_allowed_for_network_engineer(client, auth_headers_factory):
    headers, _ = auth_headers_factory("NETWORK_ENGINEER")
    resp = client.get("/api/v1/devices", headers=headers)
    assert resp.status_code == 200
