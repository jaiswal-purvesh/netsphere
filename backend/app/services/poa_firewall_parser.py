"""POA Parser / Policy Extraction Engine (#4, #23) — the piece that makes
the Plan of Action the single source of truth. An engineer writes the
firewall rule(s) into the POA exactly once, in whatever format they already
use; this module turns that into validated `ExtractedRule` objects (plus
one `ExtractedHeader`) which app/api/v1/endpoints/fw_poa_documents.py then
turns into an `FwPoaDocument` + one `FwIntent` per rule — never re-typed by
hand.

Formats supported, all deterministic (no network calls, no AI):
  - JSON / YAML — a single normalized-policy-shaped object (the example in
    the ask), or {"header": {...}, "rules": [...]}.
  - CSV — one row per rule; header-level columns (poa_ref, change_ref, ...)
    repeated on every row are folded into one document header.
  - Word (.docx) / PDF — text (and, for .docx, table) extraction, then fed
    through the same key:value block parser as free text.
  - Excel (.xlsx) — a rule table (header row matched by column name) plus
    any stray key:value cells outside it for the document header.
  - Free text — "Key: value" line blocks, the style in the example POA
    ("Firewall: Palo Alto", "Source Zone: APP", ...). Multiple rule blocks
    in one document are split on the presence of a new rule-identifying
    field (rule_name/source/destination/action) after the first block.

Deliberately NOT implemented here: an AI-extraction fallback for prose that
doesn't parse as any of the above (per the ask's own §4/§21: "for
unstructured POAs, use an AI extraction layer... but never directly
execute AI-generated values without validation" and "AI must not
independently bypass schema validation"). Wiring a real LLM call belongs in
the API layer (it needs a model + prompt + human review UI, not a pure
parsing function), and every AI-produced field would still have to pass
through `ExtractedRule`'s validation below regardless — so the safe,
honest thing this phase ships is the deterministic path plus a clear
`UnrecognizedPoaFormat` error telling the engineer which structured format
to use instead, rather than a fake AI call that isn't actually wired to
anything. See this module's `AI_EXTRACTION_NOT_IMPLEMENTED` docstring.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from app.services.cidr import CidrError, parse_cidr

# --- field synonym table --------------------------------------------------
# Maps every spelling we've seen in the ask (and reasonable variants) to the
# canonical field name. Matching is case-insensitive and ignores surrounding
# whitespace/punctuation; a synonym list is deliberately flat text (not
# regex) so adding a new alias later is a one-line change.

HEADER_SYNONYMS: dict[str, list[str]] = {
    "poa_ref": ["poa id", "poa ref", "poa number", "poa_id"],
    "change_ref": ["change id", "change/request id", "change ref", "request id", "chg", "change number"],
    "snow_ticket": ["servicenow ticket", "servicenow ticket number", "snow ticket", "ticket number", "ticket"],
    "application_name": ["application name", "application"],
    "business_owner": ["business owner"],
    "technical_owner": ["technical owner"],
    "environment": ["environment"],
    "source_application": ["source application"],
    "destination_application": ["destination application"],
    "business_justification": ["business justification", "justification"],
    "implementation_window": ["implementation window", "change window"],
    "rollback_requirement": ["rollback requirement", "rollback plan", "rollback"],
}

RULE_SYNONYMS: dict[str, list[str]] = {
    "rule_id": ["rule id"],
    "rule_name": ["rule name"],
    "rule_description": ["rule description", "description"],
    "firewall_vendor": ["firewall", "firewall vendor", "vendor"],
    "management_platform": ["manager", "management platform", "platform", "firewall platform"],
    "firewall_hostname": ["firewall hostname", "hostname"],
    "management_ip": ["management ip", "management ip/fqdn", "mgmt ip"],
    "firewall_location": ["firewall location", "location"],
    "device_group": ["device group", "device_group"],
    "vdom": ["vdom"],
    "serial": ["serial", "serial number", "serial number/device group"],
    "cloud_account": ["cloud account", "cloud account/subscription/project", "subscription", "project"],
    "source_zone": ["source zone"],
    "destination_zone": ["destination zone"],
    "source": ["source", "source ip", "source ip/cidr", "source cidr"],
    "destination": ["destination", "destination ip", "destination ip/cidr", "destination cidr"],
    "source_address_object": ["source address object"],
    "destination_address_object": ["destination address object"],
    "source_port": ["source port"],
    "destination_port": ["destination port", "port"],
    "service": ["service"],
    "protocol": ["protocol"],
    "action": ["action"],
    "nat_requirement": ["nat requirement", "nat"],
    "logging": ["logging", "log at session end", "log requirement", "logging requirement"],
    "security_profile": ["security profile"],
    "url_filtering_profile": ["url filtering profile"],
    "ips_profile": ["ips profile"],
    "antivirus_profile": ["antivirus profile"],
    "ssl_inspection_profile": ["ssl inspection profile"],
    "qos_requirement": ["qos requirement", "qos"],
    "schedule": ["schedule"],
    "rule_position": ["rule position", "rule position/order", "position"],
    "expiry_date": ["expiry date", "expiry"],
    "business_justification": ["business justification", "justification"],
}
# NOTE: deliberately no bare "application" alias here — the ask uses
# "Application" for both the header's business application name and a
# rule's App-ID list, and a POA's free-text preamble ("Application: Payments
# App") almost always means the former. A rule's App-ID list is matched via
# "App-ID" specifically instead; see RULE_SYNONYMS["application"] below.
RULE_SYNONYMS["application_ids"] = ["app-id", "application id", "app id"]


def _normalize_key(raw: str) -> str:
    s = raw.strip().lower().rstrip(":").replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def _build_reverse_map(synonyms: dict[str, list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, aliases in synonyms.items():
        for alias in aliases:
            out[_normalize_key(alias)] = canonical
        out[_normalize_key(canonical.replace("_", " "))] = canonical
    return out


_HEADER_REVERSE = _build_reverse_map(HEADER_SYNONYMS)
_RULE_REVERSE = _build_reverse_map(RULE_SYNONYMS)

# Canonical names that are legitimately both a document-header field and a
# per-rule field — today just "business_justification" (a POA can carry an
# overall justification in its preamble AND a more specific one per rule).
# _parse_kv_lines uses this to decide which one a given "Business
# Justification:" line means, since the two can't share a single dict key.
_AMBIGUOUS_KEYS = set(HEADER_SYNONYMS) & set(RULE_SYNONYMS)


def _canonicalize(raw_key: str, reverse_map: dict[str, str]) -> str | None:
    return reverse_map.get(_normalize_key(raw_key))


# --- errors ----------------------------------------------------------------

class PoaParseError(Exception):
    """Raised when the document can't be parsed at all (wrong/corrupt
    format) — distinct from a validation failure on values that *did*
    parse (ExtractedRule raises pydantic's ValidationError for those,
    surfaced by the caller per §20's "IMPLEMENTATION BLOCKED" format)."""


class UnrecognizedPoaFormat(PoaParseError):
    def __init__(self, filename: str | None):
        super().__init__(
            f"Could not recognize a firewall rule structure in "
            f"{filename or 'the pasted text'}. Supported formats: JSON, YAML, "
            "CSV, an Excel rule table, a Word/PDF document containing "
            "'Key: value' lines (see the example POA format), or a plain-text "
            "key:value block. Free-form prose that doesn't follow one of "
            "these is not auto-extracted in this phase — see this module's "
            "AI_EXTRACTION_NOT_IMPLEMENTED note.",
        )


# Kept as a named, importable constant (rather than only a comment) so a
# future PR that wires a real LLM extraction call has one obvious place to
# point at and flip — and so `grep`ing for it from a test or a doc surfaces
# the decision, not just prose.
AI_EXTRACTION_NOT_IMPLEMENTED = (
    "AI-assisted extraction for unstructured prose is not wired in this "
    "phase. Every deterministic path below still runs extracted values "
    "through ExtractedRule's schema validation regardless of source, per "
    "the requirement that AI never bypasses validation — but there is, "
    "today, no model call to bypass it with. Convert the POA to one of the "
    "structured formats this parser supports, or add the AI layer as a "
    "pre-processing step that emits the same key:value shape this parser "
    "already reads."
)


# --- validated rule / header shapes -----------------------------------

_CIDR_TOKEN_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}$")


