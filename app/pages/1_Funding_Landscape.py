"""
Funding Landscape — Federal Radar
Where is federal research money flowing?

Top bar chart: all agencies, last 4 FYs.
Sankey drill-down: Agency → Programs → States.
Table drill-down: State → Institutions.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from queries import (
    MY_INSTITUTION,
    landscape_agency_trends,
    landscape_programs_by_fy,
    landscape_states,
    landscape_institutions,
    get_my_ueis,
)

st.set_page_config(page_title="Funding Landscape — Federal Radar", layout="wide")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AGENCY_LABELS = {
    "nih": "NIH", "nsf": "NSF", "ed": "Education", "dod": "DOD",
    "doe": "DOE", "hhs": "HHS", "usda": "USDA", "nasa": "NASA",
    "commerce": "Commerce", "dot": "DOT", "epa": "EPA", "neh": "NEH",
    "dhs": "DHS",
}

# Colorblind-friendly palette — four distinct hues
FY_COLORS = {0: "#E69F00", 1: "#56B4E9", 2: "#009E73", 3: "#D55E00"}


def _short_label(v_m):
    """Format dollar amount: $8.50B, $803M, $47K — 2 decimals for billions."""
    if v_m >= 1_000:
        return f"${v_m / 1_000:.2f}B"
    if v_m >= 1:
        return f"${int(round(v_m))}M"
    if v_m >= 0.001:
        return f"${int(round(v_m * 1_000))}K"
    return "$0"


def _pct_change(current, prior):
    if prior and prior > 0:
        return (current - prior) / prior * 100
    return None


def _change_str(pct):
    if pct is None:
        return "new"
    if pct >= 0:
        return f"+{pct:.0f}%"
    return f"{pct:.0f}%"


def _style_change(val):
    if isinstance(val, str) and val.startswith("+"):
        return "color: #2ecc71; font-weight: bold"
    if isinstance(val, str) and val.startswith("-"):
        return "color: #e74c3c; font-weight: bold"
    return "color: #3498db"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

my_ueis = set(get_my_ueis())

with st.sidebar:
    st.markdown("## Funding Landscape")
    st.caption("Where is federal research money flowing?")
    st.divider()
    fy = st.selectbox("Fiscal Year", list(range(2026, 2019, -1)), index=0)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown("# Funding Landscape")
st.caption("Where is federal research money flowing?")
st.caption(
    "Federal research awards to all recipients including universities, hospitals, "
    "and companies. Totals reflect our database coverage, not full agency budgets."
)

# =========================================================================
# Top Chart: All agencies, last 4 FYs — horizontal grouped bars
# =========================================================================

n_years = 4
fy_start = fy - n_years + 1
fy_list = list(range(fy_start, fy + 1))

df_trends = landscape_agency_trends(fy, n_years)

if df_trends.empty:
    st.warning(f"No award data found for FY{fy_start}–FY{fy}.")
    st.stop()

# Add labels
df_trends["label"] = df_trends["source"].map(AGENCY_LABELS).fillna(
    df_trends["source"].str.upper()
)

# Pivot for ordering: sort agencies by most recent FY total descending
latest = df_trends[df_trends["fiscal_year"] == fy].sort_values(
    "total_m", ascending=False
)
agency_order = latest["label"].tolist()

fig = go.Figure()

for i, year in enumerate(fy_list):
    yr_data = df_trends[df_trends["fiscal_year"] == year]
    yr_map = dict(zip(yr_data["label"], yr_data["total_m"]))
    vals = [yr_map.get(a, 0) for a in agency_order]
    labels = [_short_label(v) for v in vals]

    fig.add_trace(go.Bar(
        x=agency_order,
        y=vals,
        name=f"FY{year}",
        marker_color=FY_COLORS.get(i, "#2c3e50"),
        text=labels,
        textposition="outside",
        textfont_size=10,
        cliponaxis=False,
    ))

fig.update_layout(
    barmode="group",
    height=500,
    margin=dict(t=40, b=30, l=0, r=0),
    yaxis=dict(title="", showticklabels=False),
    legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
    bargap=0.15,
    bargroupgap=0.05,
    font=dict(color="#2c3e50", family="sans-serif"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)

st.plotly_chart(fig, use_container_width=True)

# =========================================================================
# Agency selector → Sankey: Agency → Programs
# =========================================================================

st.divider()

agency_totals = (
    df_trends[df_trends["fiscal_year"] == fy]
    .sort_values("total_m", ascending=False)
)
agency_map = dict(zip(agency_totals["label"], agency_totals["source"]))

selected_label = st.selectbox(
    "Select an agency to see where the money flows",
    options=[""] + list(agency_map.keys()),
    index=0,
    key="agency_select",
)

if not selected_label:
    st.stop()

selected_agency = agency_map[selected_label]

# =========================================================================
# Sankey: Agency → Fiscal Years → Programs
# =========================================================================

df_prog_fy = landscape_programs_by_fy(selected_agency, fy, n_years)

if df_prog_fy.empty:
    st.info(f"No program-level data for {selected_label}.")
    st.stop()

# Identify top programs by total across all years
top_prog_ids = (
    df_prog_fy.groupby("program_id")["total_m"]
    .sum()
    .nlargest(12)
    .index.tolist()
)
top_prog_names = {}
for _, r in df_prog_fy.iterrows():
    if r["program_id"] in top_prog_ids and r["program_id"] not in top_prog_names:
        top_prog_names[r["program_id"]] = r["program"]

total_all = df_prog_fy["total_m"].sum()
st.caption(
    f"**{selected_label}** awarded **{_short_label(total_all)}** "
    f"across FY{fy_start}–FY{fy}."
)

# --- Build Sankey nodes ---
# Column 1: Agency (index 0)
# Column 2: Fiscal years (indices 1..n_years)
# Column 3: Programs (indices n_years+1..)

# Colorblind-friendly: reuse FY_COLORS for FY nodes, distinct palette for programs
PROG_COLORS = [
    "#332288", "#88CCEE", "#44AA99", "#117733", "#999933", "#DDCC77",
    "#CC6677", "#882255", "#AA4499", "#661100", "#6699CC", "#DDDDDD",
]

sankey_labels = [selected_label]
sankey_colors = ["#2c3e50"]

# FY nodes
fy_indices = {}
for i, year in enumerate(fy_list):
    sankey_labels.append(f"FY{year}")
    sankey_colors.append(FY_COLORS.get(i, "#2c3e50"))
    fy_indices[year] = len(sankey_labels) - 1

# Program nodes
prog_indices = {}
for i, pid in enumerate(top_prog_ids):
    name = top_prog_names[pid]
    sankey_labels.append(name)
    sankey_colors.append(PROG_COLORS[i % len(PROG_COLORS)])
    prog_indices[pid] = len(sankey_labels) - 1

# "Other programs" node
sankey_labels.append("Other programs")
sankey_colors.append("#95a5a6")
other_prog_idx = len(sankey_labels) - 1

# --- Build Sankey links ---
sources = []
targets = []
values = []
link_colors = []

# Agency → FY links
for year in fy_list:
    yr_total = df_prog_fy[df_prog_fy["fiscal_year"] == year]["total_m"].sum()
    if yr_total > 0:
        i = list(fy_list).index(year)
        sources.append(0)
        targets.append(fy_indices[year])
        values.append(round(yr_total, 1))
        c = FY_COLORS.get(i, "#2c3e50")
        # Convert hex to rgba for link transparency
        r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        link_colors.append(f"rgba({r},{g},{b},0.2)")

# FY → Program links
for year in fy_list:
    yr_data = df_prog_fy[df_prog_fy["fiscal_year"] == year]
    other_total = 0.0
    for _, row in yr_data.iterrows():
        if row["program_id"] in prog_indices:
            pi = prog_indices[row["program_id"]]
            pc = sankey_colors[pi]
            r, g, b = int(pc[1:3], 16), int(pc[3:5], 16), int(pc[5:7], 16)
            sources.append(fy_indices[year])
            targets.append(pi)
            values.append(round(row["total_m"], 1))
            link_colors.append(f"rgba({r},{g},{b},0.15)")
        else:
            other_total += row["total_m"]
    if other_total > 0:
        sources.append(fy_indices[year])
        targets.append(other_prog_idx)
        values.append(round(other_total, 1))
        link_colors.append("rgba(149,165,166,0.12)")


# --- Render Sankey ---
# Use max(incoming, outgoing) to avoid double-counting intermediate nodes
node_incoming = [0.0] * len(sankey_labels)
node_outgoing = [0.0] * len(sankey_labels)
for s, t, v in zip(sources, targets, values):
    node_outgoing[s] += v
    node_incoming[t] += v
node_values = [max(i, o) for i, o in zip(node_incoming, node_outgoing)]

# Node labels with dollar amounts baked in
node_display_labels = [
    f"{sankey_labels[i]}  {_short_label(node_values[i])}"
    for i in range(len(sankey_labels))
]
node_customdata = [_short_label(v) for v in node_values]

fig_sankey = go.Figure(go.Sankey(
    arrangement="snap",
    node=dict(
        pad=18,
        thickness=25,
        label=node_display_labels,
        color=sankey_colors,
        customdata=node_customdata,
        hovertemplate="%{customdata}<extra></extra>",
    ),
    link=dict(
        source=sources,
        target=targets,
        value=values,
        color=link_colors,
        customdata=[_short_label(v) for v in values],
        hovertemplate="%{source.label} → %{target.label}: %{customdata}<extra></extra>",
    ),
    textfont=dict(size=12, color="#000000", family="Arial, sans-serif"),
))

sankey_height = max(550, len(top_prog_ids) * 40 + 200)

fig_sankey.update_layout(
    height=sankey_height,
    margin=dict(t=20, b=20, l=20, r=20),
    font=dict(size=12, color="#000000", family="Arial, sans-serif"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)

st.plotly_chart(fig_sankey, use_container_width=True)

# =========================================================================
# Program selector → focused Sankey: Program → States only
# =========================================================================

prog_select_options = [top_prog_names[pid] for pid in top_prog_ids]
prog_name_to_id = {v: k for k, v in top_prog_names.items()}

selected_program = st.selectbox(
    "Select a program to see state distribution",
    options=[""] + prog_select_options,
    index=0,
    key="program_select",
)

if selected_program:
    selected_program_id = prog_name_to_id[selected_program]
    df_states = landscape_states(selected_agency, selected_program_id, fy)

    if df_states.empty:
        st.info(f"No state data for {selected_program} in FY{fy}.")
    else:
        df_states["current_m"] = df_states["fy_current"] / 1e6
        top_states = df_states.head(15).copy()
        rest_states = df_states.iloc[15:]["current_m"].sum() if len(df_states) > 15 else 0.0

        # --- Focused Sankey: single program → states ---
        foc_labels = [selected_program]
        foc_colors = ["#2c3e50"]
        foc_sources, foc_targets, foc_values, foc_link_colors = [], [], [], []

        for _, srow in top_states.iterrows():
            foc_labels.append(srow["state"])
            if srow["state"] == "TX":
                foc_colors.append("#E69F00")
                foc_link_colors.append("rgba(230,159,0,0.3)")
            else:
                foc_colors.append("#009E73")
                foc_link_colors.append("rgba(0,158,115,0.2)")
            foc_sources.append(0)
            foc_targets.append(len(foc_labels) - 1)
            foc_values.append(round(srow["current_m"], 1))

        if rest_states > 0:
            foc_labels.append("Other states")
            foc_colors.append("#95a5a6")
            foc_link_colors.append("rgba(149,165,166,0.15)")
            foc_sources.append(0)
            foc_targets.append(len(foc_labels) - 1)
            foc_values.append(round(rest_states, 1))

        foc_node_in = [0.0] * len(foc_labels)
        foc_node_out = [0.0] * len(foc_labels)
        for s, t, v in zip(foc_sources, foc_targets, foc_values):
            foc_node_out[s] += v
            foc_node_in[t] += v
        foc_node_vals = [max(i, o) for i, o in zip(foc_node_in, foc_node_out)]
        foc_display = [
            f"{foc_labels[i]}  {_short_label(foc_node_vals[i])}"
            for i in range(len(foc_labels))
        ]

        fig_focused = go.Figure(go.Sankey(
            arrangement="snap",
            node=dict(
                pad=14, thickness=25,
                label=foc_display, color=foc_colors,
                customdata=[_short_label(v) for v in foc_node_vals],
                hovertemplate="%{customdata}<extra></extra>",
            ),
            link=dict(
                source=foc_sources, target=foc_targets, value=foc_values,
                color=foc_link_colors,
                customdata=[_short_label(v) for v in foc_values],
                hovertemplate="%{source.label} → %{target.label}: %{customdata}<extra></extra>",
            ),
            textfont=dict(size=12, color="#000000", family="Arial, sans-serif"),
        ))
        fig_focused.update_layout(
            height=max(400, len(foc_labels) * 32 + 100),
            margin=dict(t=20, b=20, l=20, r=20),
            font=dict(size=12, color="#000000", family="Arial, sans-serif"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_focused, use_container_width=True)

        # =====================================================================
        # Institution table
        # =====================================================================

        st.divider()
        state_list = df_states.sort_values("fy_current", ascending=False)["state"].tolist()
        default_idx = (state_list.index("TX") + 1) if "TX" in state_list else 0

        selected_state = st.selectbox(
            "Select a state to see institutions",
            options=[""] + state_list,
            index=default_idx,
            key="state_select",
        )

        if selected_state:
            df_inst = landscape_institutions(
                selected_agency, selected_program_id, selected_state, fy
            )

            if df_inst.empty:
                st.info(f"No institutions in {selected_state} for "
                        f"{selected_program} in FY{fy}.")
            else:
                df_inst["current_m"] = df_inst["fy_current"] / 1e6
                df_inst["prior_m"] = df_inst["fy_prior"] / 1e6
                df_inst["pct"] = df_inst.apply(
                    lambda r: _pct_change(r["fy_current"], r["fy_prior"]), axis=1
                )

                total_st = df_inst["current_m"].sum()
                st.caption(
                    f"**{selected_program}** awarded **{_short_label(total_st)}** "
                    f"to {len(df_inst)} institutions in {selected_state} in FY{fy}."
                )

                tbl = df_inst.copy()
                tbl["Institution"] = tbl["institution"]
                tbl[f"FY{fy}"] = tbl["current_m"].apply(_short_label)
                tbl[f"FY{fy - 1}"] = tbl["prior_m"].apply(_short_label)
                tbl["Change"] = tbl["pct"].apply(_change_str)
                tbl["Awards"] = tbl["awards_current"].astype(int)

                cols = ["Institution", f"FY{fy}", f"FY{fy - 1}", "Change", "Awards"]
                df_show = tbl[cols].reset_index(drop=True)
                df_show.index = range(1, len(df_show) + 1)

                def _style_unt_row(row):
                    idx = row.name - 1
                    if idx < len(df_inst) and df_inst.iloc[idx]["inst_uei"] in my_ueis:
                        return ["background-color: #fef9e7; font-weight: bold"] * len(row)
                    return [""] * len(row)

                styled = df_show.style.map(
                    _style_change, subset=["Change"]
                ).apply(_style_unt_row, axis=1)
                st.dataframe(styled, use_container_width=True,
                             height=min(600, 55 + 38 * len(df_show)))
