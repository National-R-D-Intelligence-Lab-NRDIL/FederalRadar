"""
Open Opportunities — Federal Radar
Two panels:
  1. Peer gaps — open NOFOs where peers won and UNT wasn't competing
  2. Revisit — open NOFOs in programs UNT has won before
"""

from datetime import date

import pandas as pd
import streamlit as st

from queries import (
    MY_INSTITUTION,
    get_herd_institutions,
    get_my_ueis,
    get_peer_institutions,
    get_peer_opportunity_gaps,
    get_unt_open_revisits,
)

st.set_page_config(page_title="Open Opportunities — Federal Radar", layout="wide")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_m(m: float) -> str:
    """Format a value already in millions as $XB or $XM."""
    if m >= 1_000:
        return f"${m / 1_000:.1f}B"
    return f"${m:.0f}M"

# ---------------------------------------------------------------------------
# Peer name abbreviations for compact display
# ---------------------------------------------------------------------------

PEER_SHORT = {
    "University of Texas at Austin":         "UT Austin",
    "Texas A&M University":                  "A&M",
    "University of Texas at Arlington":      "UTA",
    "University of Texas at Dallas":         "UTD",
    "University of Texas at San Antonio":    "UTSA",
    "University of Texas at El Paso":        "UTEP",
    "University of Texas Rio Grande Valley": "UTRGV",
    "Texas State University":                "TX State",
    "Texas Tech University":                 "TX Tech",
    "University of Houston":                 "Houston",
    "Arizona State University":              "ASU",
    "Purdue University":                     "Purdue",
    "Georgia State University":              "GA State",
    "University of South Florida":           "USF",
    "University of Central Florida":         "UCF",
    "University of Utah":                    "Utah",
    "University of Memphis":                 "Memphis",
    "University of Illinois at Chicago":     "UIC",
    "University of Illinois Chicago":        "UIC",
    "Tulane University":                     "Tulane",
    "University of California Riverside":    "UCR",
    "University of California, Riverside":   "UCR",
}

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Open Opportunities")
    st.caption(MY_INSTITUTION)
    st.divider()

    peer_set = st.radio("Peer Set", ["Texas", "National", "Both", "Custom"], index=0)

    if peer_set == "Custom":
        _cdf = get_herd_institutions()
        _my_set = set(get_my_ueis())
        _cdf = _cdf[~_cdf["awards_uei"].isin(_my_set)].reset_index(drop=True)
        _label_map = {}
        for _row in _cdf.itertuples():
            _lbl = f"{_row.ipeds_name} ({_row.state})"
            _label_map[_lbl] = (_row.awards_name or _row.ipeds_name, _row.awards_uei)
        _picked = st.multiselect("Select peer institutions", sorted(_label_map.keys()))
        _custom_peer_items = [_label_map[p] for p in _picked]

    status_choice = st.radio(
        "Solicitation Status",
        ["Posted only", "Forecasted only", "Both"],
        index=0,
    )

    lookback_fy = st.selectbox(
        "Peer awards since",
        [2023, 2022, 2021],
        index=0,
        format_func=lambda y: f"FY{y}",
    )

# Map radio to DB status values
if status_choice == "Posted only":
    status_filter = ("posted",)
elif status_choice == "Forecasted only":
    status_filter = ("forecasted",)
else:
    status_filter = ("posted", "forecasted")

# ---------------------------------------------------------------------------
# Load both datasets in parallel
# ---------------------------------------------------------------------------

my_ueis    = tuple(get_my_ueis())
if peer_set == "Custom":
    peer_items = _custom_peer_items
else:
    peer_items = get_peer_institutions(peer_set)
peer_ueis  = tuple(uei for _, uei in peer_items)

if not my_ueis:
    st.error("No UEIs found for UNT. Check the institutions table.")
    st.stop()

if not peer_ueis:
    st.info("Select at least one peer institution to continue.")
    st.stop()

df_gaps     = get_peer_opportunity_gaps(my_ueis, peer_ueis, status_filter, lookback_fy)
df_revisits = get_unt_open_revisits(my_ueis, status_filter)

# ---------------------------------------------------------------------------
# Agency filter — union of both datasets
# ---------------------------------------------------------------------------

with st.sidebar:
    st.divider()
    all_agencies = sorted(
        set(df_gaps["agency_name"].dropna().tolist()) |
        set(df_revisits["agency_name"].dropna().tolist())
    )
    selected_agencies = st.multiselect("Filter by Agency", all_agencies)

if selected_agencies:
    df_gaps     = df_gaps[df_gaps["agency_name"].isin(selected_agencies)]
    df_revisits = df_revisits[df_revisits["agency_name"].isin(selected_agencies)]

# ---------------------------------------------------------------------------
# Page header + combined metrics
# ---------------------------------------------------------------------------

st.markdown("# Open Opportunities")
today = date.today()


def _close_days(row) -> int | None:
    d = row.get("close_date") or row.get("estimated_close_date")
    if not d:
        return None
    try:
        return (date.fromisoformat(str(d)[:10]) - today).days
    except ValueError:
        return None


