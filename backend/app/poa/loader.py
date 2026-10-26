"""
app/poa/loader.py
------------------
Ported from the standalone RITM-POA tool's generate_poa.py: the RITM input
file loading logic (`load_input_csv`, `_has_input_header`, `_read_odt_table`,
`ritm_from_filename`, `_row_value`), adapted to read from uploaded bytes +
an original filename instead of a filesystem path, since this runs as part
of a stateless API service with no local file state (see app/poa/README.md
and ARCHITECTURE.md).

Supports the same four input formats as the original tool: CSV, XLSX/XLS,
ODS, and ODT - including its "report title before the actual header" and
BOM/whitespace/case-insensitive header tolerance.
"""
from __future__ import annotations

import csv
import io
import os
import re

import pandas as pd
from odf import teletype
from odf.opendocument import load as load_odt
from odf.table import Table, TableCell, TableRow


def _has_input_header(row) -> bool:
    source_headers = {"source ip", "sourceip", "src ip", "source ip address", "source ip/range"}
    destination_headers = {"destination ip", "destinationip", "dst ip", "destination ip address", "destination ip/range"}
    port_headers = {"destination port", "destinationport", "dst port", "port"}
    row_values = {
        str(value).replace("﻿", "").strip().lower()
        for value in (row.tolist() if hasattr(row, "tolist") else row)
    }
    return bool(
        row_values & source_headers
        and row_values & destination_headers
        and row_values & port_headers
    )


def _read_odt_table_bytes(content: bytes) -> pd.DataFrame:
    document = load_odt(io.BytesIO(content))
    tables = document.getElementsByType(Table)
    if not tables:
        raise ValueError("ODT input does not contain a table.")

    values = []
    for row in tables[0].getElementsByType(TableRow):
        row_values = []
        for cell in row.getElementsByType(TableCell):
            text = teletype.extractText(cell).strip()
            repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
            row_values.extend([text] * repeat)
        values.append(row_values)
    if not values:
        raise ValueError("ODT input table is empty.")
    width = max(len(row) for row in values)
    return pd.DataFrame([row + [""] * (width - len(row)) for row in values])


def load_input_bytes(filename: str, content: bytes) -> pd.DataFrame:
    """Load a RITM input file (CSV, XLSX/XLS, ODS, or ODT) from raw bytes,
    auto-detecting the header row the same way the original CLI tool did:
    some exports put a report title before the actual header, so the header
    row is located by matching Source/Destination/Port header name variants
    before pandas parses the data, preserving irregular leading rows."""
    extension = os.path.splitext(filename)[1].lower()

    if extension == ".odt":
        raw = _read_odt_table_bytes(content)
        for header_index, row in raw.iterrows():
            if _has_input_header(row):
                return pd.DataFrame(
                    raw.iloc[header_index + 1:].values,
                    columns=raw.iloc[header_index].tolist(),
                )
        raise ValueError(
            "ODT input table does not contain Source IP, Destination IP, and "
            "Destination Port headers."
        )

    is_spreadsheet = extension in (".ods", ".xlsx", ".xls")
    engine = "odf" if extension == ".ods" else None

    if is_spreadsheet:
        raw_rows = pd.read_excel(io.BytesIO(content), header=None, engine=engine).iterrows()
    else:
        text = content.decode("utf-8-sig")
        raw_rows = list(enumerate(csv.reader(io.StringIO(text))))

    for header_index, row in raw_rows:
        if _has_input_header(row):
            if is_spreadsheet:
                return pd.read_excel(io.BytesIO(content), header=header_index, engine=engine)
            return pd.read_csv(io.BytesIO(content), header=header_index)

    if is_spreadsheet:
        return pd.read_excel(io.BytesIO(content), engine=engine)
    return pd.read_csv(io.BytesIO(content))


def _row_value(row, *names) -> str:
    normalized = {
        str(key).replace("﻿", "").strip().lower(): key
        for key in row.index
    }
    for name in names:
        key = normalized.get(name.strip().lower())
        if key is not None:
            value = row.get(key)
            if pd.notna(value) and str(value).strip():
                return str(value).strip()
    return ""


def ritm_from_filename(filename: str) -> str | None:
    """
    The input file's name is random per run (e.g. 'ritm1234.csv',
    'RITM1149978_export.csv', 'New_RITM_1149978.CSV') - not a fixed name -
    so pull the RITM number straight out of it: any 'RITM' followed by
    digits, case-insensitive, wherever it appears in the filename. Returns
    the normalized 'RITM<digits>' string, or None if no such pattern is
    found (e.g. a file just called 'input.csv').
    """
    base = os.path.basename(filename)
    m = re.search(r"ritm[\s_\-]*?(\d+)", base, re.IGNORECASE)
    if not m:
        return None
    return f"RITM{m.group(1)}"
