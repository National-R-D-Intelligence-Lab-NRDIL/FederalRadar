"""
pdf_export.py
Generates a PDF report of the current gap analysis for sharing with stakeholders.
Returns bytes — pass directly to st.download_button.
"""

from datetime import date
from io import BytesIO

import pandas as pd
from fpdf import FPDF

MY_INSTITUTION = "University of North Texas"
PAGE_W = 190  # usable width mm (A4 210 - 2×10 margins)

# Palette
_NAVY   = (44, 62, 80)
_WHITE  = (255, 255, 255)
_ALT    = (245, 247, 249)
_YELLOW = (255, 243, 205)   # UNT highlight
_RED    = (192, 57, 43)
_GREEN  = (39, 174, 96)
_GRAY   = (127, 140, 141)
_STEEL  = (74, 98, 119)     # table sub-header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trend_text(t: str) -> str:
    return {"↑": "Growing", "↓": "Declining", "→": "Flat"}.get(t, "-")


def _clean_md(text: str) -> str:
    """Strip markdown bold markers for plain-text PDF rendering."""
    return text.replace("**", "")


# Characters outside latin-1 that appear in program names / headlines
_UNICODE_SUBS = {
    "\u2014": "-",   # em dash
    "\u2013": "-",   # en dash
    "\u2019": "'",   # right single quote
    "\u2018": "'",   # left single quote
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2026": "...", # ellipsis
    "\u00a0": " ",   # non-breaking space
}


