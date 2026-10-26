"""Phase 6 intake — parses a ServiceNow RITM connectivity-request export
(the format the network team actually receives: one row per requested
firewall/NSG/SG/SL rule, columns like "Source IP", "Destination IP",
"Destination Port", "Technical Justification") into `IntakeRow` objects
`app/services/security_policy_resolve.py` then resolves against real
network inventory and turns into `FwIntent` rows.

This is deliberately a *separate* parser from `app/services/
poa_firewall_parser.py`, not a mode of it: that module parses an
already-written Plan of Action document (Panorama/FortiGate rule-shaped
columns — device group, zones, App-ID) that an engineer authored *after*
deciding the change. This module parses the raw connectivity *request* that
arrives before any of that exists — the "F1: Accept a connectivity request…
via CSV batch" input `claude/firewall-policy-automation-design.md` §1.1 and
Appendix A "PHASE 0 — INTAKE" describe, several steps upstream of a PoA.
The two column vocabularies do not overlap enough to share one synonym
table without one of them silently swallowing the other's fields.

Column matching is tolerant (case/whitespace-insensitive, a fixed synonym
list per field) because the exact header text drifts between ServiceNow
catalog item exports over time; matching by *position* was deliberately
rejected — a reordered export would then silently mis-map columns instead
of failing loudly.

Real, observed RITM export shape (RITM1151021.ods, 33 rows, single sheet):
  Actions | Source IP | Destination IP | Source System | Destination FQDN |
  Unable To Find Source System | Destination System | Source System Name |
  Unable To Find Destination System | Destination Type | Destination
  System Name | Destination Port | Technical Justification | SSL Bypass

Observations this parser encodes as deliberate handling, not guesses:
  - "Actions" is blank in the real export for every row — every request in
    this catalog item is an allow (there's no deny workflow through this
    form), so a blank/unrecognized action defaults to "allow" rather than
    being rejected.
  - "Source IP" is not always an IP: several rows carry an AD-style
    identifier ("bfl\\it_pennant_bfl", "it_pennant_partner") the requester
    used instead of a CIDR. These are recorded as `source_raw` verbatim and
    flagged unresolved (`source_is_identifier=True`) rather than guessed at
    — turning a domain\\user string into a CIDR is exactly the kind of
    silent wrong-address bug §3.4/§5 of the design doc warns about; a human
    has to supply the real CIDR (or the batch just carries it through as
    an unresolved row for manual follow-up).
  - "Destination Port" is frequently a comma-separated list
    ("7080,8080,8090,33022") — expanded to one `PortSpec` per value, never
    silently truncated to the first.
  - "Destination Type" holds the protocol ("TCP" in every observed row) —
    mapped to `protocol`, not to be confused with `destination_type` in
    poa_firewall_parser's vocabulary (that field means something different
    there: an address-object type). Unset/unrecognized defaults to "tcp".
  - A destination can be an FQDN instead of an IP (row 32:
    "dmsappuat.bajajfinserv.in") — carried as `destination_fqdn` and
    flagged unresolved (no DNS resolution is performed here; see this
    module's `UNRESOLVED_REASON_FQDN`).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from app.services.cidr import CidrError, ip_to_int, parse_cidr

UNRESOLVED_REASON_SOURCE_IDENTIFIER = "source is not an IP/CIDR (looks like a directory identifier) — needs manual CIDR mapping"
UNRESOLVED_REASON_FQDN = "destination is an FQDN, not an IP — needs manual resolution (no DNS lookup performed)"
UNRESOLVED_REASON_NO_DESTINATION = "no destination IP or FQDN on this row"
UNRESOLVED_REASON_NO_PORT = "no destination port on this row"

# Header synonyms, matched case/whitespace-insensitively. Kept flat (not
# regex) per poa_firewall_parser's precedent — a new alias is a one-line
# addition here, not a parser change.
_COLUMN_SYNONYMS: dict[str, list[str]] = {
    "action": ["actions", "action"],
    "source_ip": ["source ip", "source", "source ip/cidr"],
    "destination_ip": ["destination ip", "destination", "destination ip/cidr"],
    "source_system": ["source system"],
    "destination_fqdn": ["destination fqdn", "destination hostname"],
    "source_system_name": ["source system name"],
    "destination_system": ["destination system"],
    "destination_system_name": ["destination system name"],
    "destination_type": ["destination type", "protocol"],
    "destination_port": ["destination port", "port", "destination ports"],
    "technical_justification": ["technical justification", "justification", "business justification"],
    "ssl_bypass": ["ssl bypass"],
}


def _normalize_header(raw: str) -> str:
    return re.sub(r"\s+", " ", str(raw).strip().lower())


def _build_reverse_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for canon, aliases in _COLUMN_SYNONYMS.items():
        for alias in aliases:
            out[_normalize_header(alias)] = canon
    return out


_REVERSE_MAP = _build_reverse_map()


class IntakeParseError(Exception):
    """The file could not be read as a RITM sheet at all (wrong/corrupt
    format, no recognizable column headers) — distinct from a single row
    being unresolvable, which is recorded on the row, not raised."""


@dataclass
class PortSpec:
    proto: str
    port_low: int
    port_high: int


@dataclass
class IntakeRow:
    row_number: int  # 1-based, matching the sheet (header row is row 1)

    action: str = "allow"
    source_raw: str = ""
    source_is_identifier: bool = False  # True when source_raw isn't a parseable IP/CIDR
    destination_ip: str | None = None
    destination_fqdn: str | None = None
    ports: list[PortSpec] = field(default_factory=list)
    protocol: str = "tcp"
    justification: str = ""
    ssl_bypass: bool | None = None
    source_system: str = ""
    destination_system: str = ""

    unresolved_reasons: list[str] = field(default_factory=list)

    @property
    def is_resolvable(self) -> bool:
        return not self.unresolved_reasons

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "action": self.action,
            "source_raw": self.source_raw,
            "source_is_identifier": self.source_is_identifier,
            "destination_ip": self.destination_ip,
            "destination_fqdn": self.destination_fqdn,
            "ports": [{"proto": p.proto, "port_low": p.port_low, "port_high": p.port_high} for p in self.ports],
            "protocol": self.protocol,
            "justification": self.justification,
            "ssl_bypass": self.ssl_bypass,
            "unresolved_reasons": self.unresolved_reasons,
        }


@dataclass
class ParsedIntake:
    rows: list[IntakeRow]
    source_format: str
    warnings: list[str] = field(default_factory=list)


def _to_bool(v) -> bool | None:
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "yes", "y", "1"):
        return True
    if s in ("false", "no", "n", "0"):
        return False
    return None


def _parse_ports(raw, protocol: str) -> list[PortSpec]:
    if raw is None or str(raw).strip() == "":
        return []
    proto = (protocol or "tcp").strip().lower()
    if proto not in ("tcp", "udp"):
        proto = "tcp"
    out: list[PortSpec] = []
    for token in re.split(r"[,;]", str(raw)):
        token = token.strip()
        if not token:
            continue
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", token)
        if m:
            out.append(PortSpec(proto=proto, port_low=int(m.group(1)), port_high=int(m.group(2))))
            continue
        if token.isdigit():
            n = int(token)
            out.append(PortSpec(proto=proto, port_low=n, port_high=n))
    return out


def _parse_source(raw) -> tuple[str, bool]:
    """Returns (source_raw, is_identifier). A source is treated as a real
    address when it parses as either a bare IPv4 or a CIDR; anything else
    (an AD path like "bfl\\it_pennant_bfl", a bare hostname-looking token)
    is flagged rather than coerced."""
    s = "" if raw is None else str(raw).strip()
    if not s:
        return s, True
    if "/" in s:
        try:
            parse_cidr(s)
            return s, False
        except CidrError:
            return s, True
    try:
        ip_to_int(s)
        return s, False
    except CidrError:
        return s, True


def _row_to_intake_row(row_number: int, values: dict[str, object]) -> IntakeRow:
    action_raw = str(values.get("action") or "").strip().lower()
    action = "deny" if action_raw in ("deny", "block", "drop", "reject") else "allow"

    source_raw, source_is_identifier = _parse_source(values.get("source_ip"))

    destination_ip_raw = values.get("destination_ip")
    destination_ip = str(destination_ip_raw).strip() if destination_ip_raw not in (None, "") else None
    if destination_ip:
        try:
            (parse_cidr(destination_ip) if "/" in destination_ip else ip_to_int(destination_ip))
        except CidrError:
            # Not a valid address after all (e.g. stray text) — treat as absent
            # and let the FQDN/absent-destination path report it clearly.
            destination_ip = None

    destination_fqdn_raw = values.get("destination_fqdn")
    destination_fqdn = str(destination_fqdn_raw).strip() if destination_fqdn_raw not in (None, "") else None

    protocol_raw = str(values.get("destination_type") or "").strip().lower()
    protocol = protocol_raw if protocol_raw in ("tcp", "udp", "icmp") else "tcp"

    ports = _parse_ports(values.get("destination_port"), protocol)

    justification = str(values.get("technical_justification") or "").strip()
    ssl_bypass = _to_bool(values.get("ssl_bypass"))

    r = IntakeRow(
        row_number=row_number, action=action, source_raw=source_raw, source_is_identifier=source_is_identifier,
        destination_ip=destination_ip, destination_fqdn=destination_fqdn, ports=ports, protocol=protocol,
        justification=justification, ssl_bypass=ssl_bypass,
        source_system=str(values.get("source_system") or "").strip(),
        destination_system=str(values.get("destination_system") or "").strip(),
    )

    if source_is_identifier:
        r.unresolved_reasons.append(UNRESOLVED_REASON_SOURCE_IDENTIFIER)
    if not destination_ip and not destination_fqdn:
        r.unresolved_reasons.append(UNRESOLVED_REASON_NO_DESTINATION)
    elif not destination_ip and destination_fqdn:
        r.unresolved_reasons.append(UNRESOLVED_REASON_FQDN)
    if not ports:
        r.unresolved_reasons.append(UNRESOLVED_REASON_NO_PORT)

    return r


def _rows_from_table(header: list[str], data_rows: list[list]) -> list[IntakeRow]:
    columns = [_REVERSE_MAP.get(_normalize_header(h)) if h is not None else None for h in header]
    if not any(columns):
        raise IntakeParseError(
            "No recognizable RITM column headers found. Expected columns such as "
            "'Source IP', 'Destination IP', 'Destination Port', 'Technical Justification'.",
        )
    out: list[IntakeRow] = []
    for idx, row in enumerate(data_rows):
        if not any(c not in (None, "") for c in row):
            continue
        values = {col: val for col, val in zip(columns, row) if col}
        out.append(_row_to_intake_row(row_number=idx + 2, values=values))  # +2: 1-based, header is row 1
    return out


def parse_csv(content: bytes) -> ParsedIntake:
    import csv

    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise IntakeParseError("Empty CSV file.")
    return ParsedIntake(rows=_rows_from_table(rows[0], rows[1:]), source_format="csv")


def parse_xlsx(content: bytes) -> ParsedIntake:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise IntakeParseError("Empty spreadsheet.")
    return ParsedIntake(rows=_rows_from_table(list(rows[0]), [list(r) for r in rows[1:]]), source_format="xlsx")


def parse_ods(content: bytes) -> ParsedIntake:
    import pandas as pd

    xls = pd.ExcelFile(io.BytesIO(content), engine="odf")
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0], engine="odf")
    header = [str(c) for c in df.columns]
    data_rows = [[None if pd.isna(v) else v for v in row] for row in df.itertuples(index=False, name=None)]
    if not header:
        raise IntakeParseError("Empty spreadsheet.")
    return ParsedIntake(rows=_rows_from_table(header, data_rows), source_format="ods")


_EXT_TO_PARSER = {
    ".csv": parse_csv,
    ".xlsx": parse_xlsx,
    ".xls": parse_xlsx,
    ".ods": parse_ods,
}


def parse_intake_file(content: bytes, filename: str | None) -> ParsedIntake:
    if filename:
        lower = filename.lower()
        for ext, fn in _EXT_TO_PARSER.items():
            if lower.endswith(ext):
                parsed = fn(content)
                if not parsed.rows:
                    raise IntakeParseError("No data rows found after the header.")
                return parsed
    raise IntakeParseError(
        f"Unrecognized file type for {filename or 'the uploaded file'!r}. "
        "Supported: .xlsx, .csv, .ods.",
    )
