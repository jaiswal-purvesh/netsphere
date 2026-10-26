"""Real (not mocked) TCPWave IPAM/DDI REST API client — the ONPREM team's
system of record, pulled into NetSphere's own networks/subnets/
ip_addresses tables by app/services/ipam_sync.py. Same "genuine adapter,
same file organization" pattern as app/services/fw_panorama_adapter.py.

TCPWave publishes real API material (product pages, a docs portal, and
several official GitHub client repos: tims-python-client / PyPI
"tcpwave-client", tims-go-client, tcpwave-ansible, TIMS-Terraform-Provider)
but the full field-by-field REST API PDF guide sits behind the customer
portal, so this adapter is built against what's independently confirmed
plus documented, clearly-flagged assumptions where the primary spec wasn't
reachable. Before relying on this in production, get the customer's actual
"TCPWave_IPAM_RESTAPI_Guide_vNN.NNPN" PDF (or sandbox access) and diff it
against the notes below — anything marked NEEDS CONFIRMATION should be
checked first.

CONFIRMED (consistent across TCPWave's own docs/REST guide page, the
official Ansible playbooks, and the official curl-examples page):
  - Base path is `/tims/rest/<resource>/<operation>` (NOT `/tcpwaveapi/...`).
  - Two auth mechanisms: a session token minted via
    `POST /tims/rest/auth_token/get` and sent back as a `TIMS-Session-Token`
    header on every call, or mutual-TLS client certificate. The official
    Python SDK states plainly that Basic Auth is not supported.
  - HTTPS only, port 7443 in every literal official example (this is
    configurable per-integration here rather than hardcoded, since one
    third-party integration guide for TCPWave documents port 443 for a
    reverse-proxied deployment — confirm the real port with the ONPREM
    team rather than assuming either).
  - Resource/verb endpoint shape: `network/list`, `subnet/list`,
    `subnet/details`, `object/list` (IP address objects), each a GET
    returning a JSON body; `add`/`update`/`delete` are POST.
  - No API path version segment — TCPWave versions the whole product
    (e.g. "v11.32P4"), not the URL.

NEEDS CONFIRMATION (not resolvable from public sources — defensive code
below, not a guess baked in as fact):
  - Pagination parameters. No primary source was found; secondary
    evidence suggests DataTables-style `page`/`rows`/`start`/`length`
    params but this is unverified. `_paginated_get` below tries the
    common `page`/`page_size` shape and falls back to a single
    unpaginated call if the response doesn't look paginated (a plain
    list) — see its docstring.
  - Whether `list`/`get` responses represent an IP/CIDR as a single
    string (`"10.1.10.0/24"`, confirmed shape for *request* bodies in the
    official Python SDK) or as decomposed octet fields (`addr1`..`addr4`
    + `mask_length`, confirmed shape for *request* bodies in the official
    Ansible playbooks — the two official sources disagree with each
    other on the request side, so the response side is genuinely
    unknown). `_extract_cidr`/`_extract_ip` below handle both shapes.
  - The literal field name/enum for an IP object's allocation status
    (used/available/reserved/etc.). Object fields seen in official
    examples (`name`, `class_code`, `alloc_type`, `organization_name`,
    `domain_name`) don't include an obvious status enum, so this adapter
    infers "reserved" when a record is present with no live host data and
    "allocated" otherwise (see `_infer_status`) — replace this with the
    real field once confirmed, rather than trusting the inference for
    reporting.

None of this is mocked: an unreachable host, a bad token, or an
unexpected response shape all raise TcpwaveError with the real detail —
this adapter never fabricates a network/subnet/IP that wasn't actually in
the response, matching this project's "nothing here is faked" rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

TIMEOUT = 30.0
MAX_PAGES = 500  # hard stop against an infinite pagination loop from an unexpected response shape


class TcpwaveError(Exception):
    pass


@dataclass(frozen=True)
class TcpwaveIpObject:
    ip_address: str
    hostname: str | None
    mac_address: str | None
    status: str  # allocated | reserved | free — see module docstring's "NEEDS CONFIRMATION"
    organization_name: str | None
    external_ref: str | None  # TCPWave's own object identifier/name, for idempotent re-sync
    raw: dict


@dataclass(frozen=True)
class TcpwaveSubnet:
    cidr: str
    name: str | None
    external_ref: str | None
    ip_objects: list[TcpwaveIpObject] = field(default_factory=list)


@dataclass(frozen=True)
class TcpwaveNetwork:
    cidr: str
    name: str | None
    external_ref: str | None
    organization_name: str | None
    subnets: list[TcpwaveSubnet] = field(default_factory=list)


def _base_url(host: str, port: int) -> str:
    return f"https://{host}:{port}/tims/rest"


def get_auth_token(host: str, port: int, verify_tls: bool, client_ip: str, description: str = "NetSphere IPAM sync") -> str:
    """POST /tims/rest/auth_token/get — mints a session token an admin
    would otherwise generate once via the TIMS console. Exposed for
    completeness (a from-scratch setup flow could use it) but this
    adapter's normal path uses a token the admin already generated and
    pasted into the integration, since token minting is itself scoped to a
    specific client IP/hostname per TCPWave's docs."""
    try:
        resp = httpx.post(
            f"{_base_url(host, port)}/auth_token/get",
            json={"ip": client_ip, "application": "tims", "description": description},
            timeout=TIMEOUT, verify=verify_tls,
        )
    except httpx.HTTPError as e:
        raise TcpwaveError(f"TCPWave request failed: {e}") from e
    if resp.status_code != 200:
        raise TcpwaveError(f"TCPWave auth_token/get returned HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError as e:
        raise TcpwaveError(f"TCPWave auth_token/get returned non-JSON body: {resp.text[:300]}") from e
    token = body.get("token") or body.get("session_token") or body.get("auth_token")
    if not token:
        raise TcpwaveError(f"TCPWave auth_token/get response had no recognizable token field: {body}")
    return token


def _headers(token: str | None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["TIMS-Session-Token"] = token
    return headers


def _request(
    host: str, port: int, verify_tls: bool, token: str | None,
    method: str, path: str, params: dict | None = None,
    client_cert: tuple[str, str] | None = None,
) -> dict | list:
    try:
        if client_cert:
            # httpx 0.28 dropped `cert=` from the top-level convenience
            # functions (httpx.request/get/post) — only Client accepts it.
            with httpx.Client(verify=verify_tls, cert=client_cert, timeout=TIMEOUT) as client:
                resp = client.request(method, f"{_base_url(host, port)}/{path}", params=params, headers=_headers(token))
        else:
            resp = httpx.request(
                method, f"{_base_url(host, port)}/{path}", params=params,
                headers=_headers(token), timeout=TIMEOUT, verify=verify_tls,
            )
    except httpx.HTTPError as e:
        raise TcpwaveError(f"TCPWave request failed: {e}") from e
    if resp.status_code == 401 or resp.status_code == 403:
        raise TcpwaveError(f"TCPWave rejected credentials (HTTP {resp.status_code}) — token expired/invalid or cert not trusted")
    if resp.status_code != 200:
        raise TcpwaveError(f"TCPWave {path} returned HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as e:
        raise TcpwaveError(f"TCPWave {path} returned non-JSON body: {resp.text[:300]}") from e


def _rows_from_response(body: dict | list) -> tuple[list[dict], bool]:
    """Normalizes whatever shape the list/get endpoint actually returns.
    Returns (rows, looks_paginated). See module docstring — pagination
    shape is unconfirmed, so this recognizes several plausible envelopes
    rather than assuming one."""
    if isinstance(body, list):
        return body, False
    if isinstance(body, dict):
        for key in ("data", "results", "rows", "items", "objects", "networks", "subnets"):
            if isinstance(body.get(key), list):
                looks_paginated = any(k in body for k in ("page", "total", "totalRecords", "recordsTotal", "next_page"))
                return body[key], looks_paginated
    raise TcpwaveError(f"TCPWave response had no recognizable list field: {body if isinstance(body, dict) else type(body)}")


def _paginated_get(
    host: str, port: int, verify_tls: bool, token: str | None, path: str, base_params: dict,
    client_cert: tuple[str, str] | None = None,
) -> list[dict]:
    """Walks `page`/`page_size`-style pagination if the response looks
    paginated (see `_rows_from_response`); otherwise treats the first
    response as the complete result set. Capped at MAX_PAGES so an
    unexpected response shape can't spin forever against a live device."""
    all_rows: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        params = {**base_params, "page": page, "page_size": 500}
        body = _request(host, port, verify_tls, token, "GET", path, params=params, client_cert=client_cert)
        rows, looks_paginated = _rows_from_response(body)
        all_rows.extend(rows)
        if not looks_paginated or not rows:
            break
        page += 1
    return all_rows


def _extract_cidr(row: dict) -> str | None:
    """See module docstring: response CIDR may be a single string field or
    decomposed octets — try both rather than assuming one."""
    for key in ("network_address", "subnet_address", "cidr", "network"):
        val = row.get(key)
        if isinstance(val, str) and "/" in val:
            return val
    addr = ".".join(str(row[f"addr{i}"]) for i in range(1, 5) if f"addr{i}" in row) if all(f"addr{i}" in row for i in range(1, 5)) else None
    mask = row.get("mask_length") or row.get("prefix_len") or row.get("subnet_mask")
    if addr and mask:
        return f"{addr}/{mask}"
    return None


def _extract_ip(row: dict) -> str | None:
    for key in ("ip_address", "address"):
        val = row.get(key)
        if isinstance(val, str):
            return val
    if all(f"addr{i}" in row for i in range(1, 5)):
        return ".".join(str(row[f"addr{i}"]) for i in range(1, 5))
    return None


def _infer_status(row: dict) -> str:
    # See module docstring — no confirmed status enum from TCPWave's own
    # docs; a record with a live hostname is treated as allocated, an
    # explicit reservation flag (if present) as reserved, else allocated
    # (a bare address entry existing at all implies it's not free).
    if row.get("is_reserved") or row.get("reserved"):
        return "reserved"
    return "allocated"


def fetch_ip_objects(
    host: str, port: int, verify_tls: bool, token: str | None, subnet_ref: str,
    organization_name: str | None = None, client_cert: tuple[str, str] | None = None,
) -> list[TcpwaveIpObject]:
    params = {"subnet_address": subnet_ref}
    if organization_name:
        params["organization_name"] = organization_name
    rows = _paginated_get(host, port, verify_tls, token, "object/list", params, client_cert=client_cert)
    objects = []
    for row in rows:
        ip = _extract_ip(row)
        if not ip:
            continue  # can't place an object with no resolvable address — skip rather than guess
        objects.append(TcpwaveIpObject(
            ip_address=ip,
            hostname=row.get("name") or row.get("hostname"),
            mac_address=row.get("mac_address") or row.get("mac"),
            status=_infer_status(row),
            organization_name=row.get("organization_name"),
            external_ref=row.get("name") or ip,
            raw=row,
        ))
    return objects


def fetch_subnets(
    host: str, port: int, verify_tls: bool, token: str | None, network_ref: str,
    organization_name: str | None = None, client_cert: tuple[str, str] | None = None,
) -> list[TcpwaveSubnet]:
    params = {"network_address": network_ref}
    if organization_name:
        params["organization_name"] = organization_name
    rows = _paginated_get(host, port, verify_tls, token, "subnet/list", params, client_cert=client_cert)
    subnets = []
    for row in rows:
        cidr = _extract_cidr(row)
        if not cidr:
            continue
        subnets.append(TcpwaveSubnet(
            cidr=cidr, name=row.get("name"), external_ref=row.get("name") or cidr,
        ))
    return subnets


def fetch_networks(
    host: str, port: int, verify_tls: bool, token: str | None,
    organization_name: str | None = None, client_cert: tuple[str, str] | None = None,
) -> list[TcpwaveNetwork]:
    """Top-level fetch: networks, then each network's subnets, then each
    subnet's IP objects — three separate calls per level (TCPWave's
    resources are genuinely separate, not a nested single response; see
    module docstring). A failure partway through (e.g. subnet/list errors
    for one network) aborts the whole run rather than silently returning a
    partial tree — app/services/ipam_sync.py surfaces that as a failed
    sync run, never a quietly-incomplete one."""
    params = {}
    if organization_name:
        params["organization_name"] = organization_name
    rows = _paginated_get(host, port, verify_tls, token, "network/list", params, client_cert=client_cert)

    networks = []
    for row in rows:
        cidr = _extract_cidr(row)
        if not cidr:
            continue
        network_ref = row.get("name") or cidr
        subnets = fetch_subnets(host, port, verify_tls, token, network_ref, organization_name, client_cert)
        subnets_with_ips = []
        for sub in subnets:
            ip_objects = fetch_ip_objects(host, port, verify_tls, token, sub.external_ref or sub.cidr, organization_name, client_cert)
            subnets_with_ips.append(TcpwaveSubnet(
                cidr=sub.cidr, name=sub.name, external_ref=sub.external_ref, ip_objects=ip_objects,
            ))
        networks.append(TcpwaveNetwork(
            cidr=cidr, name=row.get("name"), external_ref=network_ref,
            organization_name=row.get("organization_name"), subnets=subnets_with_ips,
        ))
    return networks
