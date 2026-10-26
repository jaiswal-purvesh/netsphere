"""
poa/lookup.py
-------------
Ported from the standalone RITM-POA tool's `poa_lookup.py`, adapted to load
reference inventory sheets from **in-memory bytes** (uploaded through the
API and stored in the `poa_reference_files` table) rather than local file
paths — see app/models/poa.py's PoaReferenceFile. The lookup logic itself
(CIDR/IP matching, location/environment classification, firewall mapping,
security-list resolution, routing classification) is unchanged from the
original tool.

This module has NO hardcoded assumptions about your environment beyond what
is documented in each function's docstring -- read those before trusting the
output in production, especially:
  - environment tag            -> classify_environment() returns OCI / AWS /
                                   Azure / DC for an IP. It is no longer written
                                   to the Excel or the Word POA (the SRC VRF and
                                   DST VRF columns were removed), but the
                                   firewall and security-list decisions in
                                   poa/enrich.py still depend on it. See that
                                   method's docstring for the exact logic.
  - DST Server NSG Inbound SL  -> looked up first, by exact IP, in the OCI
                                   UAT/PROD NSG-Security-List host reports
                                   (one row per VM/load-balancer IP), which
                                   name the actual attached NSG(s). This
                                   column only ever holds an NSG (real or, if
                                   the subnet inventory's NSG_Count says one
                                   exists but the host report doesn't name it,
                                   "manual"). Whenever no NSG applies at all,
                                   the answer is a security list instead, and
                                   that goes to the "DST Subnet Inbound SL"
                                   column, not this one - see
                                   poa/enrich.py:enrich_row for the exact
                                   per-case routing.
  - Source / Destination Firewall Name
                                -> two independent columns, each matched from
                                   the CIDR_Firewall_Inventory sheet
                                   (CIDR -> Firewall) using its OWN leg's IP:
                                   the source IP for "Source Firewall Name",
                                   the destination IP for "Destination Firewall
                                   Name". A leg with no IP to map (an FQDN
                                   destination) stays blank; a leg whose IP the
                                   inventory doesn't cover reads MANUAL. See
                                   KNOWN_OCI_FIREWALLS.
    - Routing Availability       -> OCI-to-OCI is available via DRG; an
                                     on-prem/OCI leg remains verification-required.
    - Network IPAM               -> on-prem CIDRs are matched to their IPAM Name
                                     and VRF for source location/environment.
"""
from __future__ import annotations

import io
import ipaddress
import os
import re

import pandas as pd

# Messages when evaluating Security List capacity
SL_MSG_RULE_COUNT_FULL = "No security list due to rule count is full"
SL_MSG_NOT_FILLED_SINGLE = "Ticket is not filled in single security list"
SL_MSG_NONE_FOUND = "No non-default Security List found"
AUDIT_NOT_FOUND_REMARK = "Audit count not found - verify count manually for the given security list"

# OCI default security lists contain InfraTool in their name, but exports may
# place that text at either end and use underscores, hyphens, or a plural form.
INFRA_TOOL_TOKEN = "infratool"

# The only OCI perimeter firewalls currently in use. Used only to flag (in the
# console log) a CIDR_Firewall_Inventory row whose Firewall value doesn't match
# one of these - it does NOT restrict which values can be returned, so a new
# firewall added to the sheet later still comes through correctly.
KNOWN_OCI_FIREWALLS = [
    "BFL-OCI-HYD-DR-DG",
    "BFL-OCI-MUM-PROD-DG",
    "BFLIUAT-OCI-PA-NGFW",
]


def get_candidate_security_lists(sl_field):
    """
    Given a subnet's or host's raw Security_Lists cell (comma-separated names),
    drop the default InfraTool security list(s) (e.g. InfraTool_SL, InfraTools_SL1,
    or SL_InfraTools-part02) and OCI default lists, and return the remaining candidate
    names as a list of strings in their original order.
    """
    if sl_field is None or pd.isna(sl_field):
        return []
    items = [s.strip() for s in str(sl_field).split(",") if s.strip()]
    return [
        s for s in items
        if INFRA_TOOL_TOKEN not in re.sub(r"[^a-z0-9]", "", s.lower())
        and not re.search(r"(?:^|[^a-z])default(?:[^a-z]|$)", s.lower())
    ]


