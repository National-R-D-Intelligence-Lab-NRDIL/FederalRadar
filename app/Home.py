"""
Home.py — Federal Radar
Single-page competitive gap analysis for VPR/AVP.

Primary question: In [agency/program], where are peers beating us,
and by how much? Sorted by funding opportunity.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from queries import (
    MY_INSTITUTION,
    NSF_DIR_NAMES,
    NSF_DIV_NAMES,
    PEER_SHORT,
    get_field_wide_stats,
    get_fy_bounds,
    get_heatmap_data,
    get_my_ueis,
    get_nih_institutes,
    get_nsf_directorates,
    get_nsf_subdiv,
    get_peer_institutions,
    get_raw_comparison,
)

st.set_page_config(
    page_title="Federal Radar",
    page_icon="radar",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Federal Radar")
    st.caption(MY_INSTITUTION)
    st.divider()

    agency = st.selectbox(
        "Agency",
        ["nsf", "nih", "dod", "doe", "nasa", "usda", "ed", "commerce"],
        format_func=str.upper,
    )

    dir_filter = subdiv_filter = institute_filter = None

    if agency == "nsf":
        dirs = get_nsf_directorates()
        dir_labels = {d: f"{d} — {NSF_DIR_NAMES[d]}" if d in NSF_DIR_NAMES else d for d in dirs}
        dir_choice = st.selectbox(
            "Directorate", ["(All)"] + dirs,
            format_func=lambda x: dir_labels.get(x, x) if x != "(All)" else "(All)",
        )
        dir_filter = dir_choice if dir_choice != "(All)" else None
        if dir_filter:
            subdivs = get_nsf_subdiv(dir_filter)
            if subdivs:
                div_labels = {d: f"{d} — {NSF_DIV_NAMES[d]}" if d in NSF_DIV_NAMES else d for d in subdivs}
                sub_choice = st.selectbox(
                    "Division", ["(All)"] + subdivs,
                    format_func=lambda x: div_labels.get(x, x) if x != "(All)" else "(All)",
                )
                subdiv_filter = sub_choice if sub_choice != "(All)" else None

    elif agency == "nih":
        insts = get_nih_institutes()
        choice = st.selectbox("Institute", ["(All)"] + insts)
        institute_filter = choice if choice != "(All)" else None

    st.divider()

    peer_set = st.radio("Peer Set", ["Texas", "National", "Both"], index=0)

    st.divider()

    fy_min, fy_max = get_fy_bounds()
    fy_start, fy_end = st.slider(
        "Fiscal Years",
        min_value=fy_min,
        max_value=fy_max,
        value=(fy_max - 2, fy_max),
    )

    st.divider()
    st.caption(f"Data: NSF, NIH, DOD, DOE, NASA, USDA, ED · FY{fy_min}-{fy_max}")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

my_ueis   = tuple(get_my_ueis())
peer_items = get_peer_institutions(peer_set)
peer_ueis  = tuple(uei for _, uei in peer_items)

df_raw = get_raw_comparison(
    my_ueis, peer_ueis, agency, fy_start, fy_end,
    dir_filter, subdiv_filter, institute_filter,
)
df_field = get_field_wide_stats(
    agency, fy_start, fy_end,
    dir_filter, subdiv_filter, institute_filter,
)

# ---------------------------------------------------------------------------
# Scope label for header
# ---------------------------------------------------------------------------

scope_parts = [agency.upper()]
if dir_filter:
    scope_parts.append(dir_filter)
if subdiv_filter:
    scope_parts.append(subdiv_filter)
if institute_filter:
    scope_parts.append(institute_filter)
scope_label = " / ".join(scope_parts)

st.markdown(f"# {scope_label}")
st.caption(f"FY{fy_start}–{fy_end}  ·  {peer_set} peers")

# ---------------------------------------------------------------------------
# Handle unsupported agency or empty data
# ---------------------------------------------------------------------------

if df_raw.empty:
    st.info("No award data found for this filter combination.")
    st.stop()

# ---------------------------------------------------------------------------
# Build pivot: programs x institutions
# ---------------------------------------------------------------------------

pivot_n = df_raw.pivot_table(
    index="program_abbr", columns="institution",
    values="awards", aggfunc="sum", fill_value=0,
)
pivot_m = df_raw.pivot_table(
    index="program_abbr", columns="institution",
    values="funding_m", aggfunc="sum", fill_value=0,
)

# Build abbr -> full name mapping from the data for display
# Strip NSF structural prefixes (e.g. "Directorate for ", "Division of ")
_NSF_PREFIXES = (
    "Directorate for ", "Directorate, ", "Directorate - ",
    "Division of ", "Division for ", "Division - ",
    "Office of ", "Office for ",
)

def _clean_name(name: str) -> str:
    for prefix in _NSF_PREFIXES:
        if isinstance(name, str) and name.startswith(prefix):
            return name[len(prefix):]
    return name

abbr_to_name = (
    df_raw[["program_abbr", "program"]]
    .drop_duplicates("program_abbr")
    .set_index("program_abbr")["program"]
    .map(_clean_name)
    .to_dict()
)

# Ensure UNT column exists
if MY_INSTITUTION not in pivot_n.columns:
    pivot_n[MY_INSTITUTION] = 0
    pivot_m[MY_INSTITUTION] = 0.0

peer_cols = [c for c in pivot_n.columns if c != MY_INSTITUTION]

# ---------------------------------------------------------------------------
# Scorecard row
# ---------------------------------------------------------------------------

unt_df   = df_raw[df_raw["institution"] == MY_INSTITUTION]
peers_df = df_raw[df_raw["institution"] != MY_INSTITUTION]

unt_total_awards  = int(unt_df["awards"].sum())
unt_total_funding = round(unt_df["funding_m"].sum(), 1)

# Rank UNT vs all peers by total funding in scope
totals = (
    df_raw.groupby("institution")["funding_m"]
    .sum()
    .sort_values(ascending=False)
    .reset_index()
)
rank_list = totals["institution"].tolist()
unt_rank  = rank_list.index(MY_INSTITUTION) + 1 if MY_INSTITUTION in rank_list else None
n_ranked  = len(rank_list)

# Programs where peers are ahead
if peer_cols:
    peer_avg_funding = pivot_m[peer_cols].mean(axis=1)
    dollar_gap       = peer_avg_funding - pivot_m[MY_INSTITUTION]
    n_gaps           = int((dollar_gap > 0).sum())
else:
    n_gaps = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("UNT Awards",        f"{unt_total_awards:,}")
c2.metric("UNT Funding",       f"${unt_total_funding:.1f}M")
c3.metric("Rank Among Peers",  f"#{unt_rank} of {n_ranked}" if unt_rank else "—")
c4.metric("Programs with Gaps", str(n_gaps))

st.divider()

# ---------------------------------------------------------------------------
# Headline — one sentence, most important gap
# ---------------------------------------------------------------------------

if peer_cols:
    peer_avg_awards  = pivot_n[peer_cols].mean(axis=1)
    dollar_gap       = peer_avg_funding - pivot_m[MY_INSTITUTION]
    gap_programs     = dollar_gap[dollar_gap > 0].sort_values(ascending=False)

    if not gap_programs.empty:
        top_prog       = gap_programs.index[0]
        top_prog_label = abbr_to_name.get(top_prog, top_prog)
        unt_awards_top = int(pivot_n.loc[top_prog, MY_INSTITUTION])
        peer_avg_top   = round(float(peer_avg_awards.loc[top_prog]), 1)
        gap_m_top      = round(float(dollar_gap[top_prog]), 2)

        # Find the single peer with most awards in top program
        top_peer_awards = pivot_n.loc[top_prog, peer_cols].sort_values(ascending=False)
        top_peer_name   = PEER_SHORT.get(top_peer_awards.index[0], top_peer_awards.index[0])
        top_peer_count  = int(top_peer_awards.iloc[0])

        st.markdown(
            f"**Biggest gap: {top_prog_label}** — "
            f"In this program, UNT has **{unt_awards_top} awards**, "
            f"peers average **{peer_avg_top:.0f}** "
            f"({top_peer_name} leads with **{top_peer_count}**). "
            f"Closing this gap = **${gap_m_top:.1f}M** in funding."
        )

st.divider()

# ---------------------------------------------------------------------------
# Gap table
# ---------------------------------------------------------------------------

if not peer_cols:
    st.warning("No peer data found for the selected filters.")
    st.stop()

# All peers sorted by total awards — show everyone in the selected peer set
top_peer_cols = (
    pivot_n[peer_cols].sum()
    .sort_values(ascending=False)
    .index.tolist()
)

# Build display DataFrame
# Build field-wide lookup: program_abbr -> (field_awards, last_funded)
field_lookup = {}
if not df_field.empty:
    for _, r in df_field.iterrows():
        field_lookup[r["program_abbr"]] = (
            int(r["field_awards"]),
            int(r["last_funded"]),
            int(r.get("awards_current", 0)),
            int(r.get("awards_prev", 0)),
            int(r.get("awards_two_ago", 0)),
        )

rows = []
for prog in pivot_n.index:
    full_name = abbr_to_name.get(prog, prog)
    if len(full_name) > 45:
        full_name = full_name[:42] + "..."
    unt_val  = int(pivot_n.loc[prog, MY_INSTITUTION])
    peer_avg = float(pivot_n.loc[prog, peer_cols].mean())
    gap_m    = round(float(pivot_m.loc[prog, peer_cols].mean()) - float(pivot_m.loc[prog, MY_INSTITUTION]), 2)
    field_awards, last_funded, cur, prev, two_ago = field_lookup.get(prog, (0, 0, 0, 0, 0))

    # Trend: compare prev year vs two years ago (prev is more complete than partial current year)
    if prev == 0 and two_ago == 0:
        trend = "—"
    elif two_ago == 0:
        trend = "↑"
    elif prev == 0:
        trend = "↓"
    elif prev / two_ago >= 1.2:
        trend = "↑"
    elif prev / two_ago <= 0.8:
        trend = "↓"
    else:
        trend = "→"

    row = {"Program": full_name, "UNT": unt_val}
    for col in top_peer_cols:
        short      = PEER_SHORT.get(col, col[:8])
        row[short] = int(pivot_n.loc[prog, col])
    row["Peer Avg"]         = round(peer_avg, 1)
    row["Opportunity ($M)"] = gap_m
    row["Total Awards"]     = field_awards
    row["Last Funded"]      = last_funded if last_funded else "—"
    row["Trend"]            = trend
    row[f"FY{fy_end}"]      = "✓" if cur > 0 else ""
    rows.append(row)

display = (
    pd.DataFrame(rows)
    .set_index("Program")
    .sort_values("Opportunity ($M)", ascending=False)
)

n_gaps       = int((display["Opportunity ($M)"] > 0).sum())
n_competitive = int((display["Opportunity ($M)"] <= 0).sum())

st.subheader("Program Breakdown")
st.caption(
    f"All programs sorted by opportunity size. "
    f"**Opportunity ($M)** = how much more UNT would receive if it matched the peer average "
    f"(negative = UNT is already at or above peer average). "
    f"**Trend** = field-wide award count direction (↑ growing · → flat · ↓ declining) comparing "
    f"FY{fy_end - 1} vs FY{fy_end - 2}. "
    f"**FY{fy_end}** = ✓ if any institution received an award in this program in the current fiscal year. "
    f"**Total Awards** = all awards made nationally in this program (not just peers) within the selected FY range. "
    f"UNT column: 🔴 trailing badly · 🟠 within reach · 🟢 competitive or leading."
)

if display.empty:
    st.info("No program data found for this filter combination.")
    st.stop()


def _color_trend(col):
    """Color the Trend column: green ↑, red ↓, gray → or —."""
    if col.name != "Trend":
        return [""] * len(col)
    styles = []
    for v in col:
        if v == "↑":
            styles.append("color: #27ae60; font-weight: bold")
        elif v == "↓":
            styles.append("color: #e74c3c; font-weight: bold")
        else:
            styles.append("color: #95a5a6")
    return styles


def _color_unt(col):
    """Color UNT column by ratio to peer avg."""
    if col.name != "UNT":
        return [""] * len(col)
    peer_avg = display["Peer Avg"]
    opp      = display["Opportunity ($M)"]
    styles = []
    for unt_val, avg_val, opp_val in zip(col, peer_avg, opp):
        if opp_val <= 0:
            # UNT at or above peer average
            styles.append("background-color: #27ae60; color: white")
        elif avg_val == 0:
            styles.append("")
        elif unt_val == 0:
            styles.append("background-color: #c0392b; color: white")
        elif unt_val / avg_val < 0.40:
            styles.append("background-color: #e74c3c; color: white")
        elif unt_val / avg_val < 0.75:
            styles.append("background-color: #e67e22; color: white")
        else:
            styles.append("background-color: #27ae60; color: white")
    return styles


styled = display.style.apply(_color_unt).apply(_color_trend).format({
    "Peer Avg":         "{:.1f}",
    "Opportunity ($M)": "${:.2f}M",
    "Total Awards":     "{:,}",
})

st.dataframe(styled, use_container_width=True, height=min(650, 55 + 38 * len(display)))

# ---------------------------------------------------------------------------
# Peer funding comparison bar chart
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Total Funding by Institution")
st.caption("Total dollars awarded across all programs in the current scope. UNT shown in red.")

bar_data = (
    totals.rename(columns={"institution": "Institution", "funding_m": "Funding ($M)"})
    .assign(
        Label=lambda d: d["Institution"].map(lambda x: PEER_SHORT.get(x, x)),
        IsUNT=lambda d: d["Institution"] == MY_INSTITUTION,
    )
    .sort_values("Funding ($M)", ascending=True)
)

colors = ["#e74c3c" if is_unt else "#2980b9" for is_unt in bar_data["IsUNT"]]

fig = px.bar(
    bar_data,
    x="Funding ($M)",
    y="Label",
    orientation="h",
    labels={"Label": "", "Funding ($M)": "Total Funding ($M)"},
    color="IsUNT",
    color_discrete_map={True: "#e74c3c", False: "#2980b9"},
)
fig.update_layout(
    showlegend=False,
    margin=dict(t=10, b=10, l=0, r=20),
    height=max(300, 30 * len(bar_data)),
    yaxis={"categoryorder": "total ascending"},
)
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Program activity heatmap
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Program Activity Over Time")
st.caption(
    "Field-wide award activity by program and fiscal year (all universities nationally). "
    "Numbers in cells = UNT's award count. Blank = UNT had no awards that year."
)

df_heatmap = get_heatmap_data(
    my_ueis, agency, fy_start, fy_end,
    dir_filter, subdiv_filter, institute_filter,
)

if df_heatmap.empty:
    st.info("Heatmap not available for this agency.")
else:
    hm_metric = st.radio("Color by", ["Award Count", "Funding ($M)"], horizontal=True)

    # Clean program names (reuse _clean_name defined above)
    df_heatmap["label"] = df_heatmap["program"].map(_clean_name)

    # Deduplicate label per abbr (take most common from data)
    abbr_label = (
        df_heatmap[["program_abbr", "label"]]
        .drop_duplicates("program_abbr")
        .set_index("program_abbr")["label"]
        .to_dict()
    )

    # Pivot to 2D matrices
    value_col = "field_awards" if hm_metric == "Award Count" else "field_funding_m"
    hm_z   = df_heatmap.pivot_table(index="program_abbr", columns="fiscal_year", values=value_col,   aggfunc="sum", fill_value=0)
    hm_unt = df_heatmap.pivot_table(index="program_abbr", columns="fiscal_year", values="unt_awards", aggfunc="sum", fill_value=0)

    # Sort rows by total field activity ascending so highest appears at top in Plotly
    row_order = hm_z.sum(axis=1).sort_values(ascending=True).index
    hm_z   = hm_z.loc[row_order]
    hm_unt = hm_unt.loc[row_order]

    y_labels = [abbr_label.get(p, p) for p in row_order]
    x_labels = [str(int(y)) for y in hm_z.columns]

    # Text annotations: UNT count if > 0, blank otherwise
    text_vals = [
        [str(int(hm_unt.iloc[r, c])) if hm_unt.iloc[r, c] > 0 else ""
         for c in range(hm_unt.shape[1])]
        for r in range(hm_unt.shape[0])
    ]

    colorbar_title = "Awards" if hm_metric == "Award Count" else "$M"

    fig_hm = go.Figure(go.Heatmap(
        z=hm_z.values,
        x=x_labels,
        y=y_labels,
        text=text_vals,
        texttemplate="%{text}",
        textfont={"size": 11},
        colorscale="Blues",
        colorbar=dict(title=colorbar_title, thickness=14),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "FY%{x}<br>"
            f"{colorbar_title}: %{{z}}<br>"
            "UNT: %{text}<extra></extra>"
        ),
    ))
    fig_hm.update_layout(
        margin=dict(t=30, b=10, l=0, r=0),
        height=max(400, 26 * len(y_labels)),
        xaxis=dict(side="top", title=""),
        yaxis=dict(title=""),
    )
    st.plotly_chart(fig_hm, use_container_width=True)

# ---------------------------------------------------------------------------
# Sankey: Programs → Institutions
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Funding Flow: Programs to Institutions")
st.caption(
    "How awards flow from programs to UNT and peers in the selected scope. "
    "Band width is proportional to the selected metric. "
    "UNT in red · peers in blue."
)

if df_raw.empty or not peer_cols:
    st.info("No data available for Sankey in this filter combination.")
else:
    sk_metric = st.radio(
        "Flow size", ["Award Count", "Funding ($M)"], horizontal=True, key="sk_metric"
    )
    val_col = "awards" if sk_metric == "Award Count" else "funding_m"

    # Programs sorted by total peer+UNT activity descending
    prog_totals = df_raw.groupby("program_abbr")[val_col].sum()
    programs_sk = prog_totals.sort_values(ascending=False).index.tolist()
    n_prog = len(programs_sk)

    inst_nodes  = [MY_INSTITUTION] + peer_cols
    prog_labels = [_clean_name(abbr_to_name.get(p, p))[:40] for p in programs_sk]
    inst_labels = [
        "UNT" if i == MY_INSTITUTION else PEER_SHORT.get(i, i)
        for i in inst_nodes
    ]
    all_labels  = prog_labels + inst_labels

    prog_colors = ["rgba(142, 68, 173, 0.75)"] * n_prog
    inst_colors = [
        "#e74c3c" if i == MY_INSTITUTION else "#2980b9"
        for i in inst_nodes
    ]
    node_colors = prog_colors + inst_colors

    sources, targets, values, link_colors = [], [], [], []

    for pi, prog in enumerate(programs_sk):
        prog_rows = df_raw[df_raw["program_abbr"] == prog]

        for ii, inst in enumerate(inst_nodes):
            row = prog_rows[prog_rows["institution"] == inst]
            val = float(row[val_col].sum()) if not row.empty else 0.0
            if val > 0:
                sources.append(pi)
                targets.append(n_prog + ii)
                values.append(val)
                link_colors.append(
                    "rgba(231, 76, 60, 0.35)" if inst == MY_INSTITUTION
                    else "rgba(41, 128, 185, 0.25)"
                )

    fig_sk = go.Figure(go.Sankey(
        node=dict(
            pad=14,
            thickness=20,
            label=all_labels,
            color=node_colors,
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values,
            color=link_colors,
        ),
    ))
    fig_sk.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        height=max(500, 28 * n_prog + 200),
        font=dict(size=12),
    )
    st.plotly_chart(fig_sk, use_container_width=True)
