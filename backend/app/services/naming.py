"""Naming — one standard for every network component, cloud and on-prem.

Teams were each inventing names (`vpc-prod-use1`, `core-rtr-01`,
`prod-vcn-default-sl`...). This module is the single source of truth for the
default convention, and it does three things with it:

* **generate** a compliant name from a few structured choices (provider,
  environment, region/site, component, application) and pick the next free
  sequence number so the result is unique against the live inventory;
* **validate** any name against the same rule, including each provider's own
  hard limits (length/charset) that apply regardless of convention;
* **audit** the whole inventory and report which existing names don't comply,
  with a suggested replacement.

Convention (lower-case, hyphen separated, fixed segment order):

    cloud   : {org}-{env}-{region}-{type}-{app}-{seq}     bfl-prd-use1-vpc-payments-01
    on-prem : {site}-{role}-{type}-{seq}                  dc1-core-rtr-01
    vrf     : {site}-vrf-{app}                            dc1-vrf-payments

It is deliberately code-defined, not stored in a table: a default pattern that
ships with the product needs no migration and cannot be stranded by an old
database volume. Adjusting the standard means editing the constants below.

Nothing here writes to the inventory — names are generated and checked, not
reserved (a reservation feature was explicitly left out of scope).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cloud_networks import CloudNetworkInterface
from app.models.connectivity import Circuit
from app.models.device import Device
from app.models.network import Network, Subnet
from app.models.routing import RouteTable
from app.models.security_policy import SecurityGroup

ORG_CODE = "bfl"

# --- code tables -------------------------------------------------------------

ENV_CODES: dict[str, str] = {
    "prd": "Production",
    "uat": "UAT / pre-production",
    "stg": "Staging",
    "dev": "Development",
    "dr": "Disaster recovery",
    "shr": "Shared services",
}

# Free-form regions are accepted too (any 2-8 char [a-z0-9] code); these are the
# ones the builder offers, keyed by provider so the dropdown only shows regions
# that exist in that cloud. value = (short code, human label)
REGION_CODES: dict[str, dict[str, tuple[str, str]]] = {
    "aws": {
        "us-east-1": ("use1", "US East (N. Virginia)"),
        "us-west-2": ("usw2", "US West (Oregon)"),
        "eu-west-1": ("euw1", "Europe (Ireland)"),
        "ap-south-1": ("aps1", "Asia Pacific (Mumbai)"),
        "ap-southeast-1": ("apse1", "Asia Pacific (Singapore)"),
    },
    "azure": {
        "eastus": ("eus", "East US"),
        "westeurope": ("weu", "West Europe"),
        "centralindia": ("cin", "Central India"),
        "southindia": ("sin", "South India"),
    },
    "gcp": {
        "us-central1": ("usc1", "us-central1 (Iowa)"),
        "europe-west1": ("euw1", "europe-west1 (Belgium)"),
        "asia-south1": ("aps1", "asia-south1 (Mumbai)"),
    },
    "oci": {
        "us-ashburn-1": ("iad", "US East (Ashburn)"),
        "uk-london-1": ("lhr", "UK South (London)"),
        "ap-mumbai-1": ("bom", "India West (Mumbai)"),
        "ap-hyderabad-1": ("hyd", "India South (Hyderabad)"),
    },
}

# Provider-native hard limits that hold no matter what convention is in force.
# `charset` is a regex a whole name must satisfy.
PROVIDER_RULES: dict[str, dict] = {
    "aws": {"label": "AWS", "max_len": 255, "charset": r"[a-z0-9._-]+",
            "note": "Name tags allow 256 chars; 255 kept to match the convention's lower-case-only rule."},
    "azure": {"label": "Azure", "max_len": 64, "charset": r"[a-z0-9][a-z0-9._-]*[a-z0-9_]",
              "note": "Azure resource names: 2-64 chars, start with an alphanumeric, end with alphanumeric or underscore."},
    "gcp": {"label": "GCP", "max_len": 63, "charset": r"[a-z]([a-z0-9-]*[a-z0-9])?",
            "note": "GCP: 1-63 chars, lower-case letters/digits/hyphens, must start with a letter, cannot end with a hyphen."},
    "oci": {"label": "OCI", "max_len": 255, "charset": r"[a-z0-9._-]+",
            "note": "OCI display names allow 255 chars; lower-case kept for convention."},
}

# --- component catalogue ------------------------------------------------------


@dataclass(frozen=True)
class Component:
    id: str
    label: str
    scope: str                     # "cloud" | "onprem"
    pattern: str                   # tokens in {braces}
    type_codes: dict[str, str]     # provider (or "*") -> {type} segment value
    needs_role: bool = False
    roles: tuple[str, ...] = ()
    help: str = ""


# {type} differs by provider where each cloud calls the same thing something else.
COMPONENTS: list[Component] = [
    Component("network", "Virtual network (VPC / VNet / VCN)", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"aws": "vpc", "azure": "vnet", "gcp": "vpc", "oci": "vcn"},
              help="One per application boundary per environment and region."),
    Component("subnet", "Subnet", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"*": "snet"}, help="Add the tier in {app}, e.g. payments-web, payments-db."),
    Component("route_table", "Route table", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"*": "rt"}),
    Component("security_group", "Security group / NSG / firewall rules / security list", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"aws": "sg", "azure": "nsg", "gcp": "fw", "oci": "sl"},
              help="AWS security group, Azure NSG, GCP firewall rule set, OCI security list."),
    Component("peering", "Peering / transit attachment", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"aws": "tgw-att", "azure": "peer", "gcp": "peer", "oci": "drg-att"},
              help="Put both ends in {app}, e.g. payments-to-shared."),
    Component("circuit", "Dedicated interconnect (DX / ExpressRoute / Interconnect / FastConnect)", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"aws": "dx", "azure": "er", "gcp": "ic", "oci": "fc"}),
    Component("vpn", "IPsec VPN connection", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"*": "vpn"}),
    Component("interface", "Network interface (ENI / NIC / vNIC)", "cloud",
              "{org}-{env}-{region}-{type}-{app}-{seq}",
              {"aws": "eni", "azure": "nic", "gcp": "nic", "oci": "vnic"},
              help="Prefer the host's name in {app}, e.g. payments-app01."),
    Component("device", "On-prem network device", "onprem",
              "{site}-{role}-{type}-{seq}",
              {"*": ""}, needs_role=True,
              roles=("core", "edge", "dist", "access", "mgmt", "dmz", "wan"),
              help="{type} comes from the device kind: router, switch, firewall, load balancer."),
    Component("vrf", "On-prem VRF", "onprem",
              "{site}-vrf-{app}", {"*": "vrf"},
              help="One VRF per segment, named for the segment, e.g. dc1-vrf-payments."),
    Component("mpls_circuit", "On-prem MPLS / WAN circuit", "onprem",
              "{site}-{role}-{type}-{app}-{seq}", {"*": "mpls"}, needs_role=True,
              roles=("wan", "edge", "core"),
              help="{app} is the far end, e.g. dc1-wan-mpls-awsuse1-01."),
]
COMPONENT_BY_ID = {c.id: c for c in COMPONENTS}

DEVICE_KIND_CODES = {"router": "rtr", "switch": "sw", "firewall": "fw", "load_balancer": "lb"}

_SEG = re.compile(r"^[a-z0-9]+$")
_SEQ = re.compile(r"^\d{2,3}$")


def region_code_for(provider: str, region: str | None) -> str | None:
    """Short code for a provider region name, or None if unknown. Lets the
    audit map an existing network's `region` column to the {region} segment."""
    if not region:
        return None
    hit = REGION_CODES.get(provider, {}).get(region)
    return hit[0] if hit else None


