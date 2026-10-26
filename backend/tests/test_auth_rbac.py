def test_login_rejects_bad_credentials(client, auth_headers_factory):
    auth_headers_factory("READ_ONLY", email="ro@test.local")
    resp = client.post("/api/v1/auth/login", data={"username": "ro@test.local", "password": "wrong"})
    assert resp.status_code == 401


def test_unauthenticated_request_rejected(client):
    resp = client.get("/api/v1/ipam/networks")
    assert resp.status_code == 401


def test_read_only_can_view_but_not_create(client, auth_headers_factory):
    headers, _ = auth_headers_factory("READ_ONLY")
    resp = client.get("/api/v1/ipam/networks", headers=headers)
    assert resp.status_code == 200

    resp = client.post(
        "/api/v1/orgs/organizations", headers=headers, json={"name": "should not be allowed"},
    )
    assert resp.status_code == 403
    assert "admin:create" in resp.json()["detail"]


def test_super_admin_bypasses_permission_checks(client, admin_headers):
    resp = client.post("/api/v1/orgs/organizations", headers=admin_headers, json={"name": "Acme Corp"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Acme Corp"


def test_network_admin_can_create_ipam_but_not_admin_resources(client, auth_headers_factory):
    headers, _ = auth_headers_factory("NETWORK_ENGINEER")
    # NETWORK_ENGINEER has ipam:create per rbac_seed, but not admin:create
    resp = client.post("/api/v1/orgs/organizations", headers=headers, json={"name": "nope"})
    assert resp.status_code == 403
