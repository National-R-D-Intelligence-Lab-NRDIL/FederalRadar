"""
Portfolio Risk — Federal Radar
Shows agency concentration risk and what-if scenario analysis.

Primary question: How exposed are we if an agency gets cut?
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from queries import (
    ED_EXCLUSION_NOTE,
    MY_INSTITUTION,
    PEER_SHORT,
    get_fy_bounds,
    get_my_ueis,
    get_peer_institutions,
    get_portfolio_by_agency,
    get_portfolio_trend,
    get_peer_diversification,
)

st.set_page_config(page_title="Portfolio Risk — Federal Radar", layout="wide")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Portfolio Risk")
    st.caption(MY_INSTITUTION)
    st.divider()

    peer_set = st.radio("Peer Set", ["Texas", "National", "Both"], index=0)

    st.divider()

    fy_min, fy_max = get_fy_bounds()
    fy_start, fy_end = st.slider(
        "Fiscal Years",
        min_value=fy_min,
        max_value=fy_max,
        value=(fy_max - 4, fy_max),
    )

# ---------------------------------------------------------------------------
# Load UNT portfolio data
# ---------------------------------------------------------------------------

df_port = get_portfolio_by_agency(MY_INSTITUTION, fy_start, fy_end)

if df_port.empty:
    st.warning("No award data found for UNT in the selected fiscal year range.")
    st.stop()

total_funding = df_port["funding_m"].sum()

st.markdown("# Portfolio Risk")
st.caption(f"FY{fy_start}–{fy_end}")
st.caption(f"ℹ️ {ED_EXCLUSION_NOTE}")

# ---------------------------------------------------------------------------
# 1. Donut chart — UNT funding by agency
# ---------------------------------------------------------------------------

st.subheader("UNT Funding by Agency")

df_port["pct"] = (df_port["funding_m"] / total_funding * 100).round(1)
df_port["label"] = df_port["source"].str.upper() + " — $" + df_port["funding_m"].astype(str) + "M"

fig_donut = px.pie(
    df_port,
    values="funding_m",
    names="source",
    hole=0.45,
    color_discrete_sequence=px.colors.qualitative.Set2,
)
fig_donut.update_traces(
    textinfo="label+percent",
    textposition="outside",
    texttemplate="%{label}<br>%{percent:.1%}",
)
fig_donut.update_layout(
    margin=dict(t=20, b=20, l=20, r=20),
    height=420,
    showlegend=False,
    annotations=[dict(text=f"${total_funding:.1f}M", x=0.5, y=0.5,
                       font_size=22, showarrow=False)],
)

# Concentration warning
max_pct = df_port["pct"].max()
max_agency = df_port.loc[df_port["pct"].idxmax(), "source"].upper()

col_donut, col_warn = st.columns([3, 1])
with col_donut:
    st.plotly_chart(fig_donut, use_container_width=True)
with col_warn:
    if max_pct > 50:
        st.error(
            f"**High Concentration Risk**\n\n"
            f"{max_agency} accounts for **{max_pct:.0f}%** of UNT's portfolio. "
            f"A major cut to this agency would severely impact research funding."
        )
    elif max_pct > 35:
        st.warning(
            f"**Moderate Concentration**\n\n"
            f"{max_agency} accounts for **{max_pct:.0f}%** of UNT's portfolio."
        )
    else:
        st.success(
            f"**Well Diversified**\n\n"
            f"No single agency exceeds 35%. "
            f"Top agency: {max_agency} at {max_pct:.0f}%."
        )

st.divider()

# ---------------------------------------------------------------------------
# 2. What-If Scenario
# ---------------------------------------------------------------------------

st.subheader("What-If Scenario")
st.caption("Model the impact of a budget cut to a specific agency.")

col_agency, col_slider = st.columns(2)
with col_agency:
    agencies_list = df_port["source"].tolist()
    selected_agency = st.selectbox(
        "Agency to cut",
        agencies_list,
        format_func=str.upper,
    )
with col_slider:
    cut_pct = st.slider("Cut percentage", min_value=10, max_value=50, value=25, step=5)

agency_row = df_port[df_port["source"] == selected_agency].iloc[0]
agency_funding = agency_row["funding_m"]
loss = round(agency_funding * cut_pct / 100, 2)
new_agency = round(agency_funding - loss, 2)
new_total = round(total_funding - loss, 2)

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{selected_agency.upper()} Current", f"${agency_funding:.1f}M")
c2.metric(f"After {cut_pct}% Cut", f"${new_agency:.1f}M", delta=f"-${loss:.1f}M")
c3.metric("Total Before", f"${total_funding:.1f}M")
c4.metric("Total After", f"${new_total:.1f}M", delta=f"-${loss:.1f}M")

st.divider()

# ---------------------------------------------------------------------------
# 3. Peer Diversification Table
# ---------------------------------------------------------------------------

st.subheader("Peer Diversification Comparison")
st.caption(
    "HHI (Herfindahl–Hirschman Index) measures concentration: "
    "0 = perfectly diversified, 1 = single agency. "
    "Sorted by top agency share (most concentrated first). UNT row highlighted."
)

peer_items = get_peer_institutions(peer_set)
peer_names = [label for label, _ in peer_items]
all_names = [MY_INSTITUTION] + peer_names

df_div = get_peer_diversification(tuple(all_names), fy_start, fy_end)

if df_div.empty:
    st.info("No peer diversification data available.")
else:
    df_div["short"] = df_div["institution"].map(
        lambda x: "UNT" if x == MY_INSTITUTION else PEER_SHORT.get(x, x)
    )
    display_div = df_div[["short", "top_source", "top_pct", "n_sources", "hhi"]].copy()
    display_div.columns = ["Institution", "Top Agency", "Top Agency %", "# Agencies", "HHI"]
    display_div["Top Agency"] = display_div["Top Agency"].str.upper()
    display_div.index = range(1, len(display_div) + 1)

    def _highlight_unt(row):
        if row["Institution"] == "UNT":
            return ["background-color: #fff3cd"] * len(row)
        return [""] * len(row)

    styled_div = display_div.style.apply(_highlight_unt, axis=1).format({
        "Top Agency %": "{:.1f}%",
        "HHI": "{:.4f}",
    })
    st.dataframe(styled_div, use_container_width=True,
                 height=min(600, 55 + 38 * len(display_div)))

st.divider()

# ---------------------------------------------------------------------------
# 4. Agency Trend — UNT funding by FY per agency
# ---------------------------------------------------------------------------

st.subheader("Agency Trend — UNT Funding by Year")
st.caption("How UNT's funding from each agency has changed over time.")

df_trend = get_portfolio_trend(MY_INSTITUTION, fy_start, fy_end)

if df_trend.empty:
    st.info("No trend data available.")
else:
    df_trend["source"] = df_trend["source"].str.upper()
    fig_trend = px.bar(
        df_trend,
        x="fiscal_year",
        y="funding_m",
        color="source",
        barmode="group",
        labels={"fiscal_year": "Fiscal Year", "funding_m": "Funding ($M)", "source": "Agency"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_trend.update_layout(
        margin=dict(t=20, b=10, l=0, r=20),
        height=400,
        xaxis=dict(dtick=1),
    )
    st.plotly_chart(fig_trend, use_container_width=True)