def type_code(comp: Component, provider: str | None, kind: str | None = None) -> str | None:
    if comp.id == "device":
        return DEVICE_KIND_CODES.get(kind or "")
    codes = comp.type_codes
    if "*" in codes:
        return codes["*"]
    return codes.get(provider or "")


# --- inputs / results ---------------------------------------------------------


@dataclass
class NameRequest:
    component: str
    provider: str | None = None     # cloud components
    env: str | None = None
    region: str | None = None       # short code, e.g. use1 (or a provider region name — resolved)
    site: str | None = None         # on-prem
    app: str | None = None
    role: str | None = None
    kind: str | None = None         # device kind
    seq: int | None = None          # force a sequence; default = next free


@dataclass
class NameResult:
    name: str | None
    pattern: str
    parts: dict[str, str]
    issues: list[str] = field(default_factory=list)
    unique: bool | None = None
    collisions: list[dict] = field(default_factory=list)
    seq: int | None = None
    alternatives: list[str] = field(default_factory=list)


def _slug(value: str | None) -> str:
    """Lower-case and collapse anything not [a-z0-9] into nothing: a segment
    never contains a hyphen, otherwise the name can't be parsed back."""
    return re.sub(r"[^a-z0-9]", "", (value or "").strip().lower())


def _slug_app(value: str | None) -> str:
    """{app} may carry a tier (payments-web): spaces/underscores become hyphens,
    anything else non-alphanumeric is dropped, hyphens collapse and are trimmed."""
    v = re.sub(r"[\s_]+", "-", (value or "").strip().lower())
    v = re.sub(r"[^a-z0-9-]", "", v)
    return re.sub(r"-{2,}", "-", v).strip("-")


