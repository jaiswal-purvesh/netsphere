# app/poa — Plan of Action (POA) generator

The Automation module's POA generator, ported from a standalone
"RITM-POA Automation" tool (a Python CLI an engineer built independently
to turn a RITM network-change request into a Plan of Action document) into
NetSphere as a proper backend module. See `docs/ROADMAP.md`'s "Just
completed: Automation module" entry for the full story, and
`docs/API_SPEC.md`'s "Automation — POA generator" section for the API.

## What it does

Given a RITM input file (CSV/XLSX/XLS/ODS/ODT with `Source IP`,
`Destination IP`, `Destination Port`, and a few optional columns), and a
set of uploaded reference inventories, it:

1. Loads the RITM rows (`loader.py`), auto-detecting the header row (some
   exports put a report title before it).
2. Enriches every row (`enrich.py`) against the reference inventories
   (`lookup.py`): SRC/DST location, whether OCI firewall whitelisting is
   needed and on which firewall, the destination's OCI subnet/security
   list or NSG, and routing availability. Anything the inventories can't
   answer is written as `MANUAL ENTRY REQUIRED` rather than left blank or
   guessed.
3. Writes the enriched rows to an `.xlsx` (`excel_writer.py`, styled:
   yellow for manual-review cells, red for invalid input) and a branded
   10-section `.docx` Plan of Action (`word_writer.py`, using the Bajaj/ACC
   logos under `assets/`).

`generator.py`'s `generate_poa()` is the single entry point that ties all
of this together for the API layer (`app/api/v1/endpoints/poa.py`).

## The 7 reference inventories

Each is one `PoaReferenceFile` row (`app/models/poa.py`), keyed by
`kind` — uploaded/replaced via `PUT /automation/poa/reference-files/{kind}`:

| kind | What it is |
|---|---|
| `oci_uat_inventory` | OCI UAT subnet inventory (Subnet_CIDR -> Subnet_Name/VCN_Name/Security_Lists/...) |
| `oci_prod_inventory` | Same, for OCI PROD |
| `cidr_firewall_inventory` | Merged CIDR -> Firewall map (sheet `CIDR_Firewall_Inventory`) |
| `network_ipam` | On-prem Network IPAM (Address -> Name/VRF) |
| `oci_uat_nsg_sl_report` | OCI UAT NSG/Security-List host report (one row per VM/LB IP) |
| `oci_prod_nsg_sl_report` | Same, for OCI PROD |
| `security_list_audit` | Security-list rule-count audit (capacity checking) |

Any inventory left un-uploaded doesn't fail a run — it just means every
field that inventory would have supplied comes back `MANUAL ENTRY
REQUIRED`, or an on-prem/unclassified default, exactly as when the
original CLI tool's `config.json` pointed at a path that didn't exist.

## Why bytes in Postgres, not a filesystem path

Both `PoaReferenceFile.content` and `PoaRun.excel_content`/`docx_content`
are `LargeBinary` columns, not files on a mounted volume. This keeps the
backend a stateless service (no local file state, no new deployment
concern for a shared volume) per `ARCHITECTURE.md` — the same principle
already applied elsewhere in this repo. `ReferenceFile` (in `lookup.py`)
is the tiny bytes+filename wrapper the loaders read from instead of a
path.

## Porting notes

This is a faithful, logic-preserving port of the original tool's five
modules (`poa_lookup.py` -> `lookup.py`, `poa_enrich.py` -> `enrich.py`,
`poa_excel.py` -> `excel_writer.py`, `poa_word.py` -> `word_writer.py`,
and the relevant parts of `generate_poa.py` -> `loader.py` +
`generator.py`). Business logic, constants, and docstrings are unchanged;
only the I/O layer changed:

- Filesystem paths became in-memory bytes (uploaded via the API, stored
  in Postgres, read via `io.BytesIO`).
- `print()` diagnostics became entries in a `warnings: list[str]`
  returned to the caller (surfaced in the API response / frontend)
  instead of going to stdout.
- `write_excel`/`build_word_poa` now return bytes instead of saving to an
  `output_path`.

## Deliberately not done

The original tool's `reference_data/` folder (uploaded alongside it)
contains real BFL/Bajaj Finance production OCI inventory exports. None of
that was seeded into `poa_reference_files` — reference inventories are
left entirely to the user to upload via the `/automation` page, so no
production data ends up baked into this repo or its test fixtures.
