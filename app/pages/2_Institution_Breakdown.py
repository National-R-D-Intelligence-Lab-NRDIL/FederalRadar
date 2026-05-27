"""
2_Institution_Breakdown.py — Institution Breakdown
Federal Radar Streamlit MVP

Answers: "How is a specific institution performing across all federal agencies?"
"""

import plotly.express as px
import streamlit as st

from queries import (
    get_agencies,
    get_institution_awards,
    get_institution_by_agency,
    get_institution_pis,
    get_institution_summary,
    get_institution_trend,
    search_institutions,
)

st.set_page_config(
    page_title="Federal Radar – Institution Breakdown",
    page_icon="🏛️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar — institution search
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🎯 Federal Radar")
    st.caption("Institution Breakdown")

    query = st.text_input("Search Institution", value="NORTH TEXAS")
    inst_name = None

    if query.strip():
        matches = search_institutions(query.strip())
        if matches:
            inst_name = st.selectbox("Select", matches)
        else:
            st.warning("No institutions found.")

    st.divider()

    source_filter = None
    fy_filter = None

    if inst_name:
        agencies = get_agencies()
        source_filter = st.selectbox("Filter by Agency", ["(All)"] + agencies)
        if source_filter == "(All)":
            source_filter = None

        fy_input = st.text_input("Filter by FY (e.g. 2023)", "")
        if fy_input.strip().isdigit():
            fy_filter = int(fy_input.strip())

    st.caption("Data: NSF, NIH, ED, DOT, NEH · FY2019–2026")

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

st.header("Institution Breakdown")

if not inst_name:
    st.info("Search for an institution in the sidebar to get started.")
    st.stop()

# --- Summary metrics ---
summary = get_institution_summary(inst_name)

st.subheader(inst_name)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Awards", f"{summary['awards']:,}")
c2.metric("Total Funding", f"${summary['total_m']:.1f}M")
c3.metric("Agencies", summary["agencies"])
c4.metric("First FY", summary["first_fy"] or "—")
c5.metric("Last FY", summary["last_fy"] or "—")

st.divider()

# --- By-agency breakdown + trend side by side ---
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("Funding by Agency")
    agency_df = get_institution_by_agency(inst_name)
    if not agency_df.empty:
        fig = px.bar(
            agency_df,
            x="Agency",
            y="Total ($M)",
            color="Agency",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(showlegend=False, margin=dict(t=10, b=10), height=300)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(agency_df, use_container_width=True, hide_index=True)
    else:
        st.info("No agency data available.")

with col_right:
    st.subheader("Funding Trend by Agency")
    trend_df = get_institution_trend(inst_name)
    if not trend_df.empty:
        fig = px.area(
            trend_df,
            x="fiscal_year",
            y="total_m",
            color="source",
            labels={"fiscal_year": "Fiscal Year", "total_m": "Total ($M)", "source": "Agency"},
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(margin=dict(t=10, b=10), height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No trend data available.")

st.divider()

# --- Top PIs ---
st.subheader("Top Principal Investigators")
pi_df = get_institution_pis(inst_name, source_filter)
if not pi_df.empty:
    st.dataframe(pi_df.head(20), use_container_width=True, hide_index=True)
else:
    st.info("No PI data available (USASpending records do not include PI names).")

st.divider()

# --- Award detail table ---
st.subheader("Award Detail")
awards_df = get_institution_awards(inst_name, source_filter, fy_filter)
if not awards_df.empty:
    st.caption(f"{len(awards_df):,} awards shown")
    st.dataframe(awards_df, use_container_width=True, hide_index=True)
else:
    st.info("No awards found for the selected filters.")