def _split_list(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [p.strip() for p in re.split(r"[,;\n]", str(raw)) if p.strip()]


class ExtractedRule(BaseModel):
    rule_id: str | None = None
    rule_name: str | None = None
    rule_description: str = ""

    firewall_vendor: str | None = None          # paloalto | fortigate
    management_platform: str | None = None       # panorama | pan_os | fortimanager | fortigate
    firewall_hostname: str | None = None
    management_ip: str | None = None
    firewall_location: str | None = None
    device_group: str | None = None
    vdom: str | None = None
    serial: str | None = None
    cloud_account: str | None = None

    source_zone: str | None = None
    destination_zone: str | None = None
    source: list[str] = []
    destination: list[str] = []
    source_address_object: str | None = None
    destination_address_object: str | None = None

    protocol: str | None = None
    destination_port: str | None = None
    source_port: str | None = None
    service: str | None = None
    application_ids: list[str] = []

    action: str | None = None
    nat_requirement: str | None = None
    logging: str | bool | None = None
    security_profile: str | None = None
    url_filtering_profile: str | None = None
    ips_profile: str | None = None
    antivirus_profile: str | None = None
    ssl_inspection_profile: str | None = None
    qos_requirement: str | None = None
    schedule: str | None = None
    rule_position: str | None = None
    expiry_date: str | None = None
    business_justification: str = ""

    @field_validator("source", "destination", mode="before")
    @classmethod
    def _split_cidrs(cls, v):
        return _split_list(v)

    @field_validator("application_ids", mode="before")
    @classmethod
    def _split_apps(cls, v):
        return _split_list(v)

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, v):
        if v is None:
            return v
        v = str(v).strip().lower()
        if v in ("allow", "permit", "accept"):
            return "allow"
        if v in ("deny", "drop", "block", "reject"):
            return "deny"
        return v

    @field_validator("protocol", mode="before")
    @classmethod
    def _normalize_protocol(cls, v):
        return str(v).strip().lower() if v is not None else v

    @field_validator("firewall_vendor", mode="before")
    @classmethod
    def _normalize_vendor(cls, v):
        if v is None:
            return v
        v = str(v).strip().lower()
        if "palo" in v or v in ("pan", "pan-os", "paloalto"):
            return "paloalto"
        if "forti" in v:
            return "fortigate"
        return v

    @field_validator("management_platform", mode="before")
    @classmethod
    def _normalize_platform(cls, v):
        if v is None:
            return v
        v = str(v).strip().lower().replace("-", "_").replace(" ", "_")
        if v in ("panorama",):
            return "panorama"
        if v in ("pan_os", "panos", "standalone"):
            return "pan_os"
        if v in ("fortimanager", "forti_manager"):
            return "fortimanager"
        if v in ("fortigate",):
            return "fortigate"
        return v

    @model_validator(mode="after")
    def _cidrs_are_valid(self) -> "ExtractedRule":
        for role, values in (("source", self.source), ("destination", self.destination)):
            for cidr in values:
                if _CIDR_TOKEN_RE.match(cidr):
                    try:
                        parse_cidr(cidr)
                    except CidrError as e:
                        raise ValueError(f"{role} {cidr!r}: {e}")
        return self

    def missing_required_fields(self) -> list[str]:
        """§20's "IMPLEMENTATION BLOCKED / Missing Information" list —
        deliberately a method on the validated model (not a separate
        checklist) so it can never drift from what was actually parsed."""
        missing = []
        if not self.destination_zone and not self.destination_address_object:
            missing.append("Destination Zone")
        if not self.source:
            missing.append("Source IP/CIDR")
        if not self.destination:
            missing.append("Destination IP/CIDR")
        if not self.destination_port and not self.service:
            missing.append("Service Port")
        if not self.action:
            missing.append("Action")
        if not self.device_group and self.management_platform == "panorama":
            missing.append("Firewall Device Group")
        if not self.firewall_vendor:
            missing.append("Firewall Vendor")
        return missing


