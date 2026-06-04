"""
Expiring Awards — Federal Radar
Shows awards nearing their end date and funding at risk.

Primary question: What funding are we about to lose?
"""

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from queries import (
    ED_EXCLUSION_NOTE,
    MY_INSTITUTION,
    get_agencies,
    get_expiring_awards,
    get_expiring_summary,
)

st.set_page_config(page_title="Expiring Awards — Federal Radar", layout="wide")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Expiring Awards")
    st.caption(MY_INSTITUTION)
    st.divider()

    horizon_months = st.selectbox("Horizon", [6, 12, 18, 24], index=1,
                                  format_func=lambda x: f"{x} months")

    st.divider()

    all_agencies = get_agencies()
    agency_choice = st.selectbox(
        "Agency",
        ["All"] + all_agencies,
        format_func=lambda x: x.upper() if x != "All" else "All Agencies",
    )
    agency_filter = agency_choice if agency_choice != "All" else None

today = date.today()
horizon_date = (today + timedelta(days=horizon_months * 30)).isoformat()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

summary = get_expiring_summary(MY_INSTITUTION, horizon_date, agency_filter)
df_exp = get_expiring_awards(MY_INSTITUTION, horizon_date, agency_filter)

st.markdown("# Expiring Awards")
st.caption(f"Awards ending within {horizon_months} months (by {horizon_date})")
st.caption(f"ℹ️ {ED_EXCLUSION_NOTE}")

# ---------------------------------------------------------------------------
# 1. Scorecard
# ---------------------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
c1.metric("Awards Expiring", f"{summary['total_awards']:,}")
c2.metric("Funding at Risk", f"${summary['total_funding_m']:.1f}M")
c3.metric("Largest Expiration", f"${summary['largest_award_m']:.2f}M")
c4.metric("PIs Affected", f"{summary['pis_affected']:,}")

if df_exp.empty:
    st.info("No awards expiring within the selected horizon.")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# 2. Funding Cliff Chart — stacked bar by quarter
# ---------------------------------------------------------------------------

st.subheader("Funding Cliff")
st.caption("Total funding expiring by quarter, colored by agency. The 'cliff' shows when the most funding is at risk.")

df_chart = df_exp.copy()
df_chart["end_date"] = pd.to_datetime(df_chart["project_end_date"])
df_chart["quarter"] = df_chart["end_date"].dt.to_period("Q").astype(str)
df_chart["source_upper"] = df_chart["source"].str.upper()
df_chart["amount_m"] = df_chart["awd_amount"] / 1e6

cliff = (
    df_chart.groupby(["quarter", "source_upper"])["amount_m"]
    .sum()
    .reset_index()
    .rename(columns={"source_upper": "Agency", "amount_m": "Funding ($M)"})
    .sort_values("quarter")
)

fig_cliff = px.bar(
    cliff,
    x="quarter",
    y="Funding ($M)",
    color="Agency",
    labels={"quarter": "Quarter"},
    color_discrete_sequence=px.colors.qualitative.Set2,
)
fig_cliff.update_layout(
    margin=dict(t=20, b=10, l=0, r=20),
    height=380,
    barmode="stack",
)
st.plotly_chart(fig_cliff, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# 3. Expiring Awards Table
# ---------------------------------------------------------------------------

st.subheader("Expiring Awards Detail")

df_table = df_exp.copy()
df_table["source"] = df_table["source"].str.upper()
df_table["awd_amount"] = (df_table["awd_amount"] / 1e6).round(3)
df_table["pi_name"] = df_table["pi_name"].fillna("—")
df_table["program"] = df_table["program"].fillna("—")

display_cols = {
    "project_end_date": "End Date",
    "pi_name": "PI",
    "source": "Agency",
    "program": "Program",
    "awd_amount": "Amount ($M)",
    "title": "Title",
}
df_display = df_table.rename(columns=display_cols)[list(display_cols.values())]
df_display.index = range(1, len(df_display) + 1)

st.dataframe(df_display, use_container_width=True,
             height=min(600, 55 + 38 * len(df_display)))

# CSV download
csv = df_display.to_csv()
st.download_button(
    "Download expiring awards (CSV)",
    csv,
    file_name=f"expiring_awards_{horizon_months}mo.csv",
    mime="text/csv",
)

st.divider()

# ---------------------------------------------------------------------------
# 4. Agency Breakdown — horizontal bar
# ---------------------------------------------------------------------------

st.subheader("Expiring Funding by Agency")
st.caption("Which agencies have the most expiring funding.")

agency_totals = (
    df_chart.groupby("source_upper")["amount_m"]
    .sum()
    .reset_index()
    .rename(columns={"source_upper": "Agency", "amount_m": "Funding ($M)"})
    .sort_values("Funding ($M)", ascending=True)
)

fig_agency = px.bar(
    agency_totals,
    x="Funding ($M)",
    y="Agency",
    orientation="h",
    color_discrete_sequence=["#e74c3c"],
)
fig_agency.update_layout(
    margin=dict(t=10, b=10, l=0, r=20),
    height=max(250, 40 * len(agency_totals)),
    showlegend=False,
)
st.plotly_chart(fig_agency, use_container_width=True)
