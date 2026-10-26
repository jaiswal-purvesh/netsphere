"""
app/poa/enrich.py
------------------
Ported from the standalone RITM-POA tool's poa_enrich.py. Turns one raw RITM
input row (from the uploaded CSV/XLSX/ODS/ODT) into one fully-enriched row
matching the output Excel/Word template's exact column set:

    Source IP, Destination IP, Destination FQDN, Destination Type, Destination Port,
    SRC Location, DST Location,
    Whitelisting Required at OCI, Firewall Whitelisting,
    Source Firewall Name, Destination Firewall Name,
    Rule Name, SRC Subnet Name, DST Subnet Name,
    DST Subnet Inbound SL (If DST is Entire Subnet),
    DST Server NSG Inbound SL (If DST is Single IP), NSG Remark,
    Routing Availibility, Input Validation

Fields that CANNOT be derived from the reference sheets are filled with
"MANUAL ENTRY REQUIRED" so they are never silently blank/wrong.

Only a genuinely unresolvable per-row case falls back to MANUAL - the
location columns, the SL columns, and the firewall columns are all derived
from the reference sheets wherever the data allows it. For a single-IP
destination, the exact IP is checked first against the OCI UAT/PROD
NSG-Security-List host reports: a real attached NSG goes to DST Server NSG
Inbound SL; when no NSG applies at all (not in either host report, or the
host/subnet has none), the security list answer goes to DST Subnet Inbound
SL instead - so DST Server NSG Inbound SL is never holding a security list
value, only a real or still-unresolved NSG. See app/poa/lookup.py's module
docstring for exactly how each is derived.

This is a faithful, logic-preserving port: only the cross-module import
(`from poa_lookup import (...)` -> `from app.poa.lookup import (...)`,
including the local import inside `_filter_security_lists_for_row`) changed
from the original.
"""

import ipaddress
import re

from app.poa.lookup import (
    SL_MSG_RULE_COUNT_FULL,
    SL_MSG_NOT_FILLED_SINGLE,
    SL_MSG_NONE_FOUND,
    AUDIT_NOT_FOUND_REMARK,
)

MANUAL = "MANUAL ENTRY REQUIRED"
# Distinct from MANUAL on purpose: MANUAL means "the inventories don't cover
# this IP yet", which is fixed by populating a reference sheet. INVALID_IP means
# "this cell never held an IP at all", which can only be fixed in the RITM
# input. They need different follow-up, so they must not share a marker.
INVALID_IP = "NOT A VALID IP/CIDR"
# The generic name used for any leg that sits in the DC / on-premise estate.
# The merged CIDR->Firewall inventory only covers the cloud environments (OCI,
# AWS, Azure), so an on-prem IP can never map to a named firewall there. That
# is a permanent property of the sheet, not a gap to be filled, so those legs
# get this label instead of MANUAL - which would otherwise ask an engineer to
# look up a name that does not exist.
ONPREM_FIREWALL = "Onprem Firewall"

OUTPUT_COLUMNS = [
    "Source IP", "Destination IP", "Destination FQDN", "Destination Type", "Destination Port",
    "SRC Location", "DST Location",
    "Whitelisting Required at OCI", "Firewall Whitelisting",
    "Source Firewall Name", "Destination Firewall Name",
    "Rule Name", "SRC Subnet Name", "DST Subnet Name",
    "DST Subnet Inbound SL (If DST is Entire Subnet)",
    "DST Server NSG Inbound SL (If DST is Single IP)", "NSG Remark",
    "Routing Availibility", "Input Validation",
]