def _filter_security_lists(sl_field):
    """
    Backwards-compatible helper: returns the first candidate security list name or "".
    """
    kept = get_candidate_security_lists(sl_field)
    return kept[0] if kept else ""


def _filter_nsgs(nsg_field):
    """
    Given a host's raw Attached_NSGs cell (comma-separated NSG names, from the
    per-VM/load-balancer NSG/Security-List host report), drop the default
    InfraTool NSG (e.g. InfraTools_NSG) attached to every host by default, and
    return the remaining names as a clean comma-separated string. Unlike
    _filter_security_lists this keeps *all* remaining names (not just the
    first) since a single host commonly has more than one custom NSG attached.
    Returns "" if nothing is left after filtering (or the field was empty).
    """
    if nsg_field is None or pd.isna(nsg_field):
        return ""
    items = [s.strip() for s in str(nsg_field).split(",") if s.strip()]
    kept = [
        s for s in items
        if INFRA_TOOL_TOKEN not in re.sub(r"[^a-z0-9]", "", s.lower())
        and not re.search(r"(?:^|[^a-z])default(?:[^a-z]|$)", s.lower())
    ]
    return ", ".join(kept)


def _is_dr_subnet(subnet):
    """Return whether an inventory subnet belongs to a DR VCN or route table."""
    identity = " ".join(
        str(subnet.get(field) or "")
        for field in ("vcn_name", "route_table")
    ).lower()
    return bool(re.search(r"(?:^|[^a-z])dr(?:$|[^a-z])", identity))


def _to_ip(value):
    """Best-effort parse of a string into an ipaddress.IPv4Address. Returns None on failure."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "null":
        return None
    try:
        # strip a /32 etc. if present, we just want the host address here
        if "/" in s:
            s = s.split("/")[0]
        return ipaddress.ip_address(s)
    except ValueError:
        return None


def _to_networks(cidr_field):
    """A cell can contain one CIDR or a list of CIDRs separated by comma,
    semicolon, newline, or whitespace (real inventory exports use all of
    these inconsistently). Returns list of ip_network; unparsable/garbage
    tokens are silently skipped rather than crashing the whole load."""
    if cidr_field is None:
        return []
    raw = str(cidr_field)
    parts = re.split(r"[,\n;]+", raw)
    nets = []
    for part in parts:
        for token in part.split():
            token = token.strip()
            if not token:
                continue
            try:
                nets.append(ipaddress.ip_network(token, strict=False))
            except ValueError:
                continue
    return nets


def _normalize_columns(df, wanted_columns):
    """
    Renames df's columns in-place (returns the same df) so that any column
    whose name matches a `wanted_columns` entry case-/whitespace-insensitively
    (e.g. ' subnet_cidr', 'Subnet CIDR', 'SUBNET_CIDR') is renamed to the
    exact expected spelling. Real exports of these sheets are not always
    byte-for-byte consistent in header spelling - this stops that alone from
    causing every row to be skipped as 'missing expected columns'.
    """
    rename = {}
    norm_wanted = {w.strip().lower().replace(" ", "_"): w for w in wanted_columns}
    for col in df.columns:
        norm = str(col).replace("﻿", "").strip().lower().replace(" ", "_")
        if norm in norm_wanted and col != norm_wanted[norm]:
            rename[col] = norm_wanted[norm]
    if rename:
        df = df.rename(columns=rename)
    return df


class ReferenceFile:
    """A reference inventory as bytes + its original filename (used only to
    infer the format: .csv / .xlsx / .xls / .ods). Mirrors what
    PoaReferenceFile stores in the DB — kept as a tiny separate type so
    ReferenceData doesn't need to import the SQLAlchemy model."""

    __slots__ = ("filename", "content")

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.content = content


