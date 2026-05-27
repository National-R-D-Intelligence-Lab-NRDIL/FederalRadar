"""
Home.py — Program Explorer
Federal Radar Streamlit MVP

Answers: "How competitive is this program, and where does my institution rank?"
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from queries import (
    get_agencies,
    get_gap_programs,
    get_my_institution_rank,
    get_nih_activity_codes,
    get_nih_institutes,
    get_nsf_directorates,
    get_nsf_subdiv,
    get_nsf_programs,
    get_program_stats,
    get_state_distribution,
    get_top_institutions,
    get_trend,
)

st.set_page_config(
    page_title="Federal Radar – Program Explorer",
    page_icon="🎯",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🎯 Federal Radar")
    st.caption("Program Explorer")

    my_inst = st.text_input("My Institution", value="NORTH TEXAS")

    agencies = get_agencies()
    source = st.selectbox("Agency", agencies, index=agencies.index("nsf") if "nsf" in agencies else 0)

    division = subdiv = program = institute = activity_code = cfda = None

    if source == "nsf":
        directorates = get_nsf_directorates()
        if directorates:
            division = st.selectbox("Directorate", ["(All)"] + directorates)
            if division == "(All)":
                division = None
        if division:
            subdivs = get_nsf_subdiv(division)
            if subdivs:
                subdiv = st.selectbox("Division", ["(All)"] + subdivs)
                if subdiv == "(All)":
                    subdiv = None
        if division:
            programs = get_nsf_programs(division, subdiv)
            if programs:
                program = st.selectbox("Program", ["(All)"] + programs)
                if program == "(All)":
                    program = None

    elif source == "nih":
        institutes = get_nih_institutes()
        if institutes:
            institute = st.selectbox("Institute", ["(All)"] + institutes)
            if institute == "(All)":
                institute = None
        codes = get_nih_activity_codes(institute)
        if codes:
            activity_code = st.selectbox("Activity Code", ["(All)"] + codes)
            if activity_code == "(All)":
                activity_code = None

    else:
        cfda = st.text_input("CFDA / Opportunity #", "")
        if not cfda:
            cfda = None

    st.divider()
    st.caption("Data: NSF, NIH, ED, DOT, NEH · FY2019–2026")

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

st.header("Program Explorer")

# --- Metrics row ---
stats = get_program_stats(source, division, subdiv, program, institute, activity_code, cfda)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Awards", f"{stats['awards']:,}")
c2.metric("Total Funding", f"${stats['total_funding']/1e9:.2f}B" if stats['total_funding'] >= 1e9 else f"${stats['total_funding']/1e6:.1f}M")
c3.metric("Avg Award", f"${stats['avg_award']/1e6:.3f}M")
c4.metric("Institutions", f"{stats['institutions']:,}")

st.divider()

# --- Two-column layout: Trend + Map ---
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("Funding Trend")
    trend_df = get_trend(source, division, subdiv, program, institute, activity_code, cfda)
    if not trend_df.empty:
        fig = px.bar(
            trend_df, x="fiscal_year", y="total_m",
            labels={"fiscal_year": "Fiscal Year", "total_m": "Total ($M)"},
            color_discrete_sequence=["#0068C9"],
        )
        fig.update_layout(margin=dict(t=10, b=10), height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No trend data available.")

with col_right:
    st.subheader("Awards by State")
    state_df = get_state_distribution(source, division, subdiv, program, institute, activity_code, cfda)
    if not state_df.empty:
        fig = px.choropleth(
            state_df,
            locations="state",
            locationmode="USA-states",
            color="total_m",
            scope="usa",
            color_continuous_scale="Blues",
            labels={"total_m": "$M", "state": "State"},
        )
        fig.update_layout(margin=dict(t=10, b=10, l=0, r=0), height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No state data available.")

st.divider()

# --- My Institution Rank ---
if my_inst.strip():
    rank_info = get_my_institution_rank(
        my_inst, source, division, subdiv, program, institute, activity_code, cfda
    )
    if rank_info:
        st.success(
            f"**{rank_info['name']}** — Rank **#{rank_info['rank']}** of "
            f"{rank_info['total']:,} institutions · "
            f"{rank_info['awards']} awards · ${rank_info['total_m']:.2f}M total"
        )
    else:
        st.warning(f"No awards found matching '{my_inst}' in this program.")

# --- Top Institutions table ---
st.subheader("Top 25 Institutions")
top_df = get_top_institutions(source, division, subdiv, program, institute, activity_code, cfda)

if not top_df.empty and my_inst.strip():
    # Highlight my institution rows
    search_upper = my_inst.upper()

    def _highlight(row):
        inst = str(row.get("Institution", "")).upper()
        if search_upper in inst:
            return ["background-color: #fffacd"] * len(row)
        return [""] * len(row)

    st.dataframe(top_df.style.apply(_highlight, axis=1), use_container_width=True)
else:
    st.dataframe(top_df, use_container_width=True)

# --- Gap Programs (NSF only) ---
if source == "nsf" and (division or subdiv) and my_inst.strip():
    st.divider()
    st.subheader("🔍 Gap Programs")
    label = subdiv or division
    st.caption(
        f"NSF {label} programs where **≥3 peer institutions** win awards "
        f"but **{my_inst}** has none."
    )
    gap_df = get_gap_programs(subdiv or division, my_inst, use_div_abbr=bool(subdiv))
    if not gap_df.empty:
        st.dataframe(gap_df, use_container_width=True)
    else:
        st.info("No gap programs found — great coverage!")