def _existing_names(db: Session, comp: Component, provider: str | None) -> dict[str, str]:
    """lower-cased name -> where it lives, for the component's inventory table."""
    rows: list[tuple[str, str]] = []
    if comp.id == "network":
        q = select(Network.name, Network.provider).where(Network.deleted_at.is_(None))
        rows = [(n, f"network ({p})") for n, p in db.execute(q).all() if provider in (None, p)]
    elif comp.id == "subnet":
        rows = [(n, "subnet") for (n,) in db.execute(select(Subnet.name).where(Subnet.name.is_not(None))).all()]
    elif comp.id == "route_table":
        rows = [(n, "route table") for (n,) in db.execute(select(RouteTable.name).where(RouteTable.deleted_at.is_(None))).all()]
    elif comp.id == "security_group":
        q = select(SecurityGroup.name, SecurityGroup.provider).where(SecurityGroup.deleted_at.is_(None))
        rows = [(n, f"security group ({p})") for n, p in db.execute(q).all()]
    elif comp.id in ("circuit", "mpls_circuit"):
        rows = [(n, "circuit") for (n,) in db.execute(select(Circuit.name).where(Circuit.deleted_at.is_(None))).all()]
    elif comp.id == "interface":
        rows = [(n, "network interface") for (n,) in db.execute(select(CloudNetworkInterface.name).where(CloudNetworkInterface.deleted_at.is_(None))).all()]
    elif comp.id == "device":
        rows = [(n, "device") for (n,) in db.execute(select(Device.hostname).where(Device.deleted_at.is_(None))).all()]
    return {n.lower(): where for n, where in rows if n}


def _provider_issues(name: str, provider: str | None) -> list[str]:
    rule = PROVIDER_RULES.get(provider or "")
    if not rule:
        return []
    out: list[str] = []
    if len(name) > rule["max_len"]:
        out.append(f"{rule['label']} allows at most {rule['max_len']} characters; this is {len(name)}.")
    if not re.fullmatch(rule["charset"], name):
        out.append(f"Not a valid {rule['label']} name. {rule['note']}")
    return out