# Gap metrics
gap_posted    = int((df_gaps["derived_status"] == "posted").sum()) if not df_gaps.empty else 0
gap_fore      = int((df_gaps["derived_status"] == "forecasted").sum()) if not df_gaps.empty else 0
gap_peer_m    = float(df_gaps["peer_total_m"].sum()) if not df_gaps.empty else 0.0
if not df_gaps.empty:
    df_gaps["_days"] = df_gaps.apply(_close_days, axis=1)
    gap_closing = int((df_gaps["_days"].dropna() <= 60).sum())
else:
    gap_closing = 0

# Revisit metrics
rev_posted    = int((df_revisits["derived_status"] == "posted").sum()) if not df_revisits.empty else 0
if not df_revisits.empty:
    df_revisits["_days"] = df_revisits.apply(_close_days, axis=1)
    rev_closing = int((df_revisits["_days"].dropna() <= 60).sum())
else:
    rev_closing = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Programs Peers Won — UNT Absent", f"{len(df_gaps):,}",
    help="Open NOFOs where peer institutions have FY2023+ awards and UNT has none",
)
c2.metric(
    "UNT's Programs — Open Again", f"{len(df_revisits):,}",
    help="Open NOFOs in programs where UNT has historically won awards",
)
c3.metric(
    "Closing ≤ 60 Days", f"{gap_closing + rev_closing:,}",
    delta="act now" if (gap_closing + rev_closing) else None,
    delta_color="inverse" if (gap_closing + rev_closing) else "off",
)
c4.metric(
    "Peer Awards in Gap Programs", _fmt_m(gap_peer_m),
    help=f"Total peer funding under gap programs since FY{lookback_fy}",
)

# ---------------------------------------------------------------------------
# Agency grouping — map agency_code prefix to a readable parent label
# ---------------------------------------------------------------------------

# Longest-prefix-first so "HHS-NIH" matches before "HHS"
_AGENCY_MAP = {
    "HHS-NIH":    "NIH",
    "HHS-FDA":    "FDA",
    "HHS-CDC":    "CDC",
    "HHS-HRSA":   "HRSA",
    "HHS-SAMHS":  "SAMHSA",
    "HHS-ACL":    "HHS / ACL",
    "HHS-IHS":    "HHS / IHS",
    "HHS-OPHS":   "HHS",
    "HHS-ACF":    "HHS / ACF",
    "HHS":        "HHS",
    "NSF":        "NSF",
    "DOD-AMRAA":  "DOD / Army",
    "DOD-AMC":    "DOD / Army",
    "DOD-AFRL":   "DOD / Air Force",
    "DOD-NAVY":   "DOD / Navy",
    "DOD-ONR":    "DOD / Navy",
    "DOD-AF":     "DOD / Air Force",
    "DOD-AMC":    "DOD / Army",
    "DOD-AMRAA":  "DOD / Army",
    "DOD-AFRL":   "DOD / Air Force",
    "DOD":        "DOD",
    "USDA-NIFA":  "USDA / NIFA",
    "USDA-ARS":   "USDA / ARS",
    "USDA-APHIS": "USDA / APHIS",
    "USDA":       "USDA",
    "DOC-DOCNOAA":"NOAA",
    "DOC-EDA":    "Commerce / EDA",
    "DOC":        "Commerce",
    "NASA":       "NASA",
    "DOI-FWS":    "Interior / FWS",
    "DOI-NPS":    "Interior / NPS",
    "DOI-USGS":   "Interior / USGS",
    "DOI-BOR":    "Interior / BOR",
    "DOI":        "Interior",
    "ED":         "Education",
    "DOL-OESE":   "Education",    # Office of Elementary & Secondary Ed
    "DOL-OPE":    "Education",    # Office of Postsecondary Ed
    "DOL":        "Labor",
    "DOS":        "State Dept.",
    "DOT":        "DOT",
    "DOE":        "DOE",
    "DHS":        "DHS",
    "HUD":        "HUD",
    "NEH":        "NEH",
    "EPA":        "EPA",
    "USDOJ":      "DOJ",
    "DOJ":        "DOJ",
    "ONR":        "DOD / Navy",
}


def _parent_agency(code: str) -> str:
    """Map a Grants.gov agency_code to a short, readable parent label."""
    if not code:
        return "—"
    code = str(code).strip()
    for prefix, label in _AGENCY_MAP.items():
        if code.upper().startswith(prefix.upper()):
            return label
    # Fallback: return the first segment before '-'
    return code.split("-")[0]


# ---------------------------------------------------------------------------
# Shared formatting helpers
# ---------------------------------------------------------------------------

def fmt_ceiling(v) -> str:
    if pd.isna(v) or v == 0:
        return "—"
    return _fmt_m(v / 1e6)


