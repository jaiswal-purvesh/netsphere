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


def test_update_network_cidr_name_firewall_environment(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    network = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-edit", "cidr": "10.110.0.0/16", "provider": "aws"},
    ).json()
    network_id = network["id"]
    assert network["firewall"] is None

    resp = client.patch(
        f"/api/v1/ipam/networks/{network_id}", headers=admin_headers,
        json={"cidr": "10.111.0.0/16", "name": "vpc-edit-renamed", "firewall": "fw-prod-01", "environment_name": "prod"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cidr"] == "10.111.0.0/16"
    assert body["name"] == "vpc-edit-renamed"
    assert body["firewall"] == "fw-prod-01"
    assert body["environment_name"] == "prod"

    listed = client.get("/api/v1/ipam/networks", headers=admin_headers).json()
    match = next(n for n in listed if n["id"] == network_id)
    assert match["cidr"] == "10.111.0.0/16"
    assert match["firewall"] == "fw-prod-01"


def test_update_network_partial_leaves_other_fields(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    network = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-partial", "cidr": "10.112.0.0/16", "provider": "aws", "firewall": "fw-a"},
    ).json()
    network_id = network["id"]

    resp = client.patch(f"/api/v1/ipam/networks/{network_id}", headers=admin_headers, json={"environment_name": "staging"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["environment_name"] == "staging"
    assert body["firewall"] == "fw-a"  # untouched
    assert body["cidr"] == "10.112.0.0/16"  # untouched


def test_update_network_duplicate_cidr_rejected(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-x", "cidr": "10.113.0.0/16", "provider": "aws"},
    )
    other = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-y", "cidr": "10.114.0.0/16", "provider": "aws"},
    ).json()

    resp = client.patch(f"/api/v1/ipam/networks/{other['id']}", headers=admin_headers, json={"cidr": "10.113.0.0/16"})
    assert resp.status_code == 409


def test_update_network_not_found_404(client, admin_headers):
    resp = client.patch(f"/api/v1/ipam/networks/{uuid.uuid4()}", headers=admin_headers, json={"name": "x"})
    assert resp.status_code == 404


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


def test_create_network_reports_overlap_warning(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-wide-2", "cidr": "10.120.0.0/16", "provider": "aws"},
    )
    resp = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-narrow-2", "cidr": "10.120.5.0/24", "provider": "onprem"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["overlap_warnings"] is not None
    assert len(body["overlap_warnings"]) == 1
    assert body["overlap_warnings"][0]["type"] == "nested"
    assert body["overlap_warnings"][0]["cross_provider"] is True


def test_create_network_no_overlap_reports_null(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    resp = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-lonely", "cidr": "10.121.0.0/16", "provider": "aws"},
    )
    assert resp.json()["overlap_warnings"] is None


def test_update_network_reports_overlap_warning(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-target", "cidr": "10.122.0.0/16", "provider": "aws"},
    )
    other = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-mover", "cidr": "10.123.0.0/24", "provider": "aws"},
    ).json()

    resp = client.patch(f"/api/v1/ipam/networks/{other['id']}", headers=admin_headers, json={"cidr": "10.122.1.0/24"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["overlap_warnings"] is not None
    assert body["overlap_warnings"][0]["type"] == "nested"


def test_network_overlaps_endpoint(client, admin_headers):
    org = client.post("/api/v1/orgs/organizations", headers=admin_headers, json={"name": "OvOrg"}).json()
    bu = client.post("/api/v1/orgs/business-units", headers=admin_headers, json={"organization_id": org["id"], "name": "OvBU"}).json()
    env = client.post("/api/v1/orgs/environments", headers=admin_headers, json={"business_unit_id": bu["id"], "name": "prod"}).json()
    account_a = client.post(
        "/api/v1/orgs/cloud-accounts", headers=admin_headers,
        json={"environment_id": env["id"], "provider": "aws", "account_identifier": "ov-aws-1"},
    ).json()["id"]
    account_b = client.post(
        "/api/v1/orgs/cloud-accounts", headers=admin_headers,
        json={"environment_id": env["id"], "provider": "onprem", "account_identifier": "ov-onprem-1"},
    ).json()["id"]

    a = client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_a, "name": "vpc-a-ov", "cidr": "10.124.0.0/16", "provider": "aws"},
    ).json()
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_b, "name": "vpc-b-ov", "cidr": "10.124.0.0/16", "provider": "onprem"},
    )
    resp = client.get(f"/api/v1/ipam/networks/{a['id']}/overlaps", headers=admin_headers)
    assert resp.status_code == 200
    conflicts = resp.json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "duplicate"


def test_network_overlaps_endpoint_404(client, admin_headers):
    resp = client.get(f"/api/v1/ipam/networks/{uuid.uuid4()}/overlaps", headers=admin_headers)
    assert resp.status_code == 404