def _fill(comp: Component, req: NameRequest, seq: int | None) -> tuple[dict[str, str], list[str]]:
    """Build the {token: value} map, collecting every problem rather than
    stopping at the first so the UI can show them all at once."""
    issues: list[str] = []
    parts: dict[str, str] = {}
    pat = comp.pattern

    def need(token: str, value: str | None, label: str) -> None:
        v = _slug(value)
        if not v:
            issues.append(f"{label} is required.")
        elif not _SEG.match(v):
            issues.append(f"{label} must be letters and digits only.")
        else:
            parts[token] = v

    if "{org}" in pat:
        parts["org"] = ORG_CODE
    if "{env}" in pat:
        env = _slug(req.env)
        if env not in ENV_CODES:
            issues.append(f"Environment must be one of: {', '.join(ENV_CODES)}.")
        else:
            parts["env"] = env
    if "{region}" in pat:
        raw = (req.region or "").strip().lower()
        resolved = region_code_for(req.provider or "", raw) or _slug(raw)
        if not resolved:
            issues.append("Region is required.")
        elif not (2 <= len(resolved) <= 8):
            issues.append("Region code must be 2-8 letters/digits (e.g. use1).")
        else:
            parts["region"] = resolved
    if "{site}" in pat:
        need("site", req.site, "Site")
    if "{role}" in pat:
        role = _slug(req.role)
        if role not in comp.roles:
            issues.append(f"Role must be one of: {', '.join(comp.roles)}.")
        else:
            parts["role"] = role
    if "{type}" in pat:
        t = type_code(comp, req.provider, req.kind)
        if t is None or t == "":
            issues.append("Provider is required." if comp.scope == "cloud" else "Device kind is required.")
        else:
            parts["type"] = t
    if "{app}" in pat:
        app = _slug_app(req.app)
        if not app:
            issues.append("Application / segment is required.")
        else:
            parts["app"] = app
    if "{seq}" in pat and seq is not None:
        parts["seq"] = f"{seq:02d}"
    return parts, issues


def _render(pattern: str, parts: dict[str, str]) -> str:
    return pattern.format(**parts)


def generate(db: Session, req: NameRequest) -> NameResult:
    comp = COMPONENT_BY_ID.get(req.component)
    if comp is None:
        return NameResult(None, "", {}, [f"Unknown component '{req.component}'."])
    if comp.scope == "cloud" and req.provider not in PROVIDER_RULES:
        return NameResult(None, comp.pattern, {}, ["Provider must be one of: aws, azure, gcp, oci."])

    has_seq = "{seq}" in comp.pattern
    existing = _existing_names(db, comp, req.provider if comp.id == "network" else None)

    # First pass without a sequence just to surface input problems and, if the
    # pattern has {seq}, find the next free one.
    parts, issues = _fill(comp, req, 1 if has_seq else None)
    if issues:
        return NameResult(None, comp.pattern, parts, issues)

    seq = None
    if has_seq:
        seq = req.seq if req.seq else _next_free_seq(comp, parts, existing)
        if seq is None or not (1 <= seq <= 99):
            return NameResult(None, comp.pattern, parts, ["No free sequence number left (01-99) for this combination."])
        parts["seq"] = f"{seq:02d}"

    name = _render(comp.pattern, parts)
    issues.extend(_provider_issues(name, req.provider if comp.scope == "cloud" else None))

    collisions = []
    if name.lower() in existing:
        collisions.append({"name": name, "where": existing[name.lower()]})
        issues.append("This name is already in use in the inventory.")
    alternatives = []
    if has_seq and seq is not None:
        for s in range(seq + 1, min(seq + 20, 100)):
            p2 = dict(parts, seq=f"{s:02d}")
            cand = _render(comp.pattern, p2)
            if cand.lower() not in existing:
                alternatives.append(cand)
            if len(alternatives) == 3:
                break
    return NameResult(name, comp.pattern, parts, issues, unique=not collisions, collisions=collisions,
                      seq=seq, alternatives=alternatives)


def _next_free_seq(comp: Component, parts: dict[str, str], existing: dict[str, str]) -> int | None:
    for s in range(1, 100):
        cand = _render(comp.pattern, dict(parts, seq=f"{s:02d}")).lower()
        if cand not in existing:
            return s
    return None


