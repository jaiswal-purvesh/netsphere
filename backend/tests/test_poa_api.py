"""Tests for the Automation module's POA (Plan of Action) generator, ported
from the standalone RITM-POA tool. Uses small synthetic reference/input data
constructed in-test rather than the uploaded tool's real BFL/Bajaj production
inventories, so no customer data ends up in the repo."""
from __future__ import annotations

import io

from openpyxl import Workbook


def _xlsx_bytes(rows: list[dict], sheet_name: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([row[h] for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


RITM_CSV = (
    b"Source IP,Destination IP,Destination Port\n"
    b"10.10.10.5,10.20.20.5,443\n"
    b"10.10.10.6,badvalue,22\n"
)


def test_reference_files_start_empty(client, admin_headers):
    resp = client.get("/api/v1/automation/poa/reference-files", headers=admin_headers)
    assert resp.status_code == 200
    kinds = resp.json()
    assert len(kinds) == 7
    assert all(k["uploaded"] is False for k in kinds)


def test_upload_and_replace_reference_file(client, admin_headers):
    content = _xlsx_bytes(
        [{"CIDR": "10.20.0.0/16", "Firewall": "BFL-OCI-MUM-PROD-DG", "Name": "test", "Environment": "OCI"}],
        sheet_name="CIDR_Firewall_Inventory",
    )
    resp = client.put(
        "/api/v1/automation/poa/reference-files/cidr_firewall_inventory",
        headers=admin_headers,
        files={"file": ("cidr_firewall.xlsx", content, "application/octet-stream")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["uploaded"] is True
    assert body["filename"] == "cidr_firewall.xlsx"

    listing = client.get("/api/v1/automation/poa/reference-files", headers=admin_headers).json()
    row = next(k for k in listing if k["kind"] == "cidr_firewall_inventory")
    assert row["uploaded"] is True
    assert row["size_bytes"] == len(content)

    delete = client.delete("/api/v1/automation/poa/reference-files/cidr_firewall_inventory", headers=admin_headers)
    assert delete.status_code == 204
    listing_after = client.get("/api/v1/automation/poa/reference-files", headers=admin_headers).json()
    row_after = next(k for k in listing_after if k["kind"] == "cidr_firewall_inventory")
    assert row_after["uploaded"] is False


def test_unknown_reference_kind_404s(client, admin_headers):
    resp = client.put(
        "/api/v1/automation/poa/reference-files/not_a_real_kind",
        headers=admin_headers,
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 404


def test_run_with_no_reference_files_falls_back_to_onprem(client, admin_headers):
    """With no reference inventories uploaded at all, every IP should be
    classified on-prem/unclassified and firewall legs fall back to the
    'Onprem Firewall' label rather than MANUAL — matching the original
    tool's documented fallback behaviour."""
    resp = client.post(
        "/api/v1/automation/poa/runs",
        headers=admin_headers,
        data={"ritm_number": "RITM9999999"},
        files={"input_file": ("RITM9999999.csv", RITM_CSV, "text/csv")},
    )
    assert resp.status_code == 201
    run = resp.json()
    assert run["ritm_number"] == "RITM9999999"
    assert run["row_count"] == 2
    assert run["invalid_count"] == 1  # the "badvalue" destination row

    rows = run["rows"]
    good_row = next(r for r in rows if r["Source IP"] == "10.10.10.5")
    assert good_row["Source Firewall Name"] == "Onprem Firewall"
    assert good_row["Destination Firewall Name"] == "Onprem Firewall"
    assert good_row["Firewall Whitelisting"] == "Yes"
    assert good_row["Routing Availibility"].startswith("To Be Verified")

    bad_row = next(r for r in rows if r["Source IP"] == "10.10.10.6")
    assert bad_row["Input Validation"] == "Destination IP is not a valid IP or CIDR"
    assert bad_row["Routing Availibility"] == "NOT A VALID IP/CIDR"

    run_id = run["id"]
    detail = client.get(f"/api/v1/automation/poa/runs/{run_id}", headers=admin_headers)
    assert detail.status_code == 200
    assert detail.json()["row_count"] == 2

    listing = client.get("/api/v1/automation/poa/runs", headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    excel = client.get(f"/api/v1/automation/poa/runs/{run_id}/excel", headers=admin_headers)
    assert excel.status_code == 200
    assert excel.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert excel.content[:2] == b"PK"  # xlsx is a zip archive

    docx = client.get(f"/api/v1/automation/poa/runs/{run_id}/docx", headers=admin_headers)
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"  # docx is a zip archive too


def test_run_uses_uploaded_reference_files_for_oci_destination(client, admin_headers):
    inventory = _xlsx_bytes([{
        "Subnet_CIDR": "10.20.20.0/24", "Subnet_Name": "app-subnet", "VCN_Name": "prod-vcn",
        "VCN_CIDR": "10.20.0.0/16", "Compartment_Name": "prod", "Region": "ap-mumbai-1",
        "Route_Table": "rt-1", "Security_Lists": "app-sl", "NSG_Count": 0,
    }])
    up = client.put(
        "/api/v1/automation/poa/reference-files/oci_prod_inventory",
        headers=admin_headers,
        files={"file": ("oci_prod.xlsx", inventory, "application/octet-stream")},
    )
    assert up.status_code == 200

    resp = client.post(
        "/api/v1/automation/poa/runs",
        headers=admin_headers,
        data={"ritm_number": "RITM8888888"},
        files={"input_file": ("RITM8888888.csv", RITM_CSV, "text/csv")},
    )
    assert resp.status_code == 201
    good_row = next(r for r in resp.json()["rows"] if r["Source IP"] == "10.10.10.5")
    assert good_row["DST Subnet Name"] == "app-subnet"
    assert good_row["Whitelisting Required at OCI"] == "Yes"


def test_run_requires_automation_execute_permission(client, auth_headers_factory):
    headers, _ = auth_headers_factory("AUDITOR")  # automation:view only, no execute
    resp = client.post(
        "/api/v1/automation/poa/runs",
        headers=headers,
        data={"ritm_number": "RITM7777777"},
        files={"input_file": ("RITM7777777.csv", RITM_CSV, "text/csv")},
    )
    assert resp.status_code == 403

    listing = client.get("/api/v1/automation/poa/reference-files", headers=headers)
    assert listing.status_code == 200  # AUDITOR does have automation:view


def test_run_rejects_empty_input_file(client, admin_headers):
    resp = client.post(
        "/api/v1/automation/poa/runs",
        headers=admin_headers,
        data={"ritm_number": "RITM6666666"},
        files={"input_file": ("empty.csv", b"", "text/csv")},
    )
    assert resp.status_code == 400
