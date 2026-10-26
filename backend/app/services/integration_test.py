"""'Test connection' calls for each integration vendor — a lightweight,
read-only reachability + auth check so an engineer saving a key on the
Integrations page finds out immediately if it's wrong, rather than at
execution time. This deliberately does NOT touch policy/config; it's the
same spirit as the design doc's canary check (§4.4) but synchronous and
on-demand.

Each function returns (ok, message). Never raises — a bad host, TLS
failure, wrong key, or timeout is a normal, expected outcome here, not a
bug, so every httpx exception is caught and turned into a message.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

TIMEOUT = httpx.Timeout(8.0)


def test_panos(host: str, port: int, verify_tls: bool, api_key: str) -> tuple[bool, str]:
    """Shared by 'panorama' and 'pan_os' (PA-5260) — both speak the same
    PAN-OS XML API. <show><system><info> is read-only and cheap."""
    url = f"https://{host}:{port}/api/"
    params = {"type": "op", "cmd": "<show><system><info/></show>", "key": api_key}
    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT, verify=verify_tls)
    except httpx.TimeoutException:
        return False, f"Timed out connecting to {host}:{port}"
    except httpx.ConnectError as e:
        return False, f"Could not connect to {host}:{port}: {e}"
    except httpx.HTTPError as e:
        return False, f"Request failed: {e}"

    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code} from {host}:{port}"

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return False, "Unexpected response (not the PAN-OS XML API — check host/port)"

    status = root.attrib.get("status")
    if status == "success":
        model = root.findtext(".//model") or ""
        sw = root.findtext(".//sw-version") or ""
        hostname = root.findtext(".//hostname") or host
        detail = " ".join(p for p in [hostname, model, sw] if p)
        return True, f"Connected — {detail}".strip()

    msg = root.findtext(".//msg") or root.findtext(".//line") or "authentication failed"
    return False, f"PAN-OS API error: {msg}"


def test_fortigate(host: str, port: int, verify_tls: bool, api_token: str) -> tuple[bool, str]:
    """FortiOS REST API — GET /api/v2/monitor/system/status with the token
    as a bearer credential (also accepted as ?access_token= by older
    FortiOS releases; the header form is tried first)."""
    url = f"https://{host}:{port}/api/v2/monitor/system/status"
    try:
        resp = httpx.get(
            url, timeout=TIMEOUT, verify=verify_tls,
            headers={"Authorization": f"Bearer {api_token}"},
        )
        if resp.status_code in (401, 403):
            # Some FortiOS versions only honor the query-param form.
            resp = httpx.get(url, params={"access_token": api_token}, timeout=TIMEOUT, verify=verify_tls)
    except httpx.TimeoutException:
        return False, f"Timed out connecting to {host}:{port}"
    except httpx.ConnectError as e:
        return False, f"Could not connect to {host}:{port}: {e}"
    except httpx.HTTPError as e:
        return False, f"Request failed: {e}"

    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError:
            return True, "Connected"
        results = data.get("results") or {}
        version = results.get("version") or ""
        hostname = results.get("hostname") or host
        return True, f"Connected — {hostname} {version}".strip()
    if resp.status_code in (401, 403):
        return False, "Authentication failed — check the API token"
    return False, f"HTTP {resp.status_code} from {host}:{port}"
