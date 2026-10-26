"""Real Panorama/PAN-OS execution adapter — Phase 3 of
claude/firewall-policy-automation-design.md's phasing, implementing the
`snapshot / render / preview / apply / poll / verify / rollback` contract
from §3.2 against the PAN-OS XML API (the same API app/services/
integration_test.py's `test_panos` already speaks to, for consistency), for
a single device group at a time.

Known, deliberate simplifications for this phase (documented rather than
silently assumed — revisit before Phase 4 / before any wide production
rollout):

  - **Zones are not modelled.** The intent model in this phase is L3/L4 only
    (§1.1 F2's name/tag → topology resolution is out of scope), so rules are
    written with `from any / to any`. Safety instead relies on the CIDR
    scoping of the rule itself plus band placement (see below). Confirm this
    is acceptable for your zone design before relying on it — see Open
    Question §8.1 in the design doc ("is every PA-VM under Panorama").
  - **Band placement is "top of pre-rulebase, tagged"**, not the full
    band-100/200/300/400/900 anchor scheme from §3.5 (that scheme assumes
    the estate already has anchor rules marking each band, which is a
    per-customer rulebase convention this phase does not assume). Every
    rule this adapter writes carries the `managed-by:fwauto` tag so it is
    trivially distinguishable and auditable regardless of position.
  - **Commit preview** uses `<show><config><diff/></show>` (candidate vs.
    running config diff) rather than PAN-OS's dedicated commit-preview job
    type — cheaper, synchronous, and sufficient to catch "did something
    unexpected end up in the candidate config" (§A.3's core requirement),
    but it does not simulate policy evaluation order the way a true commit
    preview job would.
  - **Object scope is Shared** (not per-device-group) per the team's
    decision — see app/models/fw_automation.py's module docstring.
  - **Address-group / service-group expansion is not implemented.** A rule
    source/destination member that isn't a literal CIDR or a plain address
    object resolves to "unknown" and is excluded from the CIDR set used for
    redundancy analysis (app/services/fw_redundancy.py) rather than guessed
    at — the conservative direction, matching that module's own bias.

Every function takes the credentials/target explicitly (host, port,
verify_tls, api_key, device_group, username) rather than a model instance,
so it can be exercised in tests against a fake PAN-OS HTTP server without
touching the database layer.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from app.services.fw_redundancy import NormalizedRule

TIMEOUT = httpx.Timeout(20.0)
POLL_TIMEOUT = httpx.Timeout(10.0)

_CIDR_LIKE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?$")


class PanoramaError(RuntimeError):
    """A Panorama call failed in a way the caller must stop and surface —
    never silently swallowed, unlike the read-only 'test connection' path."""


def _base_url(host: str, port: int) -> str:
    return f"https://{host}:{port}/api/"


def _get(host: str, port: int, verify_tls: bool, params: dict) -> ET.Element:
    try:
        resp = httpx.get(_base_url(host, port), params=params, timeout=TIMEOUT, verify=verify_tls)
    except httpx.HTTPError as e:
        raise PanoramaError(f"Panorama request failed: {e}") from e
    if resp.status_code != 200:
        raise PanoramaError(f"Panorama HTTP {resp.status_code}")
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        raise PanoramaError(f"Panorama returned unparseable XML: {e}") from e
    if root.attrib.get("status") != "success":
        msg = root.findtext(".//msg") or root.findtext(".//line") or resp.text[:300]
        raise PanoramaError(f"Panorama API error: {msg}")
    return root


# ---------------------------------------------------------------- fetch ----

def _member_values(entry: ET.Element, tag: str) -> list[str]:
    node = entry.find(tag)
    if node is None:
        return []
    return [m.text or "" for m in node.findall("member")]


def fetch_objects(host: str, port: int, verify_tls: bool, api_key: str, device_group: str) -> tuple[dict[str, str], dict[str, dict]]:
    """Returns (address_name -> cidr, service_name -> {proto, port_low, port_high}),
    from Shared plus the given device group (device-group objects can
    shadow Shared ones by name; device-group wins, matching PAN-OS lookup
    order)."""
    addresses: dict[str, str] = {}
    services: dict[str, dict] = {}

    for scope_xpath in (
        "/config/shared",
        f"/config/devices/entry/device-group/entry[@name='{device_group}']",
    ):
        root = _get(host, port, verify_tls, {
            "type": "config", "action": "get", "key": api_key,
            "xpath": f"{scope_xpath}/address",
        })
        for entry in root.findall(".//address/entry"):
            name = entry.attrib.get("name", "")
            ip = entry.findtext("ip-netmask") or entry.findtext("ip-range") or entry.findtext("fqdn")
            if name and ip:
                addresses[name] = ip if "/" in ip else f"{ip}/32" if _CIDR_LIKE.match(ip) else ip

        root = _get(host, port, verify_tls, {
            "type": "config", "action": "get", "key": api_key,
            "xpath": f"{scope_xpath}/service",
        })
        for entry in root.findall(".//service/entry"):
            name = entry.attrib.get("name", "")
            for proto in ("tcp", "udp"):
                proto_node = entry.find(proto)
                if proto_node is None:
                    continue
                port_spec = proto_node.findtext("port") or ""
                lo, hi = _parse_port_spec(port_spec)
                if lo is not None:
                    services[name] = {"proto": proto, "port_low": lo, "port_high": hi}

    return addresses, services


def _parse_port_spec(spec: str) -> tuple[int | None, int | None]:
    spec = spec.split(",")[0].strip()
    if not spec:
        return None, None
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return int(lo), int(hi)
    return int(spec), int(spec)


def fetch_rulebase(host: str, port: int, verify_tls: bool, api_key: str, device_group: str) -> list[NormalizedRule]:
    addresses, services = fetch_objects(host, port, verify_tls, api_key, device_group)

    def resolve_cidrs(members: list[str]) -> list[str]:
        out = []
        for m in members:
            if m == "any":
                out.append("any")
            elif _CIDR_LIKE.match(m):
                out.append(m if "/" in m else f"{m}/32")
            elif m in addresses:
                out.append(addresses[m])
            # else: unresolved (address-group or unknown object) — excluded,
            # per the conservative-direction note in this module's docstring.
        return out

    def resolve_services(members: list[str]) -> list[dict]:
        out = []
        for m in members:
            if m in ("any", "application-default"):
                out.append({"proto": "any", "port_low": 0, "port_high": 65535})
            elif m in services:
                out.append(services[m])
        return out

    root = _get(host, port, verify_tls, {
        "type": "config", "action": "get", "key": api_key,
        "xpath": f"/config/devices/entry/device-group/entry[@name='{device_group}']/pre-rulebase/security/rules",
    })

    rules: list[NormalizedRule] = []
    for entry in root.findall(".//rules/entry"):
        name = entry.attrib.get("name", "")
        action_raw = entry.findtext("action") or "allow"
        action = "allow" if action_raw in ("allow",) else "deny"
        disabled = (entry.findtext("disabled") or "no") == "yes"
        rules.append(NormalizedRule(
            name=name, action=action, disabled=disabled,
            source_cidrs=resolve_cidrs(_member_values(entry, "source")),
            destination_cidrs=resolve_cidrs(_member_values(entry, "destination")),
            services=resolve_services(_member_values(entry, "service")),
            applications=[a for a in _member_values(entry, "application") if a != "any"],
        ))
    return rules


def fetch_config_version(host: str, port: int, verify_tls: bool, api_key: str) -> str:
    """A cheap fingerprint of Panorama's current committed state, used at
    plan time (recorded on FwPlan) and re-checked at execute time — a
    mismatch means "someone changed something since this plan was rendered"
    (§3.11 drift detection), which invalidates the plan rather than risking
    a stale apply."""
    root = _get(host, port, verify_tls, {"type": "op", "key": api_key, "cmd": "<show><system><info/></show>"})
    return root.findtext(".//uptime") or root.findtext(".//sw-version") or ""


def pending_changes(host: str, port: int, verify_tls: bool, api_key: str) -> bool:
    """§4.2 'fail closed on shared candidate config' / Appendix A Phase 1:
    is there an uncommitted change already sitting in the candidate config
    from someone else? Fails closed (raises) rather than returning False on
    an unparseable response — an empty-looking result must never be read as
    "clean" (fwauto's `pending_changes()` note, carried over verbatim)."""
    try:
        root = _get(host, port, verify_tls, {
            "type": "op", "key": api_key,
            "cmd": "<check><pending-changes></pending-changes></check>",
        })
    except PanoramaError:
        raise
    result = (root.findtext(".//result") or "").strip().lower()
    if result in ("yes", "no"):
        return result == "yes"
    raise PanoramaError("Could not determine pending-changes state — failing closed, treating as dirty.")


# ---------------------------------------------------------------- render ----

def _sanitize_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", s)[:63]


@dataclass
class RenderedArtifact:
    rule_name: str
    objects_to_create: list[dict]   # [{type: address|service, name, value...}]
    objects_reused: list[dict]
    rule_body: dict

    def to_dict(self) -> dict:
        return {
            "rule_name": self.rule_name,
            "objects_to_create": self.objects_to_create,
            "objects_reused": self.objects_reused,
            "rule_body": self.rule_body,
        }


def render(
    *, ticket_ref: str, action: str, logging: str, source: list[str], destination: list[str],
    service: list[dict], addresses: dict[str, str], services: dict[str, dict], plan_seq: str,
    rule_name_override: str | None = None, source_zone: str | None = None,
    destination_zone: str | None = None, security_profile: str | None = None,
) -> RenderedArtifact:
    """Pure — no I/O. Given the request tuple and the *already-fetched*
    object catalog, decides reuse-vs-create by value (§3.4 rule 1) with
    deterministic names for anything new (§3.4 rule 2), and builds the rule
    body. Called once by fw_plan.build_plan (to compute the diff/plan_hash)
    and again, byte-for-byte identically, by execute() right before apply —
    the identical inputs guarantee an identical output, which is what makes
    plan_hash meaningful.

    `rule_name_override`/`source_zone`/`destination_zone`/`security_profile`
    come from the POA when the engineer specified them (§3 rule metadata:
    Rule Name, Source/Destination Zone, Security Profile) — the POA is the
    source of truth for these, so when present they are used verbatim
    rather than the auto-generated name / "any" zones this adapter falls
    back to when a rule was created by hand without them."""
    by_value_addr = {v: k for k, v in addresses.items()}
    by_value_svc = {(v["proto"], v["port_low"], v["port_high"]): k for k, v in services.items()}

    objects_to_create: list[dict] = []
    objects_reused: list[dict] = []

    def address_ref(cidr: str) -> str:
        if cidr in by_value_addr:
            objects_reused.append({"type": "address", "name": by_value_addr[cidr], "value": cidr})
            return by_value_addr[cidr]
        name = _sanitize_name(f"auto-net-{cidr.replace('/', '-').replace('.', '_')}")
        objects_to_create.append({"type": "address", "name": name, "value": cidr})
        return name

    def service_ref(svc: dict) -> str:
        key = (svc["proto"], svc["port_low"], svc["port_high"])
        if key in by_value_svc:
            objects_reused.append({"type": "service", "name": by_value_svc[key], "value": svc})
            return by_value_svc[key]
        port_label = str(svc["port_low"]) if svc["port_low"] == svc["port_high"] else f"{svc['port_low']}-{svc['port_high']}"
        name = _sanitize_name(f"auto-svc-{svc['proto']}-{port_label}")
        objects_to_create.append({"type": "service", "name": name, "value": svc})
        return name

    source_refs = [address_ref(c) for c in source]
    dest_refs = [address_ref(c) for c in destination]
    service_refs = [service_ref(s) for s in service]

    rule_name = _sanitize_name(rule_name_override) if rule_name_override else _sanitize_name(f"auto-{ticket_ref}-{plan_seq}")
    log_start = logging in ("session_start", "both")

    rule_body = {
        "from": [source_zone] if source_zone else ["any"],
        "to": [destination_zone] if destination_zone else ["any"],
        "source": source_refs, "destination": dest_refs, "service": service_refs,
        "application": ["any"], "action": action,
        "log-start": log_start, "log-end": logging != "none",
        "tag": ["managed-by:fwauto"],
        "security_profile": security_profile,
    }

    return RenderedArtifact(rule_name=rule_name, objects_to_create=objects_to_create, objects_reused=objects_reused, rule_body=rule_body)


# ----------------------------------------------------------------- diff ----

def preview_diff(host: str, port: int, verify_tls: bool, api_key: str) -> str:
    """Candidate-vs-running config diff — see this module's docstring for
    why this stands in for a true commit-preview job in this phase."""
    root = _get(host, port, verify_tls, {"type": "op", "key": api_key, "cmd": "<show><config><diff/></show>"})
    text = "".join(root.itertext()).strip()
    return text or "(no pending changes)"


# ---------------------------------------------------------------- apply ----

def _set(host: str, port: int, verify_tls: bool, api_key: str, xpath: str, element: str) -> None:
    _get(host, port, verify_tls, {"type": "config", "action": "set", "key": api_key, "xpath": xpath, "element": element})


def apply_artifact(host: str, port: int, verify_tls: bool, api_key: str, device_group: str, artifact: RenderedArtifact) -> None:
    """Phase 4 (§A.2): create objects then the rule, Shared scope for
    objects per the team's decision. Never called on an already-approved
    plan without a fresh drift check immediately before it — see
    fw_executor.execute."""
    for obj in artifact.objects_to_create:
        if obj["type"] == "address":
            xpath = f"/config/shared/address/entry[@name='{obj['name']}']"
            element = f"<ip-netmask>{obj['value']}</ip-netmask><tag><member>managed-by:fwauto</member></tag>"
        else:
            svc = obj["value"]
            xpath = f"/config/shared/service/entry[@name='{obj['name']}']"
            element = (
                f"<protocol><{svc['proto']}><port>{svc['port_low']}"
                f"{'' if svc['port_low'] == svc['port_high'] else '-' + str(svc['port_high'])}"
                f"</port></{svc['proto']}></protocol><tag><member>managed-by:fwauto</member></tag>"
            )
        _set(host, port, verify_tls, api_key, xpath, element)

    rb = artifact.rule_body
    members = lambda vals: "".join(f"<member>{v}</member>" for v in vals)
    element = (
        f"<from>{members(rb['from'])}</from><to>{members(rb['to'])}</to>"
        f"<source>{members(rb['source'])}</source><destination>{members(rb['destination'])}</destination>"
        f"<service>{members(rb['service'])}</service><application>{members(rb['application'])}</application>"
        f"<action>{rb['action']}</action>"
        f"<log-start>{'yes' if rb['log-start'] else 'no'}</log-start>"
        f"<log-end>{'yes' if rb['log-end'] else 'no'}</log-end>"
        f"<tag>{members(rb['tag'])}</tag>"
        + (f"<profile-setting><group><member>{rb['security_profile']}</member></group></profile-setting>" if rb.get("security_profile") else "")
    )
    xpath = f"/config/devices/entry/device-group/entry[@name='{device_group}']/pre-rulebase/security/rules/entry[@name='{artifact.rule_name}']"
    _set(host, port, verify_tls, api_key, xpath, element)


def validate_full(host: str, port: int, verify_tls: bool, api_key: str) -> None:
    _get(host, port, verify_tls, {"type": "op", "key": api_key, "cmd": "<validate><full/></validate>"})


# --------------------------------------------------------------- commit ----

def snapshot(host: str, port: int, verify_tls: bool, api_key: str, name: str) -> str:
    """Saves the *current* (pre-change) running config to a named file on
    Panorama — the rollback point. Must be called before apply_artifact."""
    _get(host, port, verify_tls, {
        "type": "op", "key": api_key,
        "cmd": f"<save><config><to>{name}</to></config></save>",
    })
    return name


def commit_partial(host: str, port: int, verify_tls: bool, api_key: str, admin_username: str) -> str:
    """Scoped to our own admin (§A.3) so we never absorb another operator's
    unrelated pending changes into this commit. Returns the job id."""
    cmd = f"<commit><partial><admin><member>{admin_username}</member></admin></partial></commit>"
    root = _get(host, port, verify_tls, {"type": "commit", "key": api_key, "cmd": cmd})
    job_id = root.findtext(".//job")
    if not job_id:
        raise PanoramaError("Commit did not return a job id")
    return job_id


def push_to_device_group(host: str, port: int, verify_tls: bool, api_key: str, device_group: str) -> str:
    cmd = f"<commit-all><type><device-group><entry name=\"{device_group}\"/></device-group></type></commit-all>"
    root = _get(host, port, verify_tls, {"type": "commit", "action": "all", "key": api_key, "cmd": cmd})
    job_id = root.findtext(".//job")
    if not job_id:
        raise PanoramaError("Push did not return a job id")
    return job_id


def poll_job(host: str, port: int, verify_tls: bool, api_key: str, job_id: str) -> tuple[str, str]:
    """Returns (status, result) where status is PEND/FIN and result is
    OK/FAIL once FIN. Single poll — caller loops with its own deadline
    per §3.11 ('poll with a deadline, generous per-vendor')."""
    root = _get(host, port, verify_tls, {
        "type": "op", "key": api_key, "cmd": f"<show><jobs><id>{job_id}</id></jobs></show>",
    })
    status = root.findtext(".//job/status") or "PEND"
    result = root.findtext(".//job/result") or ""
    return status, result


# --------------------------------------------------------------- verify ----

def verify_rule_present(host: str, port: int, verify_tls: bool, api_key: str, device_group: str, rule_name: str) -> dict:
    root = _get(host, port, verify_tls, {
        "type": "config", "action": "get", "key": api_key,
        "xpath": f"/config/devices/entry/device-group/entry[@name='{device_group}']"
                 f"/pre-rulebase/security/rules/entry[@name='{rule_name}']",
    })
    entry = root.find(".//entry")
    if entry is None:
        return {"present": False}
    return {
        "present": True,
        "action": entry.findtext("action"),
        "tag": _member_values(entry, "tag"),
        "disabled": (entry.findtext("disabled") or "no") == "yes",
    }


# -------------------------------------------------------------- rollback ---

def rollback_to_snapshot(host: str, port: int, verify_tls: bool, api_key: str, admin_username: str, device_group: str, snapshot_name: str) -> str:
    """Loads the named pre-change config back in, commits it (admin-scoped),
    and re-pushes to the device group so the *devices* — not just
    Panorama's own config — return to the pre-change state. Returns the
    push job id to poll."""
    _get(host, port, verify_tls, {
        "type": "op", "key": api_key,
        "cmd": f"<load><config><from>{snapshot_name}</from></config></load>",
    })
    commit_partial(host, port, verify_tls, api_key, admin_username)
    return push_to_device_group(host, port, verify_tls, api_key, device_group)
