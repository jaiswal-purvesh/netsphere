"""
app/poa/generator.py
---------------------
Ported orchestration logic from the standalone RITM-POA tool's
generate_poa.py::main(), adapted to run as a single function callable from
an API endpoint: takes an uploaded RITM input file's bytes + filename, a
`ReferenceData` built from the stored `PoaReferenceFile` rows, and the run's
metadata dict (the same shape as the original tool's config.json), and
returns the enriched rows plus the generated Excel/Word bytes - nothing is
written to a filesystem path, and every `print()` diagnostic from the
original CLI is converted to an entry in a returned `warnings` list so the
caller (the API response / frontend) can surface it instead of stdout.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.poa.enrich import compute_subnet_demand, enrich_row, INVALID_IP, MANUAL
from app.poa.excel_writer import write_excel
from app.poa.loader import _row_value, load_input_bytes, ritm_from_filename
from app.poa.lookup import ReferenceData
from app.poa.word_writer import build_word_poa


@dataclass
class PoaGenerationResult:
    ritm_number: str
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_count: int = 0
    invalid_count: int = 0
    excel_content: bytes = b""
    docx_content: bytes = b""


class PoaGenerationError(ValueError):
    """Raised for the same unrecoverable input problems the original CLI
    tool exited on (--ritm/sys.exit(1) paths): an empty input file, or every
    row missing both a Source IP and a usable destination."""


def resolve_ritm_number(input_filename: str, explicit_ritm: str | None, config_ritm: str | None) -> str:
    """RITM number precedence, unchanged from the original tool: an explicit
    override > parsed from the input filename > the run metadata's
    ritm_number > the literal 'RITM' fallback. The filename wins over the
    supplied metadata because the input file is what actually changes every
    run - a metadata field is easy to forget to update."""
    return (
        explicit_ritm
        or ritm_from_filename(input_filename)
        or (config_ritm or "").strip()
        or "RITM"
    )


def generate_poa(
    *,
    input_filename: str,
    input_content: bytes,
    ref: ReferenceData,
    config: dict,
    explicit_ritm: str | None = None,
) -> PoaGenerationResult:
    """Run one full POA generation: load the RITM input, enrich every row
    against the reference inventories, and build the Excel + Word outputs.

    `config` carries the same fields the original tool's config.json did
    (ritm_number, priority_level, description_of_change, prepared_by/
    checked_by/change_manager, etc.) - see app/poa/README.md for the shape.
    """
    warnings: list[str] = list(ref.warnings)

    ritm_number = resolve_ritm_number(input_filename, explicit_ritm, config.get("ritm_number"))
    if explicit_ritm is None and ritm_from_filename(input_filename) is None and config.get("ritm_number"):
        warnings.append(
            f"Couldn't find a RITM number in the filename '{input_filename}' - "
            f"using '{ritm_number}' from the run metadata instead."
        )

    df = load_input_bytes(input_filename, input_content)
    if df.empty:
        raise PoaGenerationError("Input file has no rows.")

    subnet_demand = compute_subnet_demand(df, ref)
    enriched_rows = [
        enrich_row(row, ritm_number, ref, subnet_demand=subnet_demand)
        for _, row in df.iterrows()
    ]
    for enriched, (_, raw_row) in zip(enriched_rows, df.iterrows()):
        enriched["Technical Justification"] = _row_value(
            raw_row, "Technical Justification", "TechnicalJustification"
        )
        enriched["Business Justification"] = _row_value(
            raw_row, "Business Justification", "BusinessJustification",
            "Purpose of Change", "Purpose ofChange"
        )

    # Diagnostics: catch the two most common "why is my output empty" causes
    # up front, instead of leaving the caller to spot it column-by-column.
    no_src_ip = sum(1 for r in enriched_rows if not r["Source IP"])
    no_destination = sum(
        1 for r in enriched_rows
        if not r["Destination IP"] and not r.get("Destination FQDN")
    )
    if no_src_ip or no_destination:
        raise PoaGenerationError(
            f"{no_src_ip} row(s) have no Source IP and {no_destination} row(s) have no "
            f"Destination IP or Destination FQDN after reading the input file. No output "
            f"was generated. Check that the file contains values under 'Source IP' and "
            f"either 'Destination IP' or 'Destination FQDN' (or close variants)."
        )

    invalid_rows = [r for r in enriched_rows if r.get("Input Validation")]
    if invalid_rows:
        warnings.append(
            f"{len(invalid_rows)} row(s) have a Source or Destination value that is not a "
            f"valid IP or CIDR - an AD group or application name, for example. Nothing was "
            f"inferred from them: they are marked '{INVALID_IP}' in the output and "
            f"highlighted red in the Excel, and listed under 'Input Validation' in section 3 "
            f"of the Word POA."
        )

    no_dst_subnet = sum(
        1 for r in enriched_rows
        if r["Destination IP"] and not r["DST Subnet Name"] and not r["Whitelisting Required at OCI"] == "Yes"
    )
    if no_dst_subnet:
        warnings.append(
            f"{no_dst_subnet} row(s)' Destination IP didn't match any subnet CIDR in either "
            f"OCI inventory sheet - that's expected for on-prem/DC destinations, but worth "
            f"double-checking it's not because a sheet's Subnet_CIDR values don't cover them."
        )

    manual_count = sum(1 for r in enriched_rows for v in r.values() if v == MANUAL)
    if manual_count:
        warnings.append(
            f"{manual_count} cell(s) across the output need manual review (highlighted "
            f"yellow in the Excel, highlighted in the Word doc) - mainly NSG names (when an "
            f"NSG actually exists) and OCI Firewall fields until the CIDR/Firewall inventory "
            f"has real CIDR -> Firewall rows for them."
        )

    excel_content = write_excel(enriched_rows)

    word_config = dict(config)
    word_config["ritm_number"] = ritm_number
    docx_content = build_word_poa(enriched_rows, word_config)

    return PoaGenerationResult(
        ritm_number=ritm_number,
        rows=enriched_rows,
        warnings=warnings,
        manual_count=manual_count,
        invalid_count=len(invalid_rows),
        excel_content=excel_content,
        docx_content=docx_content,
    )
