"""
app/poa/word_writer.py
-----------------------
Ported from the standalone RITM-POA tool's poa_word.py. Builds the
"Plan of Action (POA)" Word document (.docx) from the enriched rows +
run metadata, replicating the layout/branding of the original tool's sample
output: same two logos in the header, same title bar colour, same section
structure, order and table styles.

Every row of enriched data is carried into the doc (Source/Destination/Port
table has one row per input rule, nothing is dropped), and the device /
firewall lists in the firewall-implementation section are generated from the
same enriched data so the Word doc and the Excel output always agree.

Adapted from the original only in its I/O: `build_word_poa` now writes into
an in-memory `BytesIO` and returns the document's bytes instead of saving to
a filesystem path, and its logo arguments default to the packaged assets
shipped under `app/poa/assets/` (still filesystem paths, since these are
static assets bundled with the app, not user data - `python-docx`'s
`add_picture` accepts a path directly).
"""
import os
from collections import defaultdict
from datetime import datetime
from io import BytesIO

from docx import Document
from docx.shared import Pt, Cm, Emu, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

TITLE_BG = "FFFAEE"
TITLE_FG = RGBColor(0x39, 0x54, 0x76)
LABEL_BG = "729FCF"
GREY_BG = "C0C0C0"
MANUAL_TOKEN = "MANUAL ENTRY REQUIRED"
INVALID_IP_TOKEN = "NOT A VALID IP/CIDR"

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
DEFAULT_BAJAJ_LOGO = os.path.join(ASSETS_DIR, "bajaj_logo_header.png")
DEFAULT_ACC_LOGO = os.path.join(ASSETS_DIR, "acc_logo_header.png")

# Section 5 is split into two independent sub-sections, one per leg of a flow,
# and the two are never merged: an engineer works one firewall at a time, so the
# source-firewall policies and the destination-firewall policies are listed
# apart even when both legs happen to sit behind the same firewall. Within each
# sub-section the policies are grouped under the name of the firewall they are
# created on. Each entry is (role, enriched-row column, heading, instruction).
FIREWALL_LEGS = (
    (
        "SRC", "Source Firewall Name", "5.1 Source Firewall Policies",
        "Applied outbound, on the firewall the source IP sits behind. Create each "
        "policy below on the firewall named in its heading.",
    ),
    (
        "DST", "Destination Firewall Name", "5.2 Destination Firewall Policies",
        "Applied inbound, on the firewall the destination IP sits behind. Create "
        "each policy below on the firewall named in its heading.",
    ),
)
FIREWALL_POLICY_HEADERS = [
    "Firewall Policy", "Port", "Source IP/Range", "Destination IP/Range",
    "Destination FQDN",
]
PAGE_MARGIN = Inches(1)  # Word's "Normal" margin preset
LOGO_HEIGHT = Cm(1.8)


# ---------- low level helpers ----------

