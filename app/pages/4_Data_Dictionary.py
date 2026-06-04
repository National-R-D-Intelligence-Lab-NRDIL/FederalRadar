"""
Data Dictionary — Federal Radar
Agency abbreviations, data coverage, and planned additions.
"""

import streamlit as st

from queries import MY_INSTITUTION, get_data_freshness

st.set_page_config(page_title="Data Dictionary — Federal Radar", layout="wide")

st.markdown("# Data Dictionary")
st.caption("Agency abbreviations, data sources, and coverage.")

# ---------------------------------------------------------------------------
# Current agencies in the database
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Agencies in Database")

CURRENT_AGENCIES = {
    "nsf":      ("National Science Foundation", "NSF Award Search API", "Research grants, fellowships, cooperative agreements"),
    "nih":      ("National Institutes of Health", "NIH RePORTER API", "Biomedical & public health research grants"),
    "dod":      ("Department of Defense", "USAspending API", "Defense research, DARPA, service branch R&D"),
    "doe":      ("Department of Energy", "USAspending API", "Energy research, national lab funding, ARPA-E"),
    "ed":       ("Department of Education", "USAspending API", "Education research, TRIO, Title III (excludes student aid)"),
    "nasa":     ("National Aeronautics & Space Administration", "USAspending API", "Space & aeronautics research, SBIR/STTR"),
    "usda":     ("Department of Agriculture", "USAspending API", "NIFA grants, agricultural & food science research"),
    "epa":      ("Environmental Protection Agency", "USAspending API", "Environmental research, STAR grants"),
    "neh":      ("National Endowment for the Humanities", "USAspending API", "Humanities research, fellowships, preservation"),
    "commerce": ("Department of Commerce", "USAspending API", "NIST, NOAA, EDA research grants"),
    "dhs":      ("Department of Homeland Security", "USAspending API", "Homeland security research, DHS S&T"),
    "dot":      ("Department of Transportation", "USAspending API", "Transportation research, UTC grants"),
    "hhs":      ("Department of Health & Human Services (non-NIH)", "USAspending API", "HRSA, CDC, SAMHSA, ACF — public health & social services research"),
}

df_fresh = get_data_freshness()

rows = []
for abbr, (full_name, source_api, description) in sorted(CURRENT_AGENCIES.items()):
    fresh_row = df_fresh[df_fresh["source"] == abbr]
    records = f"{int(fresh_row['record_count'].iloc[0]):,}" if not fresh_row.empty else "—"
    last_refresh = fresh_row["last_refresh_at"].iloc[0] if not fresh_row.empty and fresh_row["last_refresh_at"].notna().any() else "—"
    if last_refresh != "—":
        last_refresh = last_refresh[:10]  # date only
    rows.append({
        "Abbr": abbr.upper(),
        "Agency": full_name,
        "Data Source": source_api,
        "Description": description,
        "Records": records,
        "Last Refresh": last_refresh,
    })

import pandas as pd
df_current = pd.DataFrame(rows)
df_current.index = range(1, len(df_current) + 1)

st.dataframe(df_current, use_container_width=True,
             height=55 + 38 * len(df_current))

st.caption(f"{len(CURRENT_AGENCIES)} agencies · {df_fresh['record_count'].sum():,} total award records")

# ---------------------------------------------------------------------------
# Agencies planned for addition
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Agencies Planned for Addition")

PLANNED_HIGH = {
    "nea":  ("National Endowment for the Arts", "USAspending API", "Arts funding, creative research", "High"),
    "va":   ("Department of Veterans Affairs", "USAspending API", "VA research, clinical trials, health services", "High"),
    "doi":  ("Department of the Interior", "USAspending API", "USGS, wildlife & land management research", "High"),
    "doj":  ("Department of Justice", "USAspending API", "NIJ research grants, criminal justice studies", "High"),
    "dol":  ("Department of Labor", "USAspending API", "Workforce research, ETA grants, BLS studies", "High"),
}

PLANNED_LOW = {
    "state":    ("Department of State", "USAspending API", "Fulbright, international research programs", "Medium"),
    "hud":      ("Department of Housing & Urban Development", "USAspending API", "Housing & urban policy research", "Medium"),
    "treasury": ("Department of the Treasury", "USAspending API", "Economic policy research, CDFI Fund", "Medium"),
    "sba":      ("Small Business Administration", "USAspending API", "SBIR/STTR coordination, small business research", "Medium"),
    "usaid":    ("U.S. Agency for International Development", "USAspending API", "International development research", "Medium"),
}

planned_rows = []
for group in [PLANNED_HIGH, PLANNED_LOW]:
    for abbr, (full_name, source_api, description, priority) in sorted(group.items()):
        planned_rows.append({
            "Abbr": abbr.upper(),
            "Agency": full_name,
            "Data Source": source_api,
            "Description": description,
            "Priority": priority,
        })

df_planned = pd.DataFrame(planned_rows)
df_planned.index = range(1, len(df_planned) + 1)

def _priority_color(val):
    if val == "High":
        return "color: #e74c3c; font-weight: bold"
    return "color: #f39c12"

styled_planned = df_planned.style.map(_priority_color, subset=["Priority"])
st.dataframe(styled_planned, use_container_width=True,
             height=55 + 38 * len(df_planned))

st.caption(f"{len(PLANNED_HIGH)} high priority · {len(PLANNED_LOW)} medium priority · All available via USAspending API")

# ---------------------------------------------------------------------------
# Key field definitions
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Key Field Definitions")

FIELD_DEFS = {
    "source": "Agency abbreviation (lowercase) — e.g., `nsf`, `nih`, `dod`",
    "fiscal_year": "Federal fiscal year (Oct 1 – Sep 30). FY2026 = Oct 2025 – Sep 2026",
    "awd_amount": "Total award obligation amount in dollars",
    "awd_id": "Unique award identifier (agency-specific format)",
    "inst_uei": "Unique Entity Identifier — SAM.gov registration ID for the institution",
    "inst_canonical_name": "Standardized institution name (deduped across sources)",
    "pi_name": "Principal Investigator name",
    "obligation_date": "Date the award funds were obligated",
    "project_start_date": "Project period of performance start date",
    "project_end_date": "Project period of performance end date",
    "opportunity_number": "CFDA number (USAspending) or program identifier",
    "dir_abbr": "NSF directorate abbreviation (e.g., BIO, CSE, ENG)",
    "div_abbr": "NSF division abbreviation within a directorate",
    "pgm_ele_name": "NSF program element name",
    "nih_institute": "NIH institute/center abbreviation (e.g., NIGMS, NCI)",
    "activity_code": "NIH grant mechanism (e.g., R01, R21, T32)",
}

field_rows = [{"Field": k, "Description": v} for k, v in FIELD_DEFS.items()]
df_fields = pd.DataFrame(field_rows)
df_fields.index = range(1, len(df_fields) + 1)

st.dataframe(df_fields, use_container_width=True,
             height=55 + 38 * len(df_fields))

# ---------------------------------------------------------------------------
# Peer sets
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Peer Institution Sets")

st.markdown("""
| Set | Institutions |
|-----|-------------|
| **Texas** | Texas A&M, UT Austin, UT Arlington, UT Dallas, UTSA, UTEP, UTRGV, Texas State, Texas Tech, University of Houston |
| **National** | Arizona State, Purdue, Georgia State, University of South Florida, UCF, University of Utah, University of Memphis, University of Illinois Chicago, Tulane, UC Riverside |
| **Both** | All of the above |

Peer sets are used in the Action Dashboard (missed opportunities) and Portfolio Risk (diversification comparison).
""")
