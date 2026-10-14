"""One-page-ish shift report PDF: KPIs, per-line results, anomalies, downtime, NCs, actions."""
from __future__ import annotations

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from .config import SHIFTS

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
RULE = colors.HexColor("#cbd5e1")
HEAD_BG = colors.HexColor("#e2e8f0")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, textColor=INK, spaceAfter=2)
H2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11.5, textColor=INK, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12, textColor=INK)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=7.5, leading=9.5, textColor=MUTED)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8, leading=10)


def _table(header: list[str], rows: list[list], widths: list[float], align_right: set[int] = frozenset()):
    data = [header] + [[Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > 28 else c
                        for c in r] for r in rows]
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in align_right:
        style.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _pct(v):
    return "n/a" if v is None else f"{v:.1f}%"


def build_pdf(detail: dict, actions: list[str]) -> bytes:
    k = detail["kpis"]
    scope = detail["lines"][0]["name"] if detail["line_id"] and detail["lines"] else "All lines"
    start_h = SHIFTS[detail["shift"]]
    window = f"{start_h:02d}:00-{(start_h + 8) % 24:02d}:00"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.55 * inch,
                            title=f"Shift report {detail['date']} {detail['shift']}",
                            author="Production Intelligence Dashboard")
    story = [
        Paragraph(f"Shift Report: {detail['date']}, Shift {detail['shift']} ({window})", H1),
        Paragraph(f"{scope} &middot; generated {datetime.now():%Y-%m-%d %H:%M} &middot; "
                  "synthetic demonstration data", SMALL),
        Spacer(1, 8),
    ]

    tiles = [
        ("Units vs plan", f"{k['units']} / {k['planned_units']}", _pct(k["attainment_pct"])),
        ("Earned hours", f"{k['earned_hours']:.1f}", f"of {k['labor_hours']:.0f} labor h"),
        ("Realization", _pct(k["realization_pct"]), "earned / labor"),
        ("First-pass yield", _pct(k["first_pass_yield_pct"]), f"{k['nc_count']} NCs"),
        ("Downtime", f"{k['downtime_min']} min", f"{k['anomalies']} anomalies"),
    ]
    tile_tbl = Table([[Paragraph(f"<font size=7 color='#64748b'>{t.upper()}</font><br/>"
                                 f"<font size=13><b>{v}</b></font><br/>"
                                 f"<font size=7 color='#64748b'>{s}</font>", BODY)
                       for t, v, s in tiles]], colWidths=[1.46 * inch] * 5)
    tile_tbl.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, RULE),
                                  ("INNERGRID", (0, 0), (-1, -1), 0.5, RULE),
                                  ("TOPPADDING", (0, 0), (-1, -1), 6),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(tile_tbl)

    story.append(Paragraph("Actions for the next shift", H2))
    story.append(ListFlowable([ListItem(Paragraph(a, BODY), leftIndent=10) for a in actions],
                              bulletType="1", bulletFontSize=8, leftIndent=14))

    story.append(Paragraph("Results by line", H2))
    story.append(_table(
        ["Line", "Crew", "Plan", "Units", "Attain.", "Earned h", "NCs", "Down min"],
        [[ln["name"], ln["headcount"], ln["planned_units"], ln["units"],
          _pct(100 * ln["units"] / ln["planned_units"]) if ln["planned_units"] else "n/a",
          f"{ln['earned_hours']:.1f}", ln["nc_count"], ln["downtime_min"]] for ln in detail["lines"]],
        [2.5, 0.5, 0.55, 0.55, 0.7, 0.75, 0.5, 0.75], align_right={1, 2, 3, 4, 5, 6, 7}))

    if detail["anomalies"]:
        story.append(KeepTogether([
            Paragraph("Anomalies (Isolation Forest)", H2),
            _table(["Line", "Station", "Score", "What stood out"],
                   [[a["line"], a["station"], f"{a['score']:.3f}", a["reason"]] for a in detail["anomalies"]],
                   [2.1, 1.3, 0.55, 3.35], align_right={2}),
        ]))
    else:
        story += [Paragraph("Anomalies (Isolation Forest)", H2), Paragraph("None flagged this shift.", BODY)]

    story.append(Paragraph("Downtime", H2))
    if detail["downtime"]:
        story.append(_table(["Start", "Line", "Station", "Reason", "Min"],
                            [[e["started_at"], e["line"], e["station"], e["reason"], e["minutes"]]
                             for e in detail["downtime"]],
                            [0.55, 2.3, 1.35, 2.5, 0.6], align_right={4}))
    else:
        story.append(Paragraph("No downtime logged.", BODY))

    story.append(Paragraph("Nonconformances", H2))
    if detail["nonconformances"]:
        story.append(_table(["NC", "Serial", "Station", "Defect", "Severity", "Status"],
                            [[f"NC-{n['nc_id']}", n["serial_number"], n["station"],
                              f"{n['defect_code']}: {n['description']}", n["severity"], n["status"]]
                             for n in detail["nonconformances"]],
                            [0.6, 1.25, 1.2, 2.55, 0.65, 0.85]))
    else:
        story.append(Paragraph("No nonconformances written.", BODY))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.6 * inch, 0.35 * inch, "Production Intelligence Dashboard: synthetic data only")
        canvas.drawRightString(letter[0] - 0.6 * inch, 0.35 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