def test_export_networks_csv(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-export", "cidr": "10.130.0.0/16", "provider": "aws", "firewall": "fw-x"},
    )
    resp = client.get("/api/v1/ipam/networks/export", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.text
    assert "cidr" in body.splitlines()[0]
    assert "10.130.0.0/16" in body
    assert "fw-x" in body


def test_import_networks_csv_creates_and_updates(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    # First row creates a new network; second row (re-imported later) updates it.
    csv_text = (
        "cloud_account_id,account_identifier,provider,cidr,name,region,owner_team,business_unit_name,"
        "environment_name,vrf,vlan,firewall,status,notes\n"
        f"{account_id},,aws,10.140.0.0/16,vpc-imported,us-east-1,netops,,prod,,,fw-import-01,active,from csv\n"
    )
    resp = client.post(
        "/api/v1/ipam/networks/import", headers=admin_headers,
        files={"file": ("networks.csv", csv_text, "text/csv")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1
    assert body["updated"] == 0
    assert body["errors"] == 0
    assert body["rows"][0]["status"] == "created"

    listed = client.get("/api/v1/ipam/networks", headers=admin_headers).json()
    match = next(n for n in listed if n["cidr"] == "10.140.0.0/16")
    assert match["firewall"] == "fw-import-01"
    assert match["environment_name"] == "prod"

    # Re-import the same CIDR with a changed firewall -> update, not a duplicate error.
    csv_text_2 = csv_text.replace("fw-import-01", "fw-import-02")
    resp2 = client.post(
        "/api/v1/ipam/networks/import", headers=admin_headers,
        files={"file": ("networks.csv", csv_text_2, "text/csv")},
    )
    body2 = resp2.json()
    assert body2["created"] == 0
    assert body2["updated"] == 1
    listed2 = client.get("/api/v1/ipam/networks", headers=admin_headers).json()
    match2 = next(n for n in listed2 if n["cidr"] == "10.140.0.0/16")
    assert match2["firewall"] == "fw-import-02"


def test_import_networks_csv_by_provider_and_account_identifier(client, admin_headers):
    org = client.post("/api/v1/orgs/organizations", headers=admin_headers, json={"name": "ImportOrg"}).json()
    bu = client.post("/api/v1/orgs/business-units", headers=admin_headers, json={"organization_id": org["id"], "name": "ImportBU"}).json()
    env = client.post("/api/v1/orgs/environments", headers=admin_headers, json={"business_unit_id": bu["id"], "name": "prod"}).json()
    client.post(
        "/api/v1/orgs/cloud-accounts", headers=admin_headers,
        json={"environment_id": env["id"], "provider": "azure", "account_identifier": "sub-import-test"},
    )
    csv_text = (
        "cloud_account_id,account_identifier,provider,cidr,name\n"
        ",sub-import-test,azure,172.30.0.0/16,vnet-by-identifier\n"
    )
    resp = client.post(
        "/api/v1/ipam/networks/import", headers=admin_headers,
        files={"file": ("networks.csv", csv_text, "text/csv")},
    )
    body = resp.json()
    assert body["created"] == 1
    assert body["rows"][0]["status"] == "created"


def test_import_networks_csv_reports_row_errors_without_aborting_batch(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    csv_text = (
        "cloud_account_id,cidr,name\n"
        f"{account_id},not-a-cidr,bad-row\n"
        f"{account_id},10.150.0.0/16,good-row\n"
    )
    resp = client.post(
        "/api/v1/ipam/networks/import", headers=admin_headers,
        files={"file": ("networks.csv", csv_text, "text/csv")},
    )
    body = resp.json()
    assert body["created"] == 1
    assert body["errors"] == 1
    assert body["rows"][0]["status"] == "error"
    assert body["rows"][1]["status"] == "created"
    listed = client.get("/api/v1/ipam/networks", headers=admin_headers).json()
    assert any(n["cidr"] == "10.150.0.0/16" for n in listed)


def test_import_networks_csv_missing_required_column_400(client, admin_headers):
    resp = client.post(
        "/api/v1/ipam/networks/import", headers=admin_headers,
        files={"file": ("networks.csv", "provider,region\naws,us-east-1\n", "text/csv")},
    )
    assert resp.status_code == 400


def test_import_networks_csv_flags_overlap_without_blocking(client, admin_headers):
    account_id = _bootstrap_cloud_account(client, admin_headers)
    client.post(
        "/api/v1/ipam/networks", headers=admin_headers,
        json={"cloud_account_id": account_id, "name": "vpc-existing-wide", "cidr": "10.160.0.0/16", "provider": "aws"},
    )
    csv_text = (
        "cloud_account_id,cidr,name,provider\n"
        f"{account_id},10.160.1.0/24,vpc-imported-overlap,onprem\n"
    )
    resp = client.post(
        "/api/v1/ipam/networks/import", headers=admin_headers,
        files={"file": ("networks.csv", csv_text, "text/csv")},
    )
    body = resp.json()
    assert body["created"] == 1
    row = body["rows"][0]
    assert row["overlap_warnings"]
    assert row["overlap_warnings"][0]["type"] == "nested"


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