def fmt_close(row) -> str:
    raw = row.get("close_date") or row.get("estimated_close_date")
    status = row.get("derived_status", "")
    if not raw:
        return "Open-ended" if status == "posted" else "TBD"
    try:
        d = date.fromisoformat(str(raw)[:10])
        days = (d - today).days
        label = str(raw)[:10]
        if days < 0:
            return f"Passed ({label})"
        elif days <= 30:
            return f"🔴 {label} ({days}d)"
        elif days <= 60:
            return f"🟡 {label} ({days}d)"
        else:
            return label
    except ValueError:
        return str(raw)[:10]


def fmt_awards(v) -> str:
    if pd.isna(v):
        return "—"
    return str(int(v))


def fmt_status(s: str) -> str:
    return "Posted" if s == "posted" else "Forecasted"


def fmt_peers(names_str: str, inst_count: int, total_m: float) -> str:
    if not names_str:
        return f"{inst_count} peers · {_fmt_m(total_m)}"
    names = [n.strip() for n in names_str.split(",")]
    short = [PEER_SHORT.get(n, n[:12]) for n in names[:3]]
    suffix = f" +{len(names) - 3}" if len(names) > 3 else ""
    return f"{', '.join(short)}{suffix} · {_fmt_m(total_m)}"


OPP_COL_CONFIG = {
    "Program":        st.column_config.TextColumn("Program", width="large"),
    "Agency":         st.column_config.TextColumn("Agency", width="small"),
    "Status":         st.column_config.TextColumn("Status", width="small"),
    "Closes":         st.column_config.TextColumn("Closes", width="medium"),
    "Max Award":      st.column_config.TextColumn("Max Award",
                          help="Maximum dollar amount the agency will award to a single recipient",
                          width="small"),
    "Est. # Funded":  st.column_config.TextColumn("Est. # Funded",
                          help="Agency's estimated number of grants to be awarded",
                          width="small"),
    "Opp #":          st.column_config.TextColumn("Opp #", width="medium"),
}

# ===========================================================================
# Panel 1 — Peer gaps
# ===========================================================================

st.divider()
st.subheader(f"Where peers are winning — and UNT isn't in the room  ({len(df_gaps):,})")
st.caption(
    f"Open solicitations in programs where your {peer_set.lower()} peers have won "
    f"since FY{lookback_fy} — and UNT has no awards in the same program."
)

if df_gaps.empty:
    st.info("No gap opportunities found for the selected filters.")
else:
    gaps_display = pd.DataFrame({
        "Program":      df_gaps["opportunity_title"],
        "Agency":       df_gaps["agency_code"].apply(_parent_agency),
        "Status":       df_gaps["derived_status"].apply(fmt_status),
        "Closes":       df_gaps.apply(fmt_close, axis=1),
        "Max Award":    df_gaps["award_ceiling"].apply(fmt_ceiling),
        "Est. # Funded":df_gaps["expected_number_of_awards"].apply(fmt_awards),
        "Peers Who Won":df_gaps.apply(
            lambda r: fmt_peers(r["peer_names"], r["peer_inst_count"], r["peer_total_m"]),
            axis=1,
        ),
        "Opp #":        df_gaps["opportunity_number"].fillna("—"),
    })
    st.dataframe(
        gaps_display,
        width="stretch",
        hide_index=True,
        column_config={
            **OPP_COL_CONFIG,
            "Peers Who Won": st.column_config.TextColumn("Peers Who Won", width="large"),
        },
    )

# ===========================================================================
# Panel 2 — UNT revisits
# ===========================================================================

st.divider()
st.subheader(f"Programs UNT has won before — open again  ({len(df_revisits):,})")
st.caption(
    "Open solicitations in programs where UNT holds at least one historical award (FY2019+). "
    "These are known territory — time to reapply."
)

if df_revisits.empty:
    st.info("No revisit opportunities found for the selected filters.")
else:
    rev_display = pd.DataFrame({
        "Program":       df_revisits["opportunity_title"],
        "Agency":        df_revisits["agency_code"].apply(_parent_agency),
        "Status":        df_revisits["derived_status"].apply(fmt_status),
        "Closes":        df_revisits.apply(fmt_close, axis=1),
        "Max Award":     df_revisits["award_ceiling"].apply(fmt_ceiling),
        "Est. # Funded": df_revisits["expected_number_of_awards"].apply(fmt_awards),
        "UNT History":   df_revisits.apply(
            lambda r: f"{int(r['unt_award_count'])} awards · {_fmt_m(r['unt_total_m'])} · last FY{int(r['unt_last_fy'])}",
            axis=1,
        ),
        "Opp #":         df_revisits["opportunity_number"].fillna("—"),
    })
    st.dataframe(
        rev_display,
        width="stretch",
        hide_index=True,
        column_config={
            **OPP_COL_CONFIG,
            "UNT History": st.column_config.TextColumn("UNT History", width="large"),
        },
    )

# ---------------------------------------------------------------------------
# Footnote
# ---------------------------------------------------------------------------

st.caption(
    "Source: Grants.gov daily extract · Awards: USASpending + NIH RePORTER · "
    f"Peer lookback: FY{lookback_fy}–present · UNT history: FY2019–present"
)