# --- validation / parsing -----------------------------------------------------


def _pattern_regex(comp: Component, provider: str | None) -> re.Pattern:
    """A pattern like {org}-{env}-... becomes a regex with one named group per
    token. {type} is pinned to the codes valid for that provider so a VNet named
    with `vpc` is caught as the wrong type."""
    group = {
        "org": rf"(?P<org>{ORG_CODE})",
        "env": r"(?P<env>" + "|".join(ENV_CODES) + r")",
        "region": r"(?P<region>[a-z0-9]{2,8})",
        "site": r"(?P<site>[a-z0-9]+)",
        "role": r"(?P<role>" + "|".join(comp.roles or ("x",)) + r")",
        "app": r"(?P<app>[a-z0-9]+(?:-[a-z0-9]+)*)",   # an app may carry a tier: payments-web
        "seq": r"(?P<seq>\d{2,3})",
    }
    codes = {c for c in comp.type_codes.values() if c}
    if comp.id == "device":
        codes = set(DEVICE_KIND_CODES.values())
    if provider and "*" not in comp.type_codes and provider in comp.type_codes:
        codes = {comp.type_codes[provider]}
    group["type"] = r"(?P<type>" + "|".join(sorted((re.escape(c) for c in codes), key=len, reverse=True)) + r")"
    out = comp.pattern
    for token, rx in group.items():
        out = out.replace("{" + token + "}", rx)
    return re.compile(rf"^{out}$")


def validate(db: Session | None, name: str, component: str, provider: str | None = None) -> dict:
    comp = COMPONENT_BY_ID.get(component)
    if comp is None:
        return {"compliant": False, "issues": [f"Unknown component '{component}'."], "parts": {}, "pattern": ""}
    name = (name or "").strip()
    issues: list[str] = []
    if not name:
        return {"compliant": False, "issues": ["Name is empty."], "parts": {}, "pattern": comp.pattern}

    if name != name.lower():
        issues.append("Use lower-case only.")
    if "_" in name or " " in name:
        issues.append("Use hyphens as separators — no underscores or spaces.")
    issues.extend(_provider_issues(name.lower(), provider if comp.scope == "cloud" else None))

    m = _pattern_regex(comp, provider if comp.scope == "cloud" else None).match(name.lower().replace("_", "-"))
    parts = m.groupdict() if m else {}
    if not m:
        issues.append(f"Does not match the standard pattern {comp.pattern}.")
        issues.extend(_diagnose(comp, name.lower().replace("_", "-"), provider))
    return {"compliant": not issues, "issues": issues, "parts": parts, "pattern": comp.pattern}


def _diagnose(comp: Component, name: str, provider: str | None) -> list[str]:
    """Best-effort pointer at *which* segment is wrong, so 'does not match' is
    actionable. Walks the pattern's fixed-position segments only."""
    segs = name.split("-")
    toks = [t.strip("{}") for t in comp.pattern.split("-")]
    out: list[str] = []
    if len(segs) < len(toks):
        out.append(f"Too few segments: expected {len(toks)} ({'-'.join(toks)}), found {len(segs)}.")
        return out
    if toks[0] == "org" and segs[0] != ORG_CODE:
        out.append(f"First segment should be the org code '{ORG_CODE}', found '{segs[0]}'.")
    if "env" in toks:
        i = toks.index("env")
        if segs[i] not in ENV_CODES:
            out.append(f"Environment segment '{segs[i]}' is not one of {', '.join(ENV_CODES)}.")
    if "type" in toks:
        i = toks.index("type")
        want = type_code(comp, provider) if comp.scope == "cloud" else None
        if want and segs[i] != want:
            out.append(f"Type segment should be '{want}' for {PROVIDER_RULES.get(provider or '', {}).get('label', provider)}, found '{segs[i]}'.")
    if "seq" in toks and not _SEQ.match(segs[-1]):
        out.append("Name should end with a 2-digit sequence number, e.g. -01.")
    return out