def _shade_cell(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def _set_cell_text(cell, text, bold=False, color=None, size=None, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    if align:
        p.alignment = align
    run = p.add_run(str(text) if text is not None else "")
    run.bold = bold
    if color:
        run.font.color.rgb = color
    if size:
        run.font.size = Pt(size)
    return run


def _add_page_border(doc):
    sectPr = doc.sections[0]._sectPr
    pgBorders = OxmlElement('w:pgBorders')
    pgBorders.set(qn('w:offsetFrom'), 'page')
    for edge in ('top', 'left', 'bottom', 'right'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), '18')
        el.set(qn('w:space'), '24')
        el.set(qn('w:color'), '000000')
        pgBorders.append(el)
    sectPr.append(pgBorders)


def _add_heading_bar(doc, text):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = table.cell(0, 0)
    _shade_cell(cell, TITLE_BG)
    _set_cell_text(cell, text, bold=True, color=TITLE_FG, size=14,
                   align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()


def _bullet(doc, label, value="", bold_label=True):
    p = doc.add_paragraph(style="List Bullet")
    r = p.add_run(label)
    r.bold = bold_label
    if value != "":
        p.add_run(" " + str(value))
    return p


def _section_heading(doc, text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(12)
    return p


def _sub_heading(doc, text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.underline = True
    return p


def _highlight_if_manual(run, text):
    """Highlight a cell that still needs attention: yellow for a value the
    inventories could not supply, red for input that was never a valid IP."""
    if text == MANUAL_TOKEN:
        run.font.highlight_color = 7  # yellow
    elif text == INVALID_IP_TOKEN:
        run.font.highlight_color = 6  # red


# ---------- header / footer ----------

def _add_header(doc, bajaj_logo_path, acc_logo_path):
    section = doc.sections[0]
    # Size the header table to the printable width.
    usable_width = Emu(section.page_width - section.left_margin - section.right_margin)
    half_width = Emu(usable_width // 2)
    header = section.header
    table = header.add_table(rows=2, cols=2, width=usable_width)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for row in table.rows:
        for cell in row.cells:
            cell.width = half_width

    left, right = table.rows[0].cells
    left.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    right.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    # Left Cell - Bajaj logo
    p = left.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.add_run().add_picture(bajaj_logo_path, height=LOGO_HEIGHT)

    # Right Cell - ACC logo
    p2 = right.paragraphs[0]
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p2.add_run().add_picture(acc_logo_path, height=LOGO_HEIGHT)

    title_cell = table.cell(1, 0).merge(table.cell(1, 1))
    _shade_cell(title_cell, TITLE_BG)
    _set_cell_text(
        title_cell, "PLAN OF ACTION (POA)", bold=True, color=TITLE_FG, size=14,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )


def _set_document_footer(doc):
    """The original template has 'Sensitivity: Internal & confidential' as a real
    page footer (repeats on every page automatically) - not a body paragraph.
    Doing the same here avoids body-paragraph pagination side effects."""
    footer = doc.sections[0].footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.text = "Sensitivity: Internal & confidential"
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


# ---------- table builders ----------

def _add_src_dst_port_table(doc, rows):
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, label in enumerate(["Source", "Destination", "Port"]):
        _shade_cell(hdr[i], LABEL_BG)
        _set_cell_text(hdr[i], label, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
    for row in rows:
        cells = table.add_row().cells
        _set_cell_text(cells[0], row.get("Source IP", ""))
        _set_cell_text(cells[1], row.get("Destination IP", ""))
        _set_cell_text(cells[2], row.get("Destination Port", ""))
    doc.add_paragraph()


def _add_timing_table(doc, timing):
    data = [
        ("Pre-Implementation", "Pre-Implementation", timing.get("pre_implementation", ""), "00:00"),
        ("Implementation & Service\nConfirmation", "Implementation - without Downtime",
         timing.get("implementation_without_downtime", ""), "00:00"),
        ("", "Implementation - with Downtime", timing.get("implementation_with_downtime", ""), "00:00"),
        ("", "Customer Service Confirmation", timing.get("customer_confirmation_1", ""), "00:00"),
        ("Roll back & Service Confirmation", "Rollback - without Downtime",
         timing.get("rollback_without_downtime", ""), "00:00"),
        ("", "Rollback - with Downtime", timing.get("rollback_with_downtime", ""), "00:00"),
        ("", "Customer Service Confirmation", timing.get("customer_confirmation_2", ""), "00:00"),
        ("", "Activity Window", timing.get("activity_window", ""), "00:00"),
    ]
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, label in enumerate(["Particulars", "Activity", "Duration (HH:MM)", "Downtime (HH:MM)"]):
        _shade_cell(hdr[i], GREY_BG)
        _set_cell_text(hdr[i], label, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    for particulars, activity, duration, downtime in data:
        cells = table.add_row().cells
        _set_cell_text(cells[0], particulars)
        _set_cell_text(cells[1], activity)
        _set_cell_text(cells[2], duration)
        _set_cell_text(cells[3], downtime)
    doc.add_paragraph()


def _add_signoff_table(doc, rows_labels_data):
    table = doc.add_table(rows=0, cols=3)
    table.style = "Table Grid"
    for label, person in rows_labels_data:
        cells = table.add_row().cells
        _set_cell_text(cells[0], label, bold=True)
        _set_cell_text(cells[1], f"Name: {person.get('name', '')}")
        _set_cell_text(cells[2], f"Date: {person.get('date', '')}")
    doc.add_paragraph()


def _display_value(value):
    if value is None or not str(value).strip():
        return "None"
    return str(value)


def _add_text_block(doc, label, value):
    p = doc.add_paragraph()
    run = p.add_run(f"{label}: ")
    run.bold = True
    p.add_run(_display_value(value))


def _add_bullet_list(doc, label, items):
    heading = doc.add_paragraph()
    run = heading.add_run(label)
    run.bold = True
    for item in items:
        _bullet(doc, "", _display_value(item), bold_label=False)


def _add_data_table(doc, headers, rows, font_size=7):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for index, header in enumerate(headers):
        _shade_cell(table.rows[0].cells[index], LABEL_BG)
        _set_cell_text(
            table.rows[0].cells[index], header, bold=True,
            color=RGBColor(0xFF, 0xFF, 0xFF), size=font_size,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            run = _set_cell_text(cells[index], _display_value(value), size=font_size)
            _highlight_if_manual(run, value)
    doc.add_paragraph()
    return table


def _add_network_flow_table(doc, rows):
    headers = [
        "Source IP", "Source Location", "Destination IP", "Destination FQDN",
        "Destination Location", "Destination Type",
        "Destination Port", "Source Firewall", "Destination Firewall",
        "OCI Whitelist", "Routing",
    ]
    data = [
        [
            row.get("Source IP"), row.get("SRC Location"),
            row.get("Destination IP"), row.get("Destination FQDN"), row.get("DST Location"),
            row.get("Destination Type"), row.get("Destination Port"),
            row.get("Source Firewall Name"), row.get("Destination Firewall Name"),
            row.get("Whitelisting Required at OCI"),
            row.get("Routing Availibility"),
        ]
        for row in rows
    ]
    _add_data_table(doc, headers, data, font_size=6)


def _add_analysis_table(doc, rows):
    headers = [
        "Rule Name", "Source Subnet", "Destination Subnet",
        "Firewall Whitelisting", "Source Firewall", "Destination Firewall",
        "Destination Security List", "Destination NSG / Security List",
        "Routing Availability",
    ]
    data = [
        [
            row.get("Rule Name"), row.get("SRC Subnet Name"), row.get("DST Subnet Name"),
            row.get("Firewall Whitelisting"),
            row.get("Source Firewall Name"), row.get("Destination Firewall Name"),
            row.get("DST Subnet Inbound SL (If DST is Entire Subnet)"),
            row.get("DST Server NSG Inbound SL (If DST is Single IP)"),
            row.get("Routing Availibility"),
        ]
        for row in rows
    ]
    _add_data_table(doc, headers, data, font_size=6)


def _add_input_validation(doc, rows):
    """Rendered only when a row's Source or Destination cell was not an IP or a
    CIDR, so a clean RITM produces no block at all and the notice keeps its
    meaning when it does appear."""
    flagged = [row for row in rows if _display_value(row.get("Input Validation")) != "None"]
    if not flagged:
        return
    _sub_heading(doc, "Input Validation")
    doc.add_paragraph(
        f"{len(flagged)} row(s) in the RITM input carry a value that is not a valid IP "
        "address or CIDR - an AD group or application name, for example. Those rows "
        "could not be matched against any inventory, so no location, firewall, "
        "Security List, or routing result was derived for them and each is marked "
        "NOT A VALID IP/CIDR. Replace the values below with real addresses and "
        "re-run this POA before implementing them."
    )
    _add_data_table(
        doc,
        ["Rule Name", "Source IP", "Destination IP", "Destination Port", "Issue"],
        [
            [
                row.get("Rule Name"), row.get("Source IP"), row.get("Destination IP"),
                row.get("Destination Port"), row.get("Input Validation"),
            ]
            for row in flagged
        ],
        font_size=7,
    )


def _add_technical_justification_table(doc, rows):
    headers = ["Rule Name", "Source IP", "Destination IP", "Technical Justification"]
    data = [
        [
            row.get("Rule Name"), row.get("Source IP"), row.get("Destination IP"),
            row.get("Technical Justification"),
        ]
        for row in rows
    ]
    _add_data_table(doc, headers, data, font_size=8)


def _unique_values(rows, key):
    return sorted({
        _display_value(row.get(key)) for row in rows
        if _display_value(row.get(key)) != "None"
    })


def _add_firewall_implementation(doc, rows):
    _section_heading(doc, "5. Firewall Implementation")
    _add_bullet_list(
        doc, "Standard method",
        [
            "If source, destination, and port are the same, apply them in one rule.",
            "If the source is different but destination and port are the same, apply them in one rule.",
            "If the source is different, destination is the same, and ports are different, create a separate policy for each port.",
            "If the source is the same, destination is different, and port is the same, apply them in one rule.",
            "If the source is the same, destination and port are different, create a separate policy for each port.",
        ],
    )
    _add_text_block(
        doc, "Implementation sequence",
        "Navigate to Panorama, open the appropriate device group and policy rule "
        "base, create the rule name using the RITM number, add the grouped source "
        "and destination objects, select the required service/port, choose the "
        "destination firewall context, commit, push, and validate the rule hit."
    )
    _add_bullet_list(
        doc, "Policy naming pattern",
        [
            "Apply one policy per firewall in the path. A flow that crosses two "
            "firewalls needs both: an outbound rule on the source firewall and an "
            "inbound rule on the destination firewall.",
            "Section 5.1 lists the source firewall policies, named "
            "<RITM>-SRC-FW-<n>, grouped under the firewall each one is created on.",
            "Section 5.2 lists the destination firewall policies, named "
            "<RITM>-DST-FW-<n>, grouped the same way.",
            "The two sections are independent. When both legs sit behind the same "
            "firewall, that firewall appears in both, once for its outbound policy "
            "and once for its inbound policy - apply both.",
            "A firewall shown as MANUAL ENTRY REQUIRED is not mapped in the CIDR/"
            "firewall inventory - confirm that leg's firewall before applying its policy.",
        ],
    )
    firewall_rows = [
        row for row in rows
        if _display_value(row.get("Firewall Whitelisting")) == "Yes"
    ]
    # Each leg is collected on its own - legs[role][firewall][port] - so the two
    # sub-sections stay independent and a firewall carrying both an outbound and
    # an inbound policy is listed once under each, never folded into one row.
    legs = {
        role: defaultdict(lambda: defaultdict(
            lambda: {"sources": set(), "destinations": set(), "fqdns": set()}
        ))
        for role, _, _, _ in FIREWALL_LEGS
    }
    for row in firewall_rows:
        port = _display_value(row.get("Destination Port"))
        source_ip = _display_value(row.get("Source IP"))
        destination_ip = _display_value(row.get("Destination IP"))
        fqdn = _display_value(row.get("Destination FQDN"))
        for role, column, _, _ in FIREWALL_LEGS:
            firewall = _display_value(row.get(column))
            if firewall == "None":
                continue
            policy = legs[role][firewall][port]
            policy["sources"].add(source_ip)
            policy["destinations"].add(destination_ip)
            if fqdn != "None":
                policy["fqdns"].add(fqdn)

    rule_name = firewall_rows[0].get("Rule Name", "None") if firewall_rows else "None"
    for role, _, heading, instruction in FIREWALL_LEGS:
        _add_firewall_leg_section(doc, heading, instruction, legs[role], rule_name, role)


def _add_firewall_leg_section(doc, heading, instruction, by_firewall, rule_name, role):
    """One sub-section of section 5 - the source-firewall policies or the
    destination-firewall policies - with a separate heading and table per
    firewall name, so each block is the complete list of what to apply on that
    one firewall. Policies are numbered across the whole sub-section, giving
    <RITM>-SRC-FW-1.. and <RITM>-DST-FW-1.. as two independent sequences."""
    _sub_heading(doc, heading)
    doc.add_paragraph(instruction)
    if not by_firewall:
        doc.add_paragraph("None")
        doc.add_paragraph()
        return
    policy_number = 0
    for firewall in sorted(by_firewall):
        paragraph = doc.add_paragraph()
        label = paragraph.add_run("Firewall: ")
        label.bold = True
        name = paragraph.add_run(firewall)
        name.bold = True
        _highlight_if_manual(name, firewall)
        data = []
        for port, policy in sorted(by_firewall[firewall].items()):
            policy_number += 1
            data.append([
                f"{rule_name}-{role}-FW-{policy_number}",
                port,
                ", ".join(sorted(policy["sources"])),
                ", ".join(sorted(policy["destinations"])),
                ", ".join(sorted(policy["fqdns"])) or "None",
            ])
        _add_data_table(doc, FIREWALL_POLICY_HEADERS, data, font_size=7)


def _add_nsg_implementation(doc, rows):
    _section_heading(doc, "6. NSG Implementation")
    _add_bullet_list(
        doc, "Implementation instructions",
        [
            "When an NSG exists, go to OCI Console > Networking > Virtual Cloud Networks > VCN > Network Security Groups > NSG > Ingress Rules > Add Ingress Rule.",
            "Add the source IP/CIDR, protocol, destination port, and action, then save and verify the rule.",
            "When no NSG exists, create an NSG for this request using the name given in the 'NSG Remark' column of section 7, attach it to the destination VM/load balancer, then add the ingress rule to it.",
        ],
    )
    nsg_rows = []
    for row in rows:
        target = _display_value(row.get("DST Server NSG Inbound SL (If DST is Single IP)"))
        if target == "None":
            continue
        nsg_rows.append([
            row.get("Rule Name"), row.get("Destination IP"), row.get("Source IP"),
            row.get("Destination Port"), "Existing NSG", target,
        ])
    data = [
        row for row in nsg_rows
    ]
    if not data:
        data = [["None", "None", "None", "None", "None", "None"]]
    _add_data_table(doc, ["Rule Name", "Destination IP", "Source IP/Range", "Port", "Target Type", "NSG / Security List"], data)


def _add_security_list_implementation(doc, rows):
    _section_heading(doc, "7. Security List Implementation")
    _add_text_block(
        doc, "Implementation method",
        "Open OCI Console > Networking > Virtual Cloud Networks > select the VCN "
        "> select the destination subnet > Resources > Security Lists > select "
        "the applicable security list > Add Ingress Rule. Add the source CIDR, "
        "IP protocol, destination port, and description, then save and validate. "
        "InfraTool default lists are excluded from this POA."
    )
    security_rows = [
        row for row in rows
        if _display_value(row.get("DST Subnet Inbound SL (If DST is Entire Subnet)")) != "None"
    ]
    data = [
        [
            row.get("Rule Name"), row.get("Destination IP"), row.get("Source IP"),
            row.get("Destination Port"), row.get("DST Subnet Inbound SL (If DST is Entire Subnet)"),
            row.get("NSG Remark"),
        ]
        for row in security_rows
    ]
    _add_data_table(
        doc,
        ["Rule Name", "Destination IP/CIDR", "Source IP/Range", "Port", "Security List", "NSG Remark"],
        data,
    )


def _add_routing_implementation(doc, rows):
    _section_heading(doc, "8. Routing Implementation")
    _add_bullet_list(
        doc,
        "Routing instructions",
        [
            "For same-VCN traffic, validate the local VCN route tables.",
            "For OCI VCN-to-VCN traffic, verify both VCN route tables, DRG attachments, and the DRG route table.",
            "For production-to-DR traffic, verify the RPC connection, both VCN route tables, and DRG/RPC route propagation.",
            "For on-premise traffic, verify the on-premise route, firewall policy, FastConnect link, and DRG route before approval.",
        ],
    )
    data = [
        [row.get("Rule Name"), row.get("Source IP"), row.get("Destination IP"), row.get("Routing Availibility")]
        for row in rows
    ]
    _add_data_table(doc, ["Rule Name", "Source IP", "Destination IP", "Calculated Routing Path"], data)


# ---------- main builder ----------

def build_word_poa(
    enriched_rows,
    config,
    bajaj_logo_path=DEFAULT_BAJAJ_LOGO,
    acc_logo_path=DEFAULT_ACC_LOGO,
) -> bytes:
    """Build the Plan of Action Word document in memory and return its bytes."""
    doc = Document()
    section = doc.sections[0]
    section.top_margin = PAGE_MARGIN
    section.bottom_margin = PAGE_MARGIN
    section.left_margin = PAGE_MARGIN
    section.right_margin = PAGE_MARGIN
    technical_values = sorted({
        _display_value(row.get("Technical Justification"))
        for row in enriched_rows
        if _display_value(row.get("Technical Justification")) != "None"
    })
    technical_line = "; ".join(technical_values) if technical_values else "None"
    _add_page_border(doc)
    _add_header(doc, bajaj_logo_path, acc_logo_path)
    _section_heading(doc, "1. Change Request")
    _bullet(doc, "Request No: ", config.get("ritm_number", "None"))
    _bullet(doc, "Priority: ", config.get("priority_level", "None"))
    description = _display_value(config.get("description_of_change", "None"))
    _add_text_block(doc, "Description", description)

    _section_heading(doc, "2. Business Justification")
    business = next(
        (row.get("Business Justification") for row in enriched_rows
         if row.get("Business Justification")),
        config.get("purpose_of_change", "None"),
    )
    _add_text_block(doc, "Business justification", _display_value(business))

    _section_heading(doc, "3. Network Flow and Excel Analysis")
    _add_network_flow_table(doc, enriched_rows)
    _add_analysis_table(doc, enriched_rows)
    _add_input_validation(doc, enriched_rows)

    _section_heading(doc, "4. Technical Justification")
    _add_text_block(
        doc,
        "Technical justification",
        technical_line,
    )

    _add_firewall_implementation(doc, enriched_rows)
    _add_nsg_implementation(doc, enriched_rows)
    _add_security_list_implementation(doc, enriched_rows)
    _add_routing_implementation(doc, enriched_rows)

    _section_heading(doc, "9. Implementation and Validation")
    _bullet(doc, "Change owner: ", config.get("change_owner", "None"))
    implementation_time = config.get(
        "_generated_at",
        datetime.now().strftime("%d %B %Y @ %I:%M %p"),
    )
    _bullet(doc, "Implementation window: ",
            f"{implementation_time} - {implementation_time}")
    _bullet(doc, "Rollback plan: ", config.get("rollback_plan", "None"))
    _bullet(doc, "Pre-change testing: ", config.get("pre_change_testing", "None"))
    _bullet(doc, "Post-change testing: ", config.get("post_change_testing", "None"))
    _bullet(doc, "Execution note: ",
            "Apply only the security-list, NSG, firewall, or routing actions shown in the network-flow tables.")

    _section_heading(doc, "10. Approval and Personal Information")
    _add_signoff_table(doc, [
        ("Prepared by", config.get("prepared_by", {})),
        ("Checked by", config.get("checked_by", {})),
        ("Change Manager / Approval", config.get("change_manager", {})),
    ])
    _set_document_footer(doc)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