class ExtractedHeader(BaseModel):
    poa_ref: str = ""
    change_ref: str = ""
    snow_ticket: str = ""
    application_name: str = ""
    business_owner: str = ""
    technical_owner: str = ""
    environment: str = "prod"
    source_application: str = ""
    destination_application: str = ""
    business_justification: str = ""
    implementation_window: str = ""
    rollback_requirement: str = ""

    @field_validator("environment", mode="before")
    @classmethod
    def _normalize_env(cls, v):
        v = str(v or "prod").strip().lower()
        return v if v in ("dev", "uat", "prod") else "prod"


@dataclass
class ParsedPoa:
    header: ExtractedHeader
    rules: list[ExtractedRule] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_format: str = "text"


# --- key:value block parsing (shared by text/docx/pdf paths) --------------

def _parse_kv_lines(lines: list[str]) -> list[dict[str, str]]:
    """Splits a flat list of 'Key: value' lines into rule blocks. The ask's
    example format has no explicit per-rule delimiter, so the signal used
    here is: a new block starts the moment a rule field would be *set a
    second time* in the current block (whichever field that happens to be
    — "Firewall:" restated for the next rule, or "Rule Name:" restated,
    or "Source:" restated, all equally indicate "a new rule has begun").
    This is more robust than watching a fixed subset of fields, because
    POAs vary in which field they happen to restate per rule."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue  # blank lines are pure whitespace here, not a block boundary
        if line in ("---", "===", "***"):
            if current:
                blocks.append(current)
                current = {}
            continue
        m = re.match(r"^([A-Za-z0-9 /_.\-]+?)\s*[:=]\s*(.+)$", line)
        if not m:
            continue
        raw_key, value = m.group(1), m.group(2).strip()
        header_key = _canonicalize(raw_key, _HEADER_REVERSE)
        rule_key = _canonicalize(raw_key, _RULE_REVERSE)

        if rule_key and rule_key in _AMBIGUOUS_KEYS and not (set(current) - {"__header__"}):
            # Ambiguous field (e.g. "Business Justification") seen before any
            # rule-specific field has been set in this block — this is still
            # the document preamble, so it belongs on the header, not on
            # whatever rule happens to be assembled next.
            current.setdefault("__header__", {})[rule_key] = value
        elif rule_key:
            if rule_key in current:
                blocks.append(current)
                current = {}
            current[rule_key] = value
        elif header_key:
            # Header fields recorded on every block; the caller folds
            # identical values across blocks into one document header.
            current.setdefault("__header__", {})
            current["__header__"][header_key] = value

    if current:
        blocks.append(current)
    return blocks


def _blocks_to_parsed(blocks: list[dict[str, str]]) -> ParsedPoa:
    header_fields: dict[str, str] = {}
    rules: list[ExtractedRule] = []
    warnings: list[str] = []

    for block in blocks:
        header_fields.update(block.pop("__header__", {}))
        if not block:
            continue
        try:
            rules.append(ExtractedRule(**block))
        except ValidationError as e:
            warnings.append(f"Skipped a block that failed schema validation: {e}")

    if not rules:
        raise UnrecognizedPoaFormat(None)
    return ParsedPoa(header=ExtractedHeader(**header_fields), rules=rules, warnings=warnings)


def parse_text(text: str) -> ParsedPoa:
    return _blocks_to_parsed(_parse_kv_lines(text.splitlines()))


def _kv_lines_to_flat_dict(lines: list[str]) -> dict[str, str]:
    """Header-only extraction: every 'Key: value' line whose key matches a
    header synonym, regardless of whether any rule field is present at
    all. Used when the rules themselves live in a table (docx/xlsx) and the
    surrounding paragraph text carries only the POA header fields."""
    out: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        m = re.match(r"^([A-Za-z0-9 /_.\-]+?)\s*[:=]\s*(.+)$", line) if line else None
        if not m:
            continue
        header_key = _canonicalize(m.group(1), _HEADER_REVERSE)
        if header_key:
            out[header_key] = m.group(2).strip()
    return out


# --- structured formats ----------------------------------------------------

def _rule_dict_from_flat(d: dict) -> dict:
    """Accepts either canonical snake_case keys (the normalized-policy JSON
    example) or human-readable ones (so a hand-edited JSON/YAML/CSV export
    of a POA template still parses)."""
    out = {}
    for k, v in d.items():
        canon = k if k in ExtractedRule.model_fields else _canonicalize(k, _RULE_REVERSE)
        if canon:
            out[canon] = v
    return out


def parse_json(text: str) -> ParsedPoa:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PoaParseError(f"Invalid JSON: {e}")
    return _parse_structured_obj(data)


def parse_yaml(text: str) -> ParsedPoa:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PoaParseError(f"Invalid YAML: {e}")
    return _parse_structured_obj(data)


def _parse_structured_obj(data) -> ParsedPoa:
    if not isinstance(data, dict):
        raise UnrecognizedPoaFormat(None)
    warnings: list[str] = []
    if "rules" in data:
        header = ExtractedHeader(**_header_dict_from_flat(data.get("header", data)))
        rules_raw = data["rules"]
    else:
        header = ExtractedHeader(**_header_dict_from_flat(data))
        rules_raw = [data]

    rules = []
    for raw in rules_raw:
        try:
            rules.append(ExtractedRule(**_rule_dict_from_flat(raw)))
        except ValidationError as e:
            warnings.append(f"Skipped a rule that failed schema validation: {e}")
    if not rules:
        raise UnrecognizedPoaFormat(None)
    return ParsedPoa(header=header, rules=rules, warnings=warnings)


def _header_dict_from_flat(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        canon = k if k in ExtractedHeader.model_fields else _canonicalize(k, _HEADER_REVERSE)
        if canon:
            out[canon] = v
    return out


def parse_csv(text: str) -> ParsedPoa:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise UnrecognizedPoaFormat(None)
    rows = list(reader)
    if not rows:
        raise UnrecognizedPoaFormat(None)

    header_fields: dict[str, str] = {}
    rules: list[ExtractedRule] = []
    warnings: list[str] = []
    for row in rows:
        rule_dict = {}
        for k, v in row.items():
            if v is None or str(v).strip() == "":
                continue
            rule_canon = _canonicalize(k, _RULE_REVERSE)
            header_canon = _canonicalize(k, _HEADER_REVERSE)
            if rule_canon:
                rule_dict[rule_canon] = v
            elif header_canon:
                header_fields[header_canon] = v
        try:
            rules.append(ExtractedRule(**rule_dict))
        except ValidationError as e:
            warnings.append(f"Skipped row {rows.index(row) + 2}: {e}")

    if not rules:
        raise UnrecognizedPoaFormat(None)
    return ParsedPoa(header=ExtractedHeader(**header_fields), rules=rules, warnings=warnings)


# --- office/pdf formats: extract to text/rows, then reuse the paths above --

def parse_docx(content: bytes) -> ParsedPoa:
    import docx  # python-docx

    doc = docx.Document(io.BytesIO(content))
    lines: list[str] = [p.text for p in doc.paragraphs]

    table_blocks: list[dict[str, str]] = []
    for table in doc.tables:
        rows = [[c.text.strip() for c in row.cells] for row in table.rows]
        if not rows:
            continue
        if len(rows[0]) == 2:
            # A two-column "Field | Value" table — treat as more key:value lines.
            lines.extend(f"{r[0]}: {r[1]}" for r in rows if r[0])
        else:
            header_row = rows[0]
            for data_row in rows[1:]:
                block = dict(zip(header_row, data_row))
                table_blocks.append(block)

    parsed = None
    if any(l.strip() for l in lines):
        try:
            parsed = parse_text("\n".join(lines))
        except PoaParseError:
            # Paragraph text had header fields but no rule (the rules live
            # in a table instead) — not an error, table_blocks below
            # carries the rules and _blocks_to_parsed already folded any
            # __header__ fields it saw into ExtractedHeader defaults, so
            # recover them here from the raw lines directly.
            parsed = ParsedPoa(header=ExtractedHeader(**_header_dict_from_flat(_kv_lines_to_flat_dict(lines))), rules=[])

    if table_blocks:
        rule_dicts = [_rule_dict_from_flat(b) for b in table_blocks]
        rules, warnings = [], list(parsed.warnings) if parsed else []
        for rd in rule_dicts:
            try:
                rules.append(ExtractedRule(**rd))
            except ValidationError as e:
                warnings.append(f"Skipped a table row: {e}")
        if rules:
            header = parsed.header if parsed else ExtractedHeader()
            return ParsedPoa(header=header, rules=(parsed.rules if parsed else []) + rules, warnings=warnings, source_format="docx")

    if parsed:
        parsed.source_format = "docx"
        return parsed
    raise UnrecognizedPoaFormat(None)


def parse_xlsx(content: bytes) -> ParsedPoa:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    header_fields: dict[str, str] = {}
    rules: list[ExtractedRule] = []
    warnings: list[str] = []

    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        header_row_idx = None
        for idx, row in enumerate(rows):
            cells = [str(c).strip().lower() if c else "" for c in row]
            hits = sum(1 for c in cells if _canonicalize(c, _RULE_REVERSE))
            if hits >= 3:
                header_row_idx = idx
                break

        # Stray key:value pairs (two adjacent cells) anywhere above the rule
        # table — or across the whole sheet if there's no table on it — are
        # document header fields, e.g. a "POA ID | POA-2026-00125" row
        # preceding the rule table.
        header_scan_rows = rows if header_row_idx is None else rows[:header_row_idx]
        for row in header_scan_rows:
            for i in range(len(row) - 1):
                if row[i] and row[i + 1] not in (None, ""):
                    canon = _canonicalize(str(row[i]), _HEADER_REVERSE)
                    if canon:
                        header_fields[canon] = str(row[i + 1])

        if header_row_idx is None:
            continue

        columns = [_canonicalize(str(c).strip(), _RULE_REVERSE) if c else None for c in rows[header_row_idx]]
        for row in rows[header_row_idx + 1:]:
            if not any(row):
                continue
            rule_dict = {col: val for col, val in zip(columns, row) if col and val not in (None, "")}
            try:
                rules.append(ExtractedRule(**rule_dict))
            except ValidationError as e:
                warnings.append(f"Skipped a row in sheet {ws.title!r}: {e}")

    if not rules:
        raise UnrecognizedPoaFormat(None)
    return ParsedPoa(header=ExtractedHeader(**header_fields), rules=rules, warnings=warnings, source_format="xlsx")


def parse_pdf(content: bytes) -> ParsedPoa:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise PoaParseError(
            "No extractable text found in this PDF — it may be a scanned image. "
            "OCR is not implemented in this phase; export the POA as text/Word/Excel instead.",
        )
    parsed = parse_text(text)
    parsed.source_format = "pdf"
    return parsed


# --- dispatcher --------------------------------------------------------

_EXT_TO_PARSER = {
    ".json": ("json", lambda b: parse_json(b.decode("utf-8", errors="replace"))),
    ".yaml": ("yaml", lambda b: parse_yaml(b.decode("utf-8", errors="replace"))),
    ".yml": ("yaml", lambda b: parse_yaml(b.decode("utf-8", errors="replace"))),
    ".csv": ("csv", lambda b: parse_csv(b.decode("utf-8", errors="replace"))),
    ".txt": ("text", lambda b: parse_text(b.decode("utf-8", errors="replace"))),
    ".docx": ("docx", parse_docx),
    ".xlsx": ("xlsx", parse_xlsx),
    ".pdf": ("pdf", parse_pdf),
}


def parse_poa(content: bytes, filename: str | None = None, declared_format: str | None = None) -> ParsedPoa:
    """Top-level entry point. Tries the declared/extension-implied format
    first; for a bare pasted-text call (no filename), tries JSON, then
    YAML, then CSV, then free-text key:value blocks, in that order — the
    same content might legitimately parse as more than one, and this order
    picks the most-structured (least ambiguous) interpretation first."""
    if declared_format:
        fmt = declared_format.lower().lstrip(".")
        fmt_map = {v[0]: v[1] for v in _EXT_TO_PARSER.values()}
        if fmt in fmt_map:
            parsed = fmt_map[fmt](content)
            parsed.source_format = fmt
            return parsed

    if filename:
        for ext, (fmt, fn) in _EXT_TO_PARSER.items():
            if filename.lower().endswith(ext):
                parsed = fn(content)
                parsed.source_format = fmt
                return parsed

    text = content.decode("utf-8", errors="replace")
    for fmt, fn in (("json", parse_json), ("yaml", parse_yaml), ("csv", parse_csv), ("text", parse_text)):
        try:
            parsed = fn(text)
            parsed.source_format = fmt
            return parsed
        except PoaParseError:
            continue
    raise UnrecognizedPoaFormat(filename)