def _clean(v):
    """Normalize pandas NaN / the literal string 'null' to a real empty string."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "null", "none"):
        return ""
    return s


def _get_field(raw_row, *names):
    """
    Fetch a field from a CSV row by name, tolerant of the header variations
    real exports (ServiceNow, Excel copy/paste, etc.) commonly introduce:
    extra leading/trailing spaces, different case, or a stray BOM character
    on the first column. Tries each name in `names` in order; returns the
    first non-empty match, or "" if nothing matches at all.

    This is what fixes "the script isn't picking up my columns" when the
    input CSV's headers don't match INPUT_RITM_FORMAT byte-for-byte.
    """
    # Build once per call: a normalized-key -> real-key map for this row.
    try:
        keys = list(raw_row.keys())
    except AttributeError:
        keys = list(raw_row.index)  # pandas Series fallback
    norm_map = {}
    for k in keys:
        norm = str(k).replace("﻿", "").strip().lower()
        norm_map.setdefault(norm, k)

    for name in names:
        norm = name.strip().lower()
        real_key = norm_map.get(norm)
        if real_key is not None:
            val = _clean(raw_row.get(real_key))
            if val:
                return val
    return ""


def _is_valid_ip_or_cidr(value):
    """Whether a raw Source/Destination IP cell actually holds an IP address or
    a CIDR network.

    Real RITM exports sometimes carry an AD group or application name in these
    columns (e.g. 'bfl\\it_pennant_bfl', 'it_pennant_partner'). Without this
    check such a value misses every inventory lookup and falls through to the
    same defaults a genuine unclassified on-prem host would produce - so the POA
    reports it as 'On-Prem / Unclassified' with a firewall rule beside it, and a
    reviewer cannot tell it apart from a real address.

    A cell may list several values separated by comma, semicolon, newline, or
    whitespace (matching what _to_networks accepts); every token has to parse.
    """
    text = str(value).strip()
    tokens = [
        token for part in re.split(r"[,\n;]+", text)
        for token in part.split() if token.strip()
    ]
    if not tokens:
        return False
    for token in tokens:
        try:
            ipaddress.ip_network(token, strict=False)
        except ValueError:
            return False
    return True


def _validation_message(src_invalid, dst_invalid):
    """The Input Validation cell: which input field failed to parse, or ""."""
    bad = [
        label for label, invalid in
        (("Source IP", src_invalid), ("Destination IP", dst_invalid)) if invalid
    ]
    if not bad:
        return ""
    if len(bad) == 2:
        return "Source IP and Destination IP are not valid IPs or CIDRs"
    return f"{bad[0]} is not a valid IP or CIDR"


def _is_entire_subnet(dst_ip_raw):
    """Very simple heuristic: a destination given as a CIDR (contains '/') is
    treated as 'entire subnet'; a plain IP is treated as 'single IP'."""
    return "/" in str(dst_ip_raw)


def _to_float(value):
    """Best-effort float parse (handles NaN/None/'' from the inventory sheet's
    NSG_Count column). Returns 0.0 on anything unparsable."""
    try:
        if value is None:
            return 0.0
        f = float(value)
        return 0.0 if f != f else f  # f != f is True only for NaN
    except (TypeError, ValueError):
        return 0.0


def _filter_security_lists_for_row(subnet_row):
    """Filter a matched subnet dict's raw Security_Lists field down to the
    non-default lists (drops the 'Infra...' default security list). Local
    import avoids a hard dependency for callers that only need poa_enrich."""
    from app.poa.lookup import _filter_security_lists
    return _filter_security_lists(subnet_row.get("security_lists"))


def _is_onprem_location(location):
    """Whether a leg's SRC/DST Location places it in the DC / on-premise estate.

    classify_location() returns an 'On-Prem ...' string for exactly the IPs that
    matched neither an OCI subnet nor the merged CIDR/Firewall inventory - i.e.
    the DC and on-premise networks - so the location already computed for the
    row is the authoritative test, and the firewall column stays consistent with
    what the Location column beside it reports.
    """
    return str(location).startswith("On-Prem")


def _firewall_name(firewall_row, location=""):
    """The mapped firewall name for one leg of a flow (source or destination),
    taken from the merged CIDR->Firewall inventory. Falls back to
    ONPREM_FIREWALL for a DC/on-premise leg, which that inventory never covers,
    and otherwise to MANUAL when the leg's IP exists but isn't covered by any
    CIDR in the inventory, so a real gap in the inventory is still visible in
    the POA instead of reading as 'no firewall'."""
    if firewall_row and firewall_row.get("firewall"):
        return str(firewall_row["firewall"]).strip()
    if _is_onprem_location(location):
        return ONPREM_FIREWALL
    return MANUAL


def _is_public_ip(value):
    try:
        raw_ip = str(value).split(",", 1)[0].strip().split("/", 1)[0]
        return bool(raw_ip) and ipaddress.ip_address(raw_ip).is_global
    except ValueError:
        return False


def compute_subnet_demand(df, ref):
    """
    Computes how many rows in the ticket target each destination subnet
    where an OCI Security List rule will actually be needed (excluding
    hosts with attached NSGs, invalid IPs, external destinations, etc.).
    """
    demand = {}
    if df is None or getattr(df, "empty", True):
        return demand
    for _, raw_row in df.iterrows():
        dst_ip = _get_field(raw_row, "Destination IP", "DestinationIP", "Dst IP", "Destination IP Address", "Destination IP/Range")
        if not dst_ip or not _is_valid_ip_or_cidr(dst_ip):
            continue
        sub = ref.find_subnet(dst_ip)
        if sub and sub.get("subnet_name"):
            dst_host = ref.find_host(dst_ip)
            if not (dst_host and dst_host.get("nsgs")):
                sname = sub["subnet_name"]
                demand[sname] = demand.get(sname, 0) + 1
    return demand


def enrich_row(raw_row, ritm_number, ref, subnet_demand=None):
    """
    raw_row: a dict-like (pandas Series or dict) for one row of the input CSV,
             using the INPUT_RITM_FORMAT column names:
             'Source IP', 'Destination IP', 'Destination Type', 'Destination Port', ...
    ritm_number: e.g. 'RITM1149978' - becomes the Rule Name.
    ref: an app.poa.lookup.ReferenceData instance.
    subnet_demand: optional dict mapping subnet_name -> total rules required by this ticket.
    """
    src_ip = _get_field(raw_row, "Source IP", "SourceIP", "Src IP", "Source IP Address", "Source IP/Range")
    dst_ip = _get_field(raw_row, "Destination IP", "DestinationIP", "Dst IP", "Destination IP Address", "Destination IP/Range")
    dst_fqdn = _get_field(raw_row, "Destination FQDN", "DestinationFQDN", "Destination URL", "URL", "FQDN")
    dst_type = _get_field(raw_row, "Destination Type", "DestinationType", "Dst Type")
    dst_port = _get_field(raw_row, "Destination Port", "DestinationPort", "Dst Port", "Port")

    # A value that isn't an IP/CIDR misses every lookup below and would other-
    # wise be reported with the same defaults as a genuine unclassified host.
    # Flag it instead, and skip the lookups so nothing is inferred from it.
    src_invalid = bool(src_ip) and not _is_valid_ip_or_cidr(src_ip)
    dst_invalid = bool(dst_ip) and not _is_valid_ip_or_cidr(dst_ip)
    src_usable = bool(src_ip) and not src_invalid
    dst_usable = bool(dst_ip) and not dst_invalid

    src_subnet = ref.find_subnet(src_ip) if src_usable else None
    dst_subnet = ref.find_subnet(dst_ip) if dst_usable else None
    destination_fw = ref.find_firewall(dst_ip) if dst_usable else None
    source_fw = ref.find_firewall(src_ip) if src_usable else None

    src_location = INVALID_IP if src_invalid else (ref.classify_location(src_ip) if src_ip else "")
    dst_location = INVALID_IP if dst_invalid else (ref.classify_location(dst_ip) if dst_ip else "")

    # The environment tag each IP belongs to (OCI / AWS / Azure / DC), derived
    # from the OCI inventory + CIDR/Firewall sheets. This is NOT an output
    # column - it was dropped from the Excel and the Word POA - but the firewall
    # and security-list decisions below still depend on it, so it is still
    # computed per row. See ReferenceData.classify_environment() for precedence.
    src_vrf = ref.classify_environment(src_ip) if src_usable else ""
    dst_vrf = ref.classify_environment(dst_ip) if dst_usable else ""

    whitelisting_required_oci = "Yes" if dst_subnet else "No"

    # OCI firewall whitelisting is needed whenever traffic crosses the OCI
    # perimeter in EITHER direction - inbound (on-premise/AWS/Azure/GCP -> OCI)
    # or outbound (OCI -> DC/AWS/Azure/anything else). Only OCI-to-OCI traffic
    # stays No, even when a firewall mapping exists in the merged inventory.
    src_fw_name = ""
    dst_fw_name = ""
    whitelisting_required_oci_fw = "No"
    source_is_external = src_vrf != "OCI"
    # The destination leg needs its own usable IP before its environment can be
    # trusted: dst_vrf is "" for a blank/invalid destination, which would other-
    # wise read as "not OCI" and trigger the firewall path on nothing.
    destination_is_external = dst_usable and dst_vrf != "OCI"
    public_ip_flow = _is_public_ip(src_ip) or _is_public_ip(dst_ip)
    source_is_public_or_akamai = (
        _is_public_ip(src_ip)
        or "akamai" in src_vrf.lower()
        or "akamai" in src_location.lower()
    )
    firewall_triggered = bool(dst_fqdn) or bool(dst_ip) and (
        source_is_external or destination_is_external or public_ip_flow
    )
    if firewall_triggered:
        # Each leg is mapped independently from its own IP: "Source Firewall
        # Name" always answers "which firewall does the SOURCE IP sit behind",
        # and "Destination Firewall Name" the same for the DESTINATION IP. A
        # leg with no IP to map - an FQDN destination has no destination IP -
        # stays blank rather than MANUAL, because there is nothing to look up
        # there; that flow is carried by the source firewall alone.
        if src_ip:
            src_fw_name = INVALID_IP if src_invalid else _firewall_name(source_fw, src_location)
        if dst_ip:
            dst_fw_name = INVALID_IP if dst_invalid else _firewall_name(destination_fw, dst_location)
        whitelisting_required_oci_fw = "Yes"

    entire_subnet = _is_entire_subnet(dst_ip)
    dst_subnet_inbound_sl = ""
    dst_nsg_inbound_sl = ""
    nsg_remark = ""

    # The NSG/Security-List host report is keyed on the exact destination IP
    # (one row per VM/load-balancer), so it is the most precise available
    # source for that IP's actual attached NSG(s) - check it before falling
    # back to the OCI subnet inventory's NSG_Count.
    dst_host = ref.find_host(dst_ip) if dst_ip else None

    # OCI source -> FQDN is handled by the source firewall and must not add a
    # direct OCI Security List or NSG rule. Public/Akamai -> OCI LB traffic is
    # allowed through the destination OCI Security List, never directly to a
    # public IP without the firewall path.
    public_to_oci = source_is_public_or_akamai and dst_vrf == "OCI" and dst_subnet

    # The destination isn't inside any OCI subnet, and isn't a host in the OCI
    # NSG/Security-List reports either - it's on-premise/DC, AWS, Azure, or a
    # network none of the inventories know. There is then no OCI subnet, no
    # Security List and no NSG to whitelist on, whichever direction the flow
    # runs (OCI egress included): "Whitelisting Required at OCI" is already No
    # for these rows, and the three OCI columns are left empty to match, so the
    # POA reports None rather than MANUAL. MANUAL would claim the reference
    # sheets have a gap an engineer should fill, but a non-OCI destination has
    # no OCI rule to find - the flow is carried by the firewall columns above.
    destination_outside_oci = not dst_subnet and not dst_host

    if dst_invalid:
        # Nothing to resolve: the destination cell never held an address.
        dst_subnet_inbound_sl = INVALID_IP
    elif dst_fqdn and src_subnet:
        pass
    elif destination_outside_oci:
        pass
    elif entire_subnet:
        # Destination given as a CIDR ("entire subnet"): evaluate all attached
        # security lists against rule capacity (limit 200) and ticket demand.
        required_rules = subnet_demand.get(dst_subnet.get("subnet_name"), 1) if (subnet_demand and dst_subnet) else 1
        dst_subnet_inbound_sl = ref.resolve_security_list(
            dst_subnet.get("security_lists"),
            vcn_name=dst_subnet.get("vcn_name"),
            required_rules=required_rules,
        )
    else:
        # Destination given as a single IP. Three separate output columns are
        # in play, and each holds exactly one kind of thing:
        #   - "DST Server NSG Inbound SL": only ever a real, already-attached
        #     NSG name (blank when the destination has none).
        #   - "DST Subnet Inbound SL": the Security List to use when there is
        #     no existing NSG - i.e. the actionable answer today.
        #   - "NSG Remark": the suggested name for an NSG that doesn't exist
        #     yet, or a note when we can't tell - a remark, never an answer.
        subnet_target_name = (dst_subnet.get("subnet_name") if dst_subnet else (dst_host.get("subnet_name") if dst_host else None))
        required_rules = subnet_demand.get(subnet_target_name, 1) if (subnet_demand and subnet_target_name) else 1

        # Public/Akamai source -> OCI LB traffic always goes through a
        # Security List and never an NSG, so it gets no creation remark.
        if public_to_oci:
            raw_sl = (dst_host or {}).get("security_lists_raw") or ((dst_subnet or {}).get("security_lists") if dst_subnet else "")
            vcn = (dst_host or {}).get("vcn_name") or ((dst_subnet or {}).get("vcn_name") if dst_subnet else None)
            dst_subnet_inbound_sl = ref.resolve_security_list(
                raw_sl,
                vcn_name=vcn,
                required_rules=required_rules,
            )
        elif dst_host and dst_host.get("nsgs"):
            dst_nsg_inbound_sl = dst_host["nsgs"]
        elif dst_host:
            # Host is in the report but has no NSG attached.
            raw_sl = dst_host.get("security_lists_raw") or dst_host.get("security_lists")
            vcn = dst_host.get("vcn_name") or (dst_subnet.get("vcn_name") if dst_subnet else None)
            dst_subnet_inbound_sl = ref.resolve_security_list(
                raw_sl,
                vcn_name=vcn,
                required_rules=required_rules,
            )
            nsg_remark = f"Create new NSG: NSG-{dst_host.get('subnet_name')}-{dst_host.get('resource_name')}"
        elif dst_subnet:
            dst_subnet_inbound_sl = ref.resolve_security_list(
                dst_subnet.get("security_lists"),
                vcn_name=dst_subnet.get("vcn_name"),
                required_rules=required_rules,
            )
            nsg_count = _to_float(dst_subnet.get("nsg_count"))
            if nsg_count and nsg_count > 0:
                # An NSG exists somewhere on this subnet, but this IP isn't in
                # the host report, so we can't confirm it covers this host.
                nsg_remark = ("An NSG already exists on this subnet - confirm the exact NSG "
                              "for this IP in the OCI Console before creating a new one.")
            else:
                nsg_remark = f"Create new NSG: NSG-{dst_subnet.get('subnet_name')}-{dst_ip}"

        # If an existing security list was chosen but its rule count was not found in the audit sheet,
        # note it in the remark so the engineer can manually verify the count.
        if dst_subnet_inbound_sl and dst_subnet_inbound_sl not in (
            SL_MSG_RULE_COUNT_FULL,
            SL_MSG_NOT_FILLED_SINGLE,
            SL_MSG_NONE_FOUND,
            INVALID_IP,
        ):
            sl_vcn = (
                dst_subnet.get("vcn_name") if dst_subnet
                else (dst_host.get("vcn_name") if dst_host else None)
            )
            if not ref.is_security_list_audited(dst_subnet_inbound_sl, sl_vcn):
                if nsg_remark:
                    nsg_remark = f"{AUDIT_NOT_FOUND_REMARK}. {nsg_remark}"
                else:
                    nsg_remark = AUDIT_NOT_FOUND_REMARK

    if src_invalid or dst_invalid:
        routing = INVALID_IP
    else:
        routing = ref.classify_routing(src_ip, dst_ip) if (src_ip and dst_ip) else ""

    return {
        "Source IP": src_ip,
        "Destination IP": dst_ip,
        "Destination FQDN": dst_fqdn,
        "Destination Type": dst_type,
        "Destination Port": dst_port,
        "SRC Location": src_location,
        "DST Location": dst_location,
        "Whitelisting Required at OCI": whitelisting_required_oci,
        "Firewall Whitelisting": whitelisting_required_oci_fw,
        "Source Firewall Name": src_fw_name,
        "Destination Firewall Name": dst_fw_name,
        "Rule Name": ritm_number,
        "SRC Subnet Name": (src_subnet["subnet_name"] if src_subnet else ""),
        "DST Subnet Name": (dst_subnet["subnet_name"] if dst_subnet else ""),
        "DST Subnet Inbound SL (If DST is Entire Subnet)": dst_subnet_inbound_sl,
        "DST Server NSG Inbound SL (If DST is Single IP)": dst_nsg_inbound_sl,
        "NSG Remark": nsg_remark,
        "Routing Availibility": routing,
        "Input Validation": _validation_message(src_invalid, dst_invalid),
    }
