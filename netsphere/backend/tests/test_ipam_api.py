import uuid


def _bootstrap_cloud_account(client, headers) -> str:
    org = client.post("/api/v1/orgs/organizations", headers=headers, json={"name": "TestOrg"}).json()
    bu = client.post("/api/v1/orgs/business-units", headers=headers, json={"organization_id": org["id"], "name": "TestBU"}).json()
    env = client.post("/api/v1/orgs/environments", headers=headers, json={"business_unit_id": bu["id"], "name": "prod"}).json()
    acct = client.post(
        "/api/v1/orgs/cloud-accounts", headers=headers,
        json={"environment_id": env["id"], "provider": "aws", "account_identifier": "999999999999"},
    ).json()
    return acct["id"]


def test_create_network_and_search_ip(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    resp = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-test", "cidr": "10.50.0.0/16", "provider": "aws"},
    )
    assert resp.status_code == 201
    network = resp.json()
    assert network["cidr"] == "10.50.0.0/16"

    search = client.get("/api/v1/ipam/search", headers=admin_headers, params={"ip": "10.50.1.1"}).json()
    assert search["best_match"]["cidr"] == "10.50.0.0/16"


def test_duplicate_network_same_account_rejected(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    body = {"cloud_account_id": account_id, "name": "vpc-a", "cidr": "10.60.0.0/16", "provider": "aws"}
    first = client.post("/api/v1/ipam/networks", headers=admin_headers, json=body)
    assert first.status_code == 201
    second = client.post("/api/v1/ipam/networks", headers=admin_headers, json={**body, "name": "vpc-a-dup"})
    assert second.status_code == 409


def test_invalid_cidr_rejected(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    resp = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "bad", "cidr": "not-a-cidr", "provider": "aws"},
    )
    assert resp.status_code == 400


def test_allocate_subnet_skips_occupied_space(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    network = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-alloc", "cidr": "10.70.0.0/16", "provider": "aws"},
    ).json()
    network_id = network["id"]

    first = client.post(
        f"/api/v1/ipam/networks/{network_id}/allocate", headers=admin_headers, json={"hosts": 50},
    )
    assert first.status_code == 201
    assert first.json()["cidr"] == "10.70.0.0/26"

    second = client.post(
        f"/api/v1/ipam/networks/{network_id}/allocate", headers=admin_headers, json={"hosts": 10},
    )
    assert second.status_code == 201
    assert second.json()["cidr"] == "10.70.0.64/28"

    subnets = client.get(f"/api/v1/ipam/networks/{network_id}/subnets", headers=admin_headers).json()
    assert len(subnets) == 2


def test_allocate_preview_does_not_write(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    network = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-preview", "cidr": "10.80.0.0/24", "provider": "aws"},
    ).json()
    network_id = network["id"]

    preview = client.get(
        f"/api/v1/ipam/networks/{network_id}/allocate/preview", headers=admin_headers, params={"hosts": 10},
    )
    assert preview.status_code == 200
    assert preview.json()["suggested_cidr"] == "10.80.0.0/28"

    subnets = client.get(f"/api/v1/ipam/networks/{network_id}/subnets", headers=admin_headers).json()
    assert subnets == []  # preview must not have written anything


def test_allocate_no_room_returns_409_with_free_space(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    network = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-tiny", "cidr": "10.90.0.0/30", "provider": "aws"},
    ).json()
    network_id = network["id"]

    resp = client.post(f"/api/v1/ipam/networks/{network_id}/allocate", headers=admin_headers, json={"hosts": 100})
    assert resp.status_code == 409
    assert "free" in resp.json()["detail"]


def test_overlap_detection_flags_undeclared_overlap(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-wide", "cidr": "10.100.0.0/16", "provider": "aws"},
    )
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-narrow-onprem-mirror", "cidr": "10.100.5.0/24", "provider": "onprem"},
    )
    conflicts = client.get("/api/v1/ipam/overlaps", headers=admin_headers).json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "nested"
    assert conflicts[0]["cross_provider"] is True


def test_discovery_endpoint_ingests_mock_aws_data(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    resp = client.post(
        f"/api/v1/discovery/aws?cloud_account_id={account_id}&account_identifier=999999999999",
        headers=admin_headers,
    )
    # The bootstrap account id (999999999999) isn't in the mock's demo
    # account list, so discovery legitimately finds nothing for it — this
    # asserts the endpoint runs cleanly end-to-end, not that demo data
    # magically appears for an arbitrary account id.
    assert resp.status_code == 200
    assert resp.json()["networks_discovered"] == 0


def test_discovery_unknown_provider_returns_404(client, admin_headers):
    resp = client.post(f"/api/v1/discovery/not-a-real-cloud?cloud_account_id={uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


def test_discovery_azure_ingests_mock_demo_data(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    resp = client.post(
        f"/api/v1/discovery/azure?cloud_account_id={account_id}&account_identifier=a1b2c3d4-0001-4000-8000-000000000001",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["networks_discovered"] == 2  # subscription 0 has 2 VNets in the mock demo data
    assert body["subnets_created"] == 6


def test_discovery_gcp_ingests_mock_demo_data(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    resp = client.post(
        f"/api/v1/discovery/gcp?cloud_account_id={account_id}&account_identifier=netsphere-demo-prod",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["networks_discovered"] == 2  # project 0 has 2 VPCs
    assert body["subnets_created"] == 6  # 3 + 3 subnets


def test_discovery_oci_ingests_mock_demo_data(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    resp = client.post(
        "/api/v1/discovery/oci?cloud_account_id="
        f"{account_id}&account_identifier=ocid1.compartment.oc1..demoprod",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["networks_discovered"] == 2  # compartment 0 has 2 VCNs
    assert body["subnets_created"] == 6  # 3 + 3 subnets


def test_discovery_all_four_clouds_match_documented_demo_totals(client, admin_headers):
    # Sanity-checks the full "*" sweep for each provider against the exact
    # counts providers/mock/README.md documents, so a future edit to the
    # demo data that silently drifts from the documented numbers fails a
    # test instead of just being wrong in the docs.
    account_id = _bootstrap_cloud_account(client, admin_headers)
    expectations = {
        "aws": (5, 15),
        "azure": (4, 12),
        "gcp": (4, 10),
        "oci": (3, 8),
    }
    for provider, (networks, subnets) in expectations.items():
        resp = client.post(
            f"/api/v1/discovery/{provider}?cloud_account_id={account_id}&account_identifier=*",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["networks_discovered"] == networks, provider
        assert body["subnets_created"] == subnets, provider