def _safe(text: str) -> str:
    """Replace known non-latin-1 chars then encode safely for Helvetica."""
    for ch, sub in _UNICODE_SUBS.items():
        text = text.replace(ch, sub)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _section_header(pdf: "RadarPDF", title: str) -> None:
    pdf.set_fill_color(*_NAVY)
    pdf.set_text_color(*_WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, _safe(f"  {title}"), border=0, fill=True,
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _table_header(pdf: "RadarPDF", headers: list[str], widths: list[float]) -> None:
    pdf.set_fill_color(*_STEEL)
    pdf.set_text_color(*_WHITE)
    pdf.set_font("Helvetica", "B", 8)
    for h, w in zip(headers, widths):
        pdf.cell(w, 7, h, border=1, align="C", fill=True)
    pdf.ln(7)


def _check_page(pdf: "RadarPDF", headers: list[str], widths: list[float],
                threshold: float = 265) -> None:
    """Add a new page and reprint the table header if close to bottom."""
    if pdf.get_y() > threshold:
        pdf.add_page()
        _table_header(pdf, headers, widths)


# ---------------------------------------------------------------------------
# Document class
# ---------------------------------------------------------------------------

class RadarPDF(FPDF):
    def __init__(self, scope: str, fy_start: int, fy_end: int, peer_set: str):
        super().__init__()
        self._scope = _safe(scope)
        self._sub = _safe(f"FY{fy_start}-{fy_end}  |  {peer_set} Peers  |  {MY_INSTITUTION}")

    def header(self):
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_GRAY)
        self.cell(PAGE_W / 2, 5, "Federal Radar - Confidential",
                  new_x="RIGHT", new_y="TOP")
        self.cell(PAGE_W / 2, 5, self._scope, align="R",
                  new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*_GRAY)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_GRAY)
        self.cell(
            0, 5,
            f"Generated {date.today().isoformat()}  |  Page {self.page_no()}",
            align="C",
        )


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def generate_gap_report(
    scope_label: str,
    fy_start: int,
    fy_end: int,
    peer_set: str,
    unt_awards: int,
    unt_funding: float,
    unt_rank: int | None,
    n_ranked: int,
    n_gaps: int,
    headline: str,
    gap_df: pd.DataFrame,
    peer_funding: pd.DataFrame,
    pi_df: pd.DataFrame | None = None,
    charts: list[tuple[str, bytes]] | None = None,
) -> bytes:
    """
    gap_df     : display DataFrame from Home.py (index = Program name, columns include
                 UNT, Peer Avg, Opportunity ($M), Total Awards, Last Funded, Trend)
    peer_funding: DataFrame with columns institution | funding_m
    pi_df      : optional UNT PI table (PI | Agency | Total ($M) | Awards | First FY | Last FY)
    """
    pdf = RadarPDF(scope_label, fy_start, fy_end, peer_set)
    pdf.set_margins(10, 14, 10)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ------------------------------------------------------------------
    # Title block
    # ------------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*_NAVY)
    pdf.cell(0, 10, _safe(scope_label), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 6, _safe(f"FY{fy_start}-{fy_end}  |  {peer_set} Peers  |  {MY_INSTITUTION}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ------------------------------------------------------------------
    # Scorecard (2-row box grid)
    # ------------------------------------------------------------------
    box_w = PAGE_W / 4
    labels = ["UNT Awards", "UNT Funding", "Rank Among Peers", "Programs with Gaps"]
    values = [
        f"{unt_awards:,}",
        f"${unt_funding:.1f}M",
        f"#{unt_rank} of {n_ranked}" if unt_rank else "-",
        str(n_gaps),
    ]

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_GRAY)
    for label in labels:
        pdf.cell(box_w, 7, label, border="LTR", align="C")
    pdf.ln(7)

    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*_NAVY)
    for val in values:
        pdf.cell(box_w, 11, val, border="LBR", align="C")
    pdf.ln(15)

    # ------------------------------------------------------------------
    # Headline sentence
    # ------------------------------------------------------------------
    if headline:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(0, 5, _safe(_clean_md(headline)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ------------------------------------------------------------------
    # Program Breakdown Table
    # ------------------------------------------------------------------
    _section_header(pdf, "Program Breakdown")

    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 4,
             "Opportunity ($M) = gap between UNT and peer average funding. "
             "Negative = UNT is at or above peer average.",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    col_w = [63, 13, 18, 26, 22, 18, 16]  # total = 176
    hdrs  = ["Program", "UNT", "Peer Avg", "Opp ($M)", "Total Awds", "Last FY", "Trend"]
    _table_header(pdf, hdrs, col_w)

    for i, (prog, row) in enumerate(gap_df.iterrows()):
        _check_page(pdf, hdrs, col_w)

        opp  = float(row.get("Opportunity ($M)", 0))
        fill = i % 2 == 0
        pdf.set_fill_color(*(  _ALT if fill else _WHITE  ))

        row_cells = [
            (_safe(str(prog)[:40]),                          col_w[0], "L"),
            (str(int(row.get("UNT", 0))),                   col_w[1], "C"),
            (f"{float(row.get('Peer Avg', 0)):.1f}",        col_w[2], "C"),
            (f"${opp:.2f}M",                                col_w[3], "C"),
            (f"{int(row.get('Total Awards', 0)):,}",        col_w[4], "C"),
            (str(row.get("Last Funded", "-")),              col_w[5], "C"),
            (_trend_text(str(row.get("Trend", "-"))),       col_w[6], "C"),
        ]

        pdf.set_font("Helvetica", "", 8)
        for j, (text, w, align) in enumerate(row_cells):
            if j == 3:  # Opportunity — color by sign
                pdf.set_text_color(*(_RED if opp > 0 else _GREEN if opp < 0 else _GRAY))
                pdf.set_font("Helvetica", "B", 8)
            else:
                pdf.set_text_color(*_NAVY if prog == MY_INSTITUTION else (30, 30, 30))
                pdf.set_font("Helvetica", "", 8)
            pdf.cell(w, 6, text, border=1, align=align, fill=True)
        pdf.ln(6)

    pdf.ln(6)

    # ------------------------------------------------------------------
    # Peer Funding Comparison
    # ------------------------------------------------------------------
    if not peer_funding.empty:
        _section_header(pdf, "Peer Funding Comparison")

        pw = [115, 40, 35]
        ph = ["Institution", "Funding ($M)", "Rank"]
        _table_header(pdf, ph, pw)

        sorted_df = (
            peer_funding
            .sort_values("funding_m", ascending=False)
            .reset_index(drop=True)
        )
        for i, row in sorted_df.iterrows():
            _check_page(pdf, ph, pw)

            is_unt = row["institution"] == MY_INSTITUTION
            pdf.set_fill_color(*(_YELLOW if is_unt else (_ALT if i % 2 == 0 else _WHITE)))
            pdf.set_font("Helvetica", "B" if is_unt else "", 8)
            pdf.set_text_color(*_NAVY if is_unt else (30, 30, 30))

            pdf.cell(pw[0], 6, _safe(str(row["institution"])[:58]), border=1, align="L", fill=True)
            pdf.cell(pw[1], 6, f"${row['funding_m']:.1f}M", border=1, align="C", fill=True)
            pdf.cell(pw[2], 6, f"#{i + 1}", border=1, align="C", fill=True)
            pdf.ln(6)

        pdf.ln(6)

    # ------------------------------------------------------------------
    # UNT Principal Investigators
    # ------------------------------------------------------------------
    if pi_df is not None and not pi_df.empty:
        _section_header(pdf, "UNT Principal Investigators")

        iw = [72, 18, 34, 20, 16, 16]
        ih = ["PI", "Agency", "Total Funding", "Awards", "First FY", "Last FY"]
        _table_header(pdf, ih, iw)

        for i, row in pi_df.head(25).iterrows():
            _check_page(pdf, ih, iw)

            pdf.set_fill_color(*(_ALT if i % 2 == 0 else _WHITE))
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(30, 30, 30)

            funding_raw = row.get("Total ($M)", row.get("Total Funding", 0))
            try:
                funding_str = f"${float(str(funding_raw)):.2f}M"
            except (ValueError, TypeError):
                funding_str = str(funding_raw)

            cells = [
                (_safe(str(row.get("PI", ""))[:40]),   iw[0], "L"),
                (str(row.get("Agency", "")).upper(),   iw[1], "C"),
                (funding_str,                          iw[2], "C"),
                (str(row.get("Awards", "")),           iw[3], "C"),
                (_fy_str(row.get("First FY")),         iw[4], "C"),
                (_fy_str(row.get("Last FY")),          iw[5], "C"),
            ]
            for text, w, align in cells:
                pdf.cell(w, 6, text, border=1, align=align, fill=True)
            pdf.ln(6)

    # ------------------------------------------------------------------
    # Chart pages — one chart per page
    # ------------------------------------------------------------------
    if charts:
        for chart_title, png_bytes in charts:
            if not png_bytes:
                continue
            pdf.add_page()
            _section_header(pdf, chart_title)
            pdf.ln(2)
            # Full-width image; height scales proportionally from PNG dimensions
            pdf.image(BytesIO(png_bytes), x=10, w=190)

    return bytes(pdf.output())


def _fy_str(val) -> str:
    try:
        return str(int(val)) if val else "-"
    except (ValueError, TypeError):
        return "-"