# --- audit --------------------------------------------------------------------


def _infer_env(env_name: str | None) -> str | None:
    e = _slug(env_name)
    aliases = {"prod": "prd", "production": "prd", "prd": "prd", "uat": "uat", "staging": "stg", "stage": "stg",
               "stg": "stg", "dev": "dev", "development": "dev", "dr": "dr", "shared": "shr", "shr": "shr"}
    return aliases.get(e)


def _env_for(env_name: str | None, legacy_name: str) -> str | None:
    """Environment code from the network's own field, else from a word in its
    legacy name ('vnet-prod-eastus' -> prd)."""
    hit = _infer_env(env_name)
    if hit:
        return hit
    for w in re.split(r"[^a-z0-9]+", legacy_name.lower()):
        hit = _infer_env(w)
        if hit:
            return hit
    return None


def audit(db: Session) -> dict:
    """Score every named inventory object against the standard."""
    sections: list[dict] = []

    def add(comp_id: str, rows: list[dict]) -> None:
        comp = COMPONENT_BY_ID[comp_id]
        items = []
        for r in rows:
            v = validate(db, r["name"], comp_id, r.get("provider"))
            suggest = r.get("suggest")
            items.append({"name": r["name"], "provider": r.get("provider"), "context": r.get("context", ""),
                          "compliant": v["compliant"], "issues": v["issues"],
                          # only offer a replacement for a name that actually needs replacing
                          "suggestion": suggest() if suggest and not v["compliant"] else None})
        compliant = sum(1 for i in items if i["compliant"])
        sections.append({"component": comp_id, "label": comp.label, "scope": comp.scope, "pattern": comp.pattern,
                         "total": len(items), "compliant": compliant, "items": items})

    nets = db.execute(select(Network).where(Network.deleted_at.is_(None)).order_by(Network.name)).scalars().all()
    add("network", [{
        "name": n.name, "provider": n.provider, "context": f"{n.cidr} · {n.region or 'no region'}",
        "suggest": lambda n=n: _suggest(db, "network", n.provider, _env_for(n.environment_name, n.name), n.region, _app_from(n.name)),
    } for n in nets])

    sgs = db.execute(select(SecurityGroup).where(SecurityGroup.deleted_at.is_(None)).order_by(SecurityGroup.name)).scalars().all()
    net_by_id = {n.id: n for n in nets}
    add("security_group", [{
        "name": s.name, "provider": _sg_provider(s.provider), "context": s.provider,
        "suggest": lambda s=s: _suggest(db, "security_group", _sg_provider(s.provider),
                                        _env_for(None, s.name),
                                        net_by_id[s.network_id].region if s.network_id in net_by_id else None, _app_from(s.name)),
    } for s in sgs])

    rts = db.execute(select(RouteTable).where(RouteTable.deleted_at.is_(None)).order_by(RouteTable.name)).scalars().all()
    add("route_table", [{
        "name": r.name, "provider": net_by_id[r.network_id].provider if r.network_id in net_by_id else None,
        "context": net_by_id[r.network_id].name if r.network_id in net_by_id else "",
        "suggest": lambda r=r: _suggest(db, "route_table", net_by_id[r.network_id].provider, _env_for(None, r.name),
                                        net_by_id[r.network_id].region, _app_from(r.name)) if r.network_id in net_by_id else None,
    } for r in rts])

    circuits = db.execute(select(Circuit).where(Circuit.deleted_at.is_(None)).order_by(Circuit.name)).scalars().all()
    add("circuit", [{"name": c.name, "provider": c.cloud_account.provider if c.cloud_account else None,
                     "context": c.circuit_type} for c in circuits if c.cloud_account_id is not None])
    add("mpls_circuit", [{"name": c.name, "provider": None, "context": "on-prem"}
                         for c in circuits if c.cloud_account_id is None])

    devs = db.execute(select(Device).where(Device.deleted_at.is_(None)).order_by(Device.hostname)).scalars().all()
    add("device", [{"name": d.hostname, "provider": None, "context": f"{d.site or 'no site'} · {d.device_type}",
                    "suggest": lambda d=d: _suggest_device(db, d)} for d in devs])

    total = sum(s["total"] for s in sections)
    ok = sum(s["compliant"] for s in sections)
    return {"total": total, "compliant": ok, "non_compliant": total - ok, "sections": sections}