class ReferenceData:
    """
    Holds parsed lookup tables built from:
      - OCI UAT inventory sheet   (Subnet_CIDR -> Subnet_Name / VCN_Name / Security_Lists / ...)
      - OCI PROD inventory sheet  (same columns as UAT)
    - Merged CIDR/Firewall inventory ("CIDR_Firewall_Inventory" sheet: CIDR -> Firewall/Environment)
    - Network IPAM CSV (Address -> Name / VRF for on-prem networks)
      - OCI UAT/PROD NSG-Security-List host reports (one row per VM/load-balancer
        IP -> its Attached_NSGs / Subnet_Security_Lists). Exact-IP lookups
        against these take priority over the OCI subnet inventory's NSG_Count
        for a destination IP, since they name the actual NSG(s) instead of
        just flagging that one exists.

    Each `*_file` constructor argument is a `ReferenceFile` (bytes + filename)
    or None when that reference hasn't been uploaded yet — every field it
    would have supplied then reads MANUAL ENTRY REQUIRED / falls back to the
    on-prem default, exactly as when the standalone CLI tool's config.json
    pointed at a path that didn't exist.
    """

    def __init__(
        self, uat_file: ReferenceFile | None = None, prod_file: ReferenceFile | None = None,
        cidr_firewall_file: ReferenceFile | None = None, ipam_file: ReferenceFile | None = None,
        uat_host_file: ReferenceFile | None = None, prod_host_file: ReferenceFile | None = None,
        security_list_audit_files: list[ReferenceFile] | None = None,
    ):
        self.subnet_rows = []      # list of dicts, one per OCI subnet
        self.firewall_rows = []    # list of dicts, one per CIDR->Firewall mapping row
        self.ipam_rows = []        # list of dicts, one per on-prem IPAM CIDR
        self.host_by_ip = {}       # ip string -> dict, one per VM/LB IP from the NSG/SL host reports
        self.sl_audit = {}         # (vcn_lower, sl_lower) -> audit info dict
        self.sl_audit_by_name = {} # sl_lower -> audit info dict
        self.warnings: list[str] = []

        self._load_oci_inventory(uat_file, environment_label="UAT")
        self._load_oci_inventory(prod_file, environment_label="PROD")
        self._load_cidr_firewall(cidr_firewall_file)
        self._load_ipam(ipam_file)
        self._load_host_inventory(uat_host_file, environment_label="UAT")
        self._load_host_inventory(prod_host_file, environment_label="PROD")
        self._load_security_list_audit(security_list_audit_files or [])

    # ---------- loaders ----------

    def _warn(self, message: str) -> None:
        self.warnings.append(message)

    def _read_any(self, ref_file: ReferenceFile, sheet_name=None):
        """Reads .csv, .xlsx, .xls, or .ods transparently from in-memory bytes."""
        ext = os.path.splitext(ref_file.filename)[1].lower()
        buf = io.BytesIO(ref_file.content)

        if ext == ".csv":
            try:
                return pd.read_csv(buf, encoding="utf-8-sig")
            except UnicodeDecodeError:
                buf.seek(0)
                return pd.read_csv(buf, encoding="latin1")

        engine = "odf" if ext == ".ods" else None
        if sheet_name is not None:
            try:
                return pd.read_excel(buf, sheet_name=sheet_name, engine=engine)
            except Exception:
                buf.seek(0)
                return pd.read_excel(buf, sheet_name=0, engine=engine)

        return pd.read_excel(buf, sheet_name=0, engine=engine)

    def _load_oci_inventory(self, ref_file, environment_label):
        if not ref_file:
            return
        try:
            df = self._read_any(ref_file)
        except Exception as e:
            self._warn(f"Could not read OCI {environment_label} inventory '{ref_file.filename}': {e}")
            return

        required = ["Subnet_CIDR", "Subnet_Name", "VCN_Name", "VCN_CIDR"]
        df = _normalize_columns(df, required + [
            "Compartment_Name", "Region", "Route_Table", "Security_Lists", "NSG_Count",
        ])
        missing = [c for c in required if c not in df.columns]
        if missing:
            self._warn(f"'{ref_file.filename}' is missing expected columns {missing} - skipped.")
            return

        count = 0
        for _, row in df.iterrows():
            nets = _to_networks(row.get("Subnet_CIDR"))
            if not nets:
                continue
            for net in nets:
                self.subnet_rows.append({
                    "network": net,
                    "subnet_name": row.get("Subnet_Name"),
                    "vcn_name": row.get("VCN_Name"),
                    "vcn_cidr": row.get("VCN_CIDR"),
                    "compartment": row.get("Compartment_Name"),
                    "region": row.get("Region"),
                    "route_table": row.get("Route_Table"),
                    "security_lists": row.get("Security_Lists"),
                    "nsg_count": row.get("NSG_Count"),
                    "environment": environment_label,
                })
                count += 1

    def _load_cidr_firewall(self, ref_file):
        if not ref_file:
            return
        try:
            df = self._read_any(ref_file, sheet_name="CIDR_Firewall_Inventory")
        except Exception as e:
            self._warn(f"Could not read CIDR/Firewall inventory '{ref_file.filename}': {e}")
            return

        required = ["CIDR", "Firewall"]
        df = _normalize_columns(df, required + ["Name", "Environment"])
        missing = [c for c in required if c not in df.columns]
        if missing:
            self._warn(f"'{ref_file.filename}' is missing expected columns {missing} - skipped.")
            return

        count = 0
        for _, row in df.iterrows():
            nets = _to_networks(row.get("CIDR"))
            if not nets:
                continue
            for net in nets:
                self.firewall_rows.append({
                    "network": net,
                    "name": row.get("Name"),
                    "firewall": row.get("Firewall"),
                    "environment": row.get("Environment"),
                })
                count += 1
        if count == 0:
            self._warn(
                f"'{ref_file.filename}' has no data rows yet - Source/Destination Firewall "
                f"Name fields will come back blank until it's populated.",
            )

    def _load_ipam(self, ref_file):
        if not ref_file:
            return
        try:
            df = self._read_any(ref_file)
        except Exception as e:
            self._warn(f"Could not read Network IPAM inventory '{ref_file.filename}': {e}")
            return

        df = _normalize_columns(df, ["Address", "Name", "VRF"])
        missing = [column for column in ("Address", "Name") if column not in df.columns]
        if missing:
            self._warn(f"'{ref_file.filename}' is missing expected IPAM columns {missing} - skipped.")
            return

        for _, row in df.iterrows():
            name = "" if pd.isna(row.get("Name")) else str(row.get("Name")).strip()
            vrf = "" if pd.isna(row.get("VRF")) else str(row.get("VRF")).strip()
            for network in _to_networks(row.get("Address")):
                self.ipam_rows.append({"network": network, "name": name, "vrf": vrf})

    def _load_host_inventory(self, ref_file, environment_label):
        """Loads one OCI NSG/Security-List host report: one row per scanned
        VM/load-balancer IP, giving its exact Attached_NSGs and
        Subnet_Security_Lists. Duplicate IP rows in the sheet keep the first
        occurrence."""
        if not ref_file:
            return
        try:
            df = self._read_any(ref_file)
        except Exception as e:
            self._warn(f"Could not read NSG/Security List host report '{ref_file.filename}': {e}")
            return

        required = ["IP_Address", "Resource_Name", "Resource_Type"]
        df = _normalize_columns(df, required + [
            "Attached_NSGs", "Subnet_Security_Lists", "VCN_Name", "Subnet_Name",
        ])
        missing = [c for c in required if c not in df.columns]
        if missing:
            self._warn(f"'{ref_file.filename}' is missing expected columns {missing} - skipped.")
            return

        for _, row in df.iterrows():
            ip = _to_ip(row.get("IP_Address"))
            if ip is None:
                continue
            key = str(ip)
            if key in self.host_by_ip:
                continue
            self.host_by_ip[key] = {
                "resource_name": row.get("Resource_Name"),
                "resource_type": row.get("Resource_Type"),
                "vcn_name": row.get("VCN_Name"),
                "subnet_name": row.get("Subnet_Name"),
                "nsgs": _filter_nsgs(row.get("Attached_NSGs")),
                "security_lists": _filter_security_lists(row.get("Subnet_Security_Lists")),
                "security_lists_raw": row.get("Subnet_Security_Lists"),
                "environment": environment_label,
            }

    def _load_security_list_audit(self, ref_files: list[ReferenceFile]):
        if not ref_files:
            return
        total_loaded = 0
        for ref_file in ref_files:
            try:
                df = self._read_any(ref_file)
            except Exception as e:
                self._warn(f"Could not read security list audit sheet '{ref_file.filename}': {e}")
                continue

            required = ["SecurityList", "TotalRules"]
            df = _normalize_columns(df, required + ["VCN", "RuleLimit", "RemainingHeadroom"])
            missing = [c for c in required if c not in df.columns]
            if missing:
                self._warn(f"'{ref_file.filename}' is missing expected columns {missing} - skipped.")
                continue

            for _, row in df.iterrows():
                sl_name = str(row.get("SecurityList", "")).strip()
                if not sl_name or sl_name.lower() == "nan":
                    continue
                vcn_name = str(row.get("VCN", "")).strip()
                total_rules = int(row.get("TotalRules", 0)) if pd.notna(row.get("TotalRules")) else 0
                rule_limit = int(row.get("RuleLimit", 200)) if pd.notna(row.get("RuleLimit")) else 200
                headroom = int(row.get("RemainingHeadroom", rule_limit - total_rules)) if pd.notna(row.get("RemainingHeadroom")) else (rule_limit - total_rules)

                info = {
                    "security_list": sl_name,
                    "vcn": vcn_name,
                    "total_rules": total_rules,
                    "rule_limit": rule_limit,
                    "remaining_headroom": headroom,
                }
                if vcn_name:
                    self.sl_audit[(vcn_name.lower(), sl_name.lower())] = info
                sl_key = sl_name.lower()
                if sl_key not in self.sl_audit_by_name or self.sl_audit_by_name[sl_key]["total_rules"] < total_rules:
                    self.sl_audit_by_name[sl_key] = info
                total_loaded += 1

    # ---------- lookups ----------

    def find_subnet(self, ip):
        """Returns the most specific (smallest) matching OCI subnet dict, or None."""
        ip = _to_ip(ip)
        if ip is None:
            return None
        matches = [r for r in self.subnet_rows if ip in r["network"]]
        if not matches:
            return None
        return min(matches, key=lambda r: -r["network"].prefixlen)

    def find_firewall(self, ip):
        """Returns the most specific matching CIDR->Firewall dict, or None."""
        ip = _to_ip(ip)
        if ip is None:
            return None
        matches = [r for r in self.firewall_rows if ip in r["network"]]
        if not matches:
            return None
        return min(matches, key=lambda r: -r["network"].prefixlen)

    def find_ipam(self, ip):
        """Returns the most specific matching on-prem Network IPAM record, or None."""
        ip = _to_ip(ip)
        if ip is None:
            return None
        matches = [r for r in self.ipam_rows if ip in r["network"]]
        if not matches:
            return None
        return min(matches, key=lambda r: -r["network"].prefixlen)

    def classify_location(self, ip):
        """
        Returns a human-readable location string for an IP, using (in order):
          1. The matching OCI subnet's VCN/Environment (most precise).
             2. The matching CIDR/Firewall inventory's Environment.
             3. The matching Network IPAM Name only when the merged inventory
                 has no usable environment match.
             4. 'On-Prem / Unclassified' as a fallback.
        """
        subnet = self.find_subnet(ip)
        if subnet:
            return f"OCI-{subnet['environment']} ({subnet['vcn_name']})"
        fw = self.find_firewall(ip)
        if fw and fw.get("environment"):
            return str(fw["environment"])
        ipam = self.find_ipam(ip)
        if ipam and ipam.get("name"):
            return f"On-Prem ({ipam['name']})"
        return "On-Prem / Unclassified"

    def classify_environment(self, ip):
        """
        Returns the VRF-style environment tag for an IP: 'OCI', 'AWS', 'Azure',
        or the Network IPAM VRF for a known on-prem network, derived purely
        from the reference inventories - never a manual/blank value:
          1. If the IP falls inside any OCI subnet from the OCI inventory
             sheets -> 'OCI'.
             2. Else, if the IP falls inside a CIDR from the CIDR_Firewall
             inventory sheet, read that row's Environment column and map it:
             contains 'aws' -> 'AWS', 'azure' -> 'Azure', 'oci' -> 'OCI',
             otherwise the Environment value itself is returned as-is.
          3. Else, if the IP matches Network IPAM, return its VRF.
          4. Otherwise (no match anywhere) -> 'DC'.
        """
        if self.find_subnet(ip):
            return "OCI"
        fw = self.find_firewall(ip)
        if fw and fw.get("environment"):
            env = str(fw["environment"]).strip()
            env_lower = env.lower()
            if "aws" in env_lower:
                return "AWS"
            if "azure" in env_lower:
                return "Azure"
            if "oci" in env_lower:
                return "OCI"
            return env if env else "DC"
        ipam = self.find_ipam(ip)
        if ipam and ipam.get("vrf"):
            return ipam["vrf"]
        return "DC"

    def find_host(self, ip):
        """Returns the VM/load-balancer host record for `ip` from the NSG/
        Security-List host reports (exact IP match, not CIDR), or None if
        `ip` wasn't one of the scanned hosts. This is the most precise source
        available for a destination IP's actual attached NSG(s), so callers
        should look here before falling back to the OCI subnet inventory's
        NSG_Count."""
        ip = _to_ip(ip)
        if ip is None:
            return None
        return self.host_by_ip.get(str(ip))

    def resolve_security_list(self, sl_field, vcn_name=None, required_rules=1):
        """
        Intelligently resolves which security list to use when a subnet or host
        has one or more security lists attached.

        Evaluation rules:
          1. Filter out InfraTool default lists and OCI default lists.
          2. Check rule capacity in self.sl_audit:
             - An SL is full if TotalRules >= 200 or RemainingHeadroom <= 0.
             - An SL is feasible if it is not full and RemainingHeadroom >= required_rules.
          3. Return the first feasible SL that can accommodate all required_rules for this ticket.
          4. If no SL is feasible:
             - If ALL attached candidate SLs are full (TotalRules >= 200 / RemainingHeadroom <= 0):
               returns 'No security list due to rule count is full'.
             - If some SLs have space, but none can fit the entire ticket request:
               returns 'Ticket is not filled in single security list'.
             - If no candidates were found at all:
               returns 'No non-default Security List found'.
        """
        candidates = get_candidate_security_lists(sl_field)
        if not candidates:
            return SL_MSG_NONE_FOUND

        evaluated = []
        for sl_name in candidates:
            info = None
            if vcn_name:
                info = self.sl_audit.get((str(vcn_name).lower().strip(), sl_name.lower().strip()))
            if not info:
                info = self.sl_audit_by_name.get(sl_name.lower().strip())

            if info:
                total_rules = info["total_rules"]
                rule_limit = info["rule_limit"]
                headroom = info["remaining_headroom"]
            else:
                total_rules = 0
                rule_limit = 200
                headroom = 200

            is_full = (total_rules >= rule_limit) or (headroom <= 0)
            is_feasible = (not is_full) and (headroom >= required_rules)
            evaluated.append({
                "name": sl_name,
                "total_rules": total_rules,
                "rule_limit": rule_limit,
                "headroom": headroom,
                "is_full": is_full,
                "is_feasible": is_feasible,
            })

        for item in evaluated:
            if item["is_feasible"]:
                return item["name"]

        if all(item["is_full"] for item in evaluated):
            return SL_MSG_RULE_COUNT_FULL

        return SL_MSG_NOT_FILLED_SINGLE

    def is_security_list_audited(self, sl_name, vcn_name=None):
        """Returns True if the security list is found in the audit sheet."""
        if not sl_name:
            return False
        sl_str = str(sl_name).strip()
        if vcn_name and (str(vcn_name).lower().strip(), sl_str.lower()) in self.sl_audit:
            return True
        return sl_str.lower() in self.sl_audit_by_name

    def security_list_for_ip(self, ip, required_rules=1):
        """
        Convenience wrapper: finds the OCI subnet containing `ip` and returns
        its best security list name (Infra defaults excluded, capacity checked).
        Returns None if the IP isn't inside any known OCI subnet at all.
        """
        subnet = self.find_subnet(ip)
        if not subnet:
            return None
        return self.resolve_security_list(
            subnet.get("security_lists"),
            vcn_name=subnet.get("vcn_name"),
            required_rules=required_rules,
        )

    def classify_routing(self, src_ip, dst_ip):
        """
        Returns routing status based on the known network boundaries:
          - Both IPs land in the same VCN -> local VCN routing is available.
          - Production-to-DR traffic -> use the RPC connection.
          - Other OCI-to-OCI traffic -> routing is available through the DRG.
          - Either IP is outside OCI -> verify the on-prem route, firewall,
            FastConnect link, and DRG route before sign-off.
        """
        s = self.find_subnet(src_ip)
        d = self.find_subnet(dst_ip)
        if not s or not d:
            return "To Be Verified (On-Prem route, firewall, FastConnect, and DRG route)"
        if s["vcn_name"] == d["vcn_name"]:
            return "Yes (Same VCN local routing)"
        if (
            s.get("environment") == "PROD"
            and d.get("environment") == "PROD"
            and _is_dr_subnet(s) != _is_dr_subnet(d)
            and (_is_dr_subnet(s) or _is_dr_subnet(d))
        ):
            return "Yes (Production to DR via RPC)"
        return "Yes (OCI to OCI via DRG)"