_LEGACY_NOISE = set(ENV_CODES) | {
    "prod", "production", "staging", "development", "shared", "vpc", "vnet", "vcn", "network", "subnet",
    "sg", "nsg", "sl", "fw", "rt", "default", "allow", "live", "demo", "test",
}


_REGION_WORDS = {w for regs in REGION_CODES.values() for v, (code, _l) in regs.items()
                 for w in (v.replace("-", ""), code, *v.split("-"))} | {"uk", "us", "eu", "euw", "weu", "eus", "westeu", "useast", "uscentral"}


def _app_from(name: str) -> str:
    """Pull a plausible {app} out of a legacy name by dropping the words the new
    convention already encodes (env, type, region-looking tokens like 'use1')."""
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]
    keep = [w for w in words if w not in _LEGACY_NOISE and w not in _REGION_WORDS and not re.fullmatch(r"[a-z]{2,4}\d", w)]
    return "".join(keep[:2]) or "core"


def _sg_provider(sg_provider: str) -> str | None:
    return {"aws_sg": "aws", "azure_nsg": "azure", "gcp_firewall": "gcp", "oci_security_list": "oci"}.get(sg_provider)


def _suggest(db: Session, component: str, provider: str | None, env_name: str | None, region: str | None,
             app: str) -> str | None:
    env = _infer_env(env_name)
    if not provider or not env or not region:
        return None
    res = generate(db, NameRequest(component=component, provider=provider, env=env, region=region, app=app))
    return res.name if res.name and not res.issues else None


def _suggest_device(db: Session, d: Device) -> str | None:
    kind = d.device_type if d.device_type in DEVICE_KIND_CODES else None
    if not kind or not d.site:
        return None
    role = "edge" if "edge" in d.hostname.lower() else "core"
    res = generate(db, NameRequest(component="device", site=d.site, role=role, kind=kind))
    return res.name if res.name and not res.issues else None


# --- spec for the UI ----------------------------------------------------------


def spec(db: Session) -> dict:
    sites = sorted({s for (s,) in db.execute(select(Device.site).where(Device.site.is_not(None), Device.deleted_at.is_(None))).all() if s})
    return {
        "org": ORG_CODE,
        "environments": [{"code": c, "label": l} for c, l in ENV_CODES.items()],
        "regions": {p: [{"value": v, "code": code, "label": label} for v, (code, label) in regs.items()]
                    for p, regs in REGION_CODES.items()},
        "providers": [{"id": k, "label": v["label"], "max_len": v["max_len"], "note": v["note"]} for k, v in PROVIDER_RULES.items()],
        "device_kinds": [{"id": k, "code": c} for k, c in DEVICE_KIND_CODES.items()],
        "sites": sites,
        "components": [{
            "id": c.id, "label": c.label, "scope": c.scope, "pattern": c.pattern, "help": c.help,
            "needs_role": c.needs_role, "roles": list(c.roles),
            "type_codes": c.type_codes,
        } for c in COMPONENTS],
        "rules": [
            "Lower-case letters and digits only; hyphen is the only separator.",
            "Segment order is fixed; never reorder or drop a segment.",
            "Sequence is two digits (01-99) and makes the name unique within its group.",
            "An application with a tier joins them in {app}: payments-web, payments-db.",
            "Provider limits always apply on top (GCP must start with a letter, Azure max 64 characters).",
        ],
    }
