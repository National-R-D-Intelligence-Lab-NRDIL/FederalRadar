"""
Home.py — Federal Radar
Single-page competitive gap analysis for VPR/AVP.

Primary question: In [agency/program], where are peers beating us,
and by how much? Sorted by funding opportunity.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from pdf_export import generate_gap_report


def _short_label(name: str) -> str:
    """Derive a compact display label from a full institution name."""
    s = name
    for prefix in ("The University of ", "University of ", "University at ", "College of "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    for suffix in (" University", " College", " Institute of Technology", " State University"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s[:20] + ("…" if len(s) > 20 else "")


def _to_png(fig, width: int = 1000, height: int = 700) -> bytes | None:
    """Export a Plotly figure to PNG bytes via kaleido. Returns None on failure.
    Clones the figure and widens margins so labels are not clipped in the
    fixed-width kaleido render (automargin doesn't work reliably there)."""
    import copy
    try:
        fig_copy = copy.deepcopy(fig)
        cur_margin = fig_copy.layout.margin or {}
        cur_l = getattr(cur_margin, "l", None) or 10
        cur_b = getattr(cur_margin, "b", None) or 10
        fig_copy.update_layout(margin=dict(l=max(cur_l, 180), b=max(cur_b, 60)))
        return pio.to_image(fig_copy, format="png", width=width, height=height, scale=1)
    except Exception:
        return None
from queries import (
    ED_EXCLUSION_NOTE,
    ED_NON_RESEARCH_CFDAS,
    NSF_DIR_NAMES,
    NSF_DIV_NAMES,
    PEER_SHORT,
    get_agencies,
    get_field_wide_stats,
    get_fy_bounds,
    get_heatmap_data,
    get_herd_institutions,
    get_herd_states,
    get_scoped_pis,
    get_my_ueis,
    get_nih_institutes,
    get_nsf_directorates,
    get_nsf_subdiv,
    get_peer_institutions,
    get_pis_for_program,
    get_raw_comparison,
    get_raw_comparison_by_fy,
    get_validation_stats,
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
    st.divider()

    # ------------------------------------------------------------------
    # Institution picker
    # ------------------------------------------------------------------
    _states = ["(All)"] + get_herd_states()
    _state_pick = st.selectbox("State", _states, key="picker_state")
    _state_val = _state_pick if _state_pick != "(All)" else None

    _inst_df = get_herd_institutions(state=_state_val)
    _opt_labels = [f"{row.ipeds_name} ({row.state})" for row in _inst_df.itertuples()]
    _opt_ueis   = _inst_df["awards_uei"].tolist()
    _opt_names  = _inst_df["awards_name"].tolist()
    _opt_ipeds  = _inst_df["ipeds_name"].tolist()

    _my_default_ueis = get_my_ueis()
    _default_idx = next(
        (i for i, u in enumerate(_opt_ueis) if u in _my_default_ueis), 0
    )
    _inst_idx = st.selectbox(
        "Institution",
        range(len(_opt_labels)),
        format_func=lambda i: _opt_labels[i],
        index=_default_idx,
        key="picker_inst",
    )
    selected_uei  = _opt_ueis[_inst_idx]
    my_inst_name  = _opt_names[_inst_idx] or _opt_ipeds[_inst_idx]
    my_ipeds_name = _opt_ipeds[_inst_idx]
    my_col_label  = _short_label(my_ipeds_name)

    st.divider()

    all_agencies = get_agencies()
    agency = st.selectbox(
        "Agency",
        all_agencies,
        format_func=str.upper,
    )

    dir_filter = subdiv_filter = institute_filter = None
    cfda_filter = None
    ed_exclude_cfdas: tuple[str, ...] = ()

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

    else:
        if agency == "ed":
            ed_exclude_cfdas = ED_NON_RESEARCH_CFDAS
            st.caption(f"ℹ️ {ED_EXCLUSION_NOTE}")

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
    _agencies_str = ", ".join(a.upper() for a in all_agencies)
    st.caption(f"Data: {_agencies_str} · FY{fy_min}-{fy_max}")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

_all_my_ueis = tuple(get_my_ueis())
my_ueis      = _all_my_ueis if selected_uei in _all_my_ueis else (selected_uei,)
peer_items = get_peer_institutions(peer_set)
peer_ueis  = tuple(uei for _, uei in peer_items)

df_raw = get_raw_comparison(
    my_ueis, peer_ueis, agency, fy_start, fy_end,
    dir_filter, subdiv_filter, institute_filter,
    cfda_filter, ed_exclude_cfdas,
)
df_field = get_field_wide_stats(
    agency, fy_start, fy_end,
    dir_filter, subdiv_filter, institute_filter,
    cfda_filter, ed_exclude_cfdas,
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
if cfda_filter:
    scope_parts.append(cfda_filter)
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

# Ensure my institution column exists
if my_inst_name not in pivot_n.columns:
    pivot_n[my_inst_name] = 0
    pivot_m[my_inst_name] = 0.0

peer_cols = [c for c in pivot_n.columns if c != my_inst_name]

# ---------------------------------------------------------------------------
# Scorecard row
# ---------------------------------------------------------------------------

unt_df   = df_raw[df_raw["institution"] == my_inst_name]
peers_df = df_raw[df_raw["institution"] != my_inst_name]

unt_total_awards  = int(unt_df["awards"].sum())
unt_total_funding = round(unt_df["funding_m"].sum(), 1)

# Rank my institution vs all peers by total funding in scope
totals = (
    df_raw.groupby("institution")["funding_m"]
    .sum()
    .sort_values(ascending=False)
    .reset_index()
)
rank_list = totals["institution"].tolist()
unt_rank  = rank_list.index(my_inst_name) + 1 if my_inst_name in rank_list else None
n_ranked  = len(rank_list)

# Programs where peers are ahead
if peer_cols:
    peer_avg_funding = pivot_m[peer_cols].mean(axis=1)
    dollar_gap       = peer_avg_funding - pivot_m[my_inst_name]
    n_gaps           = int((dollar_gap > 0).sum())
else:
    n_gaps = 0

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{my_col_label} Awards",  f"{unt_total_awards:,}")
c2.metric(f"{my_col_label} Funding", f"${unt_total_funding:.1f}M")
c3.metric("Rank Among Peers",        f"#{unt_rank} of {n_ranked}" if unt_rank else "—")
c4.metric("Programs with Gaps",      str(n_gaps))

st.divider()

# ---------------------------------------------------------------------------
# Headline — one sentence, most important gap
# ---------------------------------------------------------------------------

_headline = ""
if peer_cols:
    peer_avg_awards  = pivot_n[peer_cols].mean(axis=1)
    dollar_gap       = peer_avg_funding - pivot_m[my_inst_name]
    gap_programs     = dollar_gap[dollar_gap > 0].sort_values(ascending=False)

    if not gap_programs.empty:
        top_prog       = gap_programs.index[0]
        top_prog_label = abbr_to_name.get(top_prog, top_prog)
        unt_awards_top = int(pivot_n.loc[top_prog, my_inst_name])
        peer_avg_top   = round(float(peer_avg_awards.loc[top_prog]), 1)
        gap_m_top      = round(float(dollar_gap[top_prog]), 2)

        # Find the single peer with most awards in top program
        top_peer_awards = pivot_n.loc[top_prog, peer_cols].sort_values(ascending=False)
        top_peer_name   = PEER_SHORT.get(top_peer_awards.index[0], top_peer_awards.index[0])
        top_peer_count  = int(top_peer_awards.iloc[0])

        _headline = (
            f"**Biggest gap: {top_prog_label}** — "
            f"In this program, {my_col_label} has **{unt_awards_top} awards**, "
            f"peers average **{peer_avg_top:.0f}** "
            f"({top_peer_name} leads with **{top_peer_count}**). "
            f"If {my_col_label} matched the peer average, it would represent "
            f"an additional **${gap_m_top:.1f}M** in funding."
        )
        st.markdown(_headline)
    else:
        _headline = ""

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
    unt_val  = int(pivot_n.loc[prog, my_inst_name])
    peer_avg = float(pivot_n.loc[prog, peer_cols].mean())
    gap_m    = round(float(pivot_m.loc[prog, peer_cols].mean()) - float(pivot_m.loc[prog, my_inst_name]), 2)
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

    row = {"Program": full_name, my_col_label: unt_val}
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
    f"{my_col_label} column: 🔴 trailing badly · 🟠 within reach · 🟢 competitive or leading."
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
    """Color my-institution column by ratio to peer avg."""
    if col.name != my_col_label:
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

# CSV export for gap table
_gap_csv = display.to_csv()
st.download_button(
    "Download gap table (CSV)",
    _gap_csv,
    file_name=f"federal_radar_gap_{agency}_{fy_start}-{fy_end}.csv",
    mime="text/csv",
)

# PDF export button is at the bottom of the page after all charts are rendered

# ---------------------------------------------------------------------------
# PI Drill-Down
# ---------------------------------------------------------------------------

if agency in ("nsf", "nih"):
    # Determine which DB column to use for program filtering
    if agency == "nsf":
        if subdiv_filter:
            _prog_col = "pgm_ele_name"
        elif dir_filter:
            _prog_col = "div_abbr"
        else:
            _prog_col = "dir_abbr"
    else:
        _prog_col = "activity_code" if institute_filter else "nih_institute"

    st.subheader("PI Drill-Down")
    with st.expander("Select a program and institution to see PIs", expanded=True):
        # First pick institution, then show only programs where that institution has awards
        _all_insts = [my_inst_name] + [c for c in pivot_n.columns if c != my_inst_name]
        _pi_inst_labels = {i: PEER_SHORT.get(i, i) for i in _all_insts}
        _pi_inst_choice = st.selectbox(
            "Institution", _all_insts,
            format_func=lambda x: _pi_inst_labels.get(x, x),
            key="pi_inst",
        )

        # Only show programs where the selected institution has > 0 awards
        _programs_for_pi = [p for p in pivot_n.index if pivot_n.loc[p, _pi_inst_choice] > 0]
        if not _programs_for_pi:
            st.info(f"No programs with awards for {_pi_inst_labels.get(_pi_inst_choice, _pi_inst_choice)}.")
            _pi_prog_abbr = None
        else:
            _display_progs = [abbr_to_name.get(p, p) for p in _programs_for_pi]
            _pi_prog_choice = st.selectbox("Program", _display_progs, key="pi_prog")
            _pi_prog_idx = _display_progs.index(_pi_prog_choice) if _pi_prog_choice in _display_progs else 0
            _pi_prog_abbr = _programs_for_pi[_pi_prog_idx]

            _pi_df = get_pis_for_program(
                _pi_inst_choice, agency, _prog_col, _pi_prog_abbr, fy_start, fy_end
            )
            if _pi_df.empty:
                st.info("No PI data found for this combination.")
            else:
                def _fmt_funding(v):
                    if v >= 1e6:
                        return f"${v / 1e6:.2f}M"
                    if v >= 1e3:
                        return f"${v / 1e3:.2f}K"
                    return f"${v:,.0f}"

                _pi_df["Total Funding"] = _pi_df["Total Funding"].map(_fmt_funding)
                st.dataframe(
                    _pi_df,
                    use_container_width=True,
                    column_config={
                        "First FY": st.column_config.NumberColumn(format="%d"),
                        "Last FY": st.column_config.NumberColumn(format="%d"),
                    },
                )

# ---------------------------------------------------------------------------
# Peer funding comparison bar chart
# ---------------------------------------------------------------------------

# Chart capture variables — populated below, used for PDF export at page bottom
_pdf_fig_bar: object = None
_pdf_fig_hm:  object = None
_pdf_fig_sk:  object = None
_pdf_hm_h:    int    = 700
_pdf_sk_h:    int    = 700

st.divider()
st.subheader("Total Funding by Institution")
st.caption(f"Total dollars awarded across all programs in the current scope. {my_col_label} shown in red.")

bar_data = (
    totals.rename(columns={"institution": "Institution", "funding_m": "Funding ($M)"})
    .assign(
        Label=lambda d: d["Institution"].map(lambda x: PEER_SHORT.get(x, my_col_label if x == my_inst_name else x)),
        IsUNT=lambda d: d["Institution"] == my_inst_name,
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
fig.update_traces(
    text=bar_data["Funding ($M)"].map(lambda x: f"${x:.1f}M"),
    textposition="outside",
    textfont=dict(size=9),
    cliponaxis=False,
)
_bar_label_w = max((len(str(lbl)) for lbl in bar_data["Label"]), default=10) * 7
_bar_max = bar_data["Funding ($M)"].max() if not bar_data.empty else 1
fig.update_layout(
    showlegend=False,
    margin=dict(t=10, b=10, l=_bar_label_w, r=80),
    height=max(300, 30 * len(bar_data)),
    yaxis={"categoryorder": "total ascending", "automargin": True},
    xaxis=dict(range=[0, _bar_max * 1.18]),
)
st.plotly_chart(fig, use_container_width=True)
_pdf_fig_bar = fig

# CSV export for funding comparison
_fund_csv = bar_data[["Institution", "Funding ($M)"]].to_csv(index=False)
st.download_button(
    "Download funding comparison (CSV)",
    _fund_csv,
    file_name=f"federal_radar_funding_{agency}_{fy_start}-{fy_end}.csv",
    mime="text/csv",
)

# ---------------------------------------------------------------------------
# Program activity heatmap
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Program Activity Over Time")
st.caption(
    "Field-wide award activity by program and fiscal year (all universities nationally). "
    f"Numbers in cells = {my_col_label}'s award count. Blank = {my_col_label} had no awards that year."
)

df_heatmap = get_heatmap_data(
    my_ueis, agency, fy_start, fy_end,
    dir_filter, subdiv_filter, institute_filter,
    cfda_filter, ed_exclude_cfdas,
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

    # Build UNT funding pivot for hover
    hm_unt_funding = None
    if "unt_funding_m" in df_heatmap.columns:
        hm_unt_funding = df_heatmap.pivot_table(
            index="program_abbr", columns="fiscal_year",
            values="unt_funding_m", aggfunc="sum", fill_value=0,
        ).reindex(index=row_order, columns=hm_z.columns, fill_value=0)

    # Build customdata for hover: [raw_z, unt_funding_m]
    z_raw = hm_z.values
    if hm_unt_funding is not None:
        customdata = np.stack([z_raw, hm_unt_funding.values], axis=-1)
    else:
        customdata = np.stack([z_raw, np.zeros_like(z_raw)], axis=-1)

    if hm_metric == "Funding ($M)":
        hover_tpl = (
            "<b>%{y}</b><br>"
            "FY%{x}<br>"
            "Field: $%{customdata[0]:.1f}M<br>"
            "UNT: $%{customdata[1]:.1f}M (awards: %{text})<extra></extra>"
        )
    else:
        hover_tpl = (
            "<b>%{y}</b><br>"
            "FY%{x}<br>"
            "Field Awards: %{customdata[0]:,.0f}<br>"
            "UNT Awards: %{text}<extra></extra>"
        )

    fig_hm = go.Figure(go.Heatmap(
        z=hm_z.values,
        x=x_labels,
        y=y_labels,
        text=text_vals,
        texttemplate="%{text}",
        textfont={"size": 11},
        colorscale="Blues",
        colorbar=dict(title=colorbar_title, thickness=14),
        customdata=customdata,
        hovertemplate=hover_tpl,
    ))
    _hm_label_w = max((len(lbl) for lbl in y_labels), default=10) * 7
    fig_hm.update_layout(
        margin=dict(t=30, b=10, l=_hm_label_w, r=10),
        height=max(400, 26 * len(y_labels)),
        xaxis=dict(side="top", title="", type="category"),
        yaxis=dict(title="", automargin=True),
    )
    st.plotly_chart(fig_hm, use_container_width=True)
    _pdf_fig_hm = fig_hm
    _pdf_hm_h   = max(600, 32 * len(y_labels))

# ---------------------------------------------------------------------------
# Sankey: Programs → Fiscal Year → Institutions
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Funding Flow: Programs → Fiscal Year → Institutions")
st.caption(
    "How awards flow from programs through fiscal years to UNT and peers. "
    "Band width is proportional to the selected metric. "
    "UNT in red · peers in blue · fiscal years in green."
)

if df_raw.empty or not peer_cols:
    st.info("No data available for Sankey in this filter combination.")
else:
    sk_metric = st.radio(
        "Flow size", ["Award Count", "Funding ($M)"], horizontal=True, key="sk_metric"
    )
    val_col = "awards" if sk_metric == "Award Count" else "funding_m"

    # Fetch FY-level data for the Sankey
    df_sk = get_raw_comparison_by_fy(
        my_ueis, peer_ueis, agency, fy_start, fy_end,
        dir_filter, subdiv_filter, institute_filter,
        cfda_filter, ed_exclude_cfdas,
    )

    if df_sk.empty:
        st.info("No data available for Sankey in this filter combination.")
    else:
        def _fmt_dollars(m: float) -> str:
            """Auto-format a value in millions: $1.2B, $435M, $12M, $0.4M."""
            if m >= 1000:
                b = m / 1000
                return f"${b:,.1f}B" if b != int(b) else f"${int(b):,}B"
            if m >= 10:
                return f"${m:,.0f}M"
            if m >= 1:
                return f"${m:.1f}M" if m != int(m) else f"${int(m)}M"
            if m > 0:
                return f"${m:.1f}M"
            return "$0M"

        # Programs sorted by total activity descending
        prog_totals = df_sk.groupby("program_abbr")[val_col].sum()
        programs_sk = prog_totals.sort_values(ascending=False).index.tolist()
        n_prog = len(programs_sk)

        # FY nodes — only years with actual data, sorted
        fy_list = sorted(df_sk["fiscal_year"].unique().tolist())
        n_fy = len(fy_list)

        inst_nodes = [my_inst_name] + peer_cols
        n_inst = len(inst_nodes)

        # Compute node totals for labels
        _prog_funding = df_sk.groupby("program_abbr")["funding_m"].sum()
        _prog_awards = df_sk.groupby("program_abbr")["awards"].sum()
        _fy_funding = df_sk.groupby("fiscal_year")["funding_m"].sum()
        _fy_awards = df_sk.groupby("fiscal_year")["awards"].sum()
        _inst_funding = df_sk.groupby("institution")["funding_m"].sum()
        _inst_awards = df_sk.groupby("institution")["awards"].sum()

        # Node layout: [programs (0..n_prog-1)] [FYs (n_prog..n_prog+n_fy-1)] [insts (n_prog+n_fy..)]
        _prog_names = [_clean_name(abbr_to_name.get(p, p))[:35] for p in programs_sk]
        _fy_names = [f"FY{fy}" for fy in fy_list]
        _inst_names = [
            my_col_label if i == my_inst_name else PEER_SHORT.get(i, i)
            for i in inst_nodes
        ]

        if sk_metric == "Funding ($M)":
            prog_labels = [f"{n} ({_fmt_dollars(float(_prog_funding.get(p, 0)))})" for n, p in zip(_prog_names, programs_sk)]
            fy_labels = [f"{n} ({_fmt_dollars(float(_fy_funding.get(fy, 0)))})" for n, fy in zip(_fy_names, fy_list)]
            inst_labels = [f"{n} ({_fmt_dollars(float(_inst_funding.get(i, 0)))})" for n, i in zip(_inst_names, inst_nodes)]
        else:
            prog_labels = [f"{n} ({int(_prog_awards.get(p, 0)):,})" for n, p in zip(_prog_names, programs_sk)]
            fy_labels = [f"{n} ({int(_fy_awards.get(fy, 0)):,})" for n, fy in zip(_fy_names, fy_list)]
            inst_labels = [f"{n} ({int(_inst_awards.get(i, 0)):,})" for n, i in zip(_inst_names, inst_nodes)]

        all_labels = prog_labels + fy_labels + inst_labels

        prog_colors = ["rgba(142, 68, 173, 0.75)"] * n_prog
        fy_colors = ["rgba(39, 174, 96, 0.8)"] * n_fy
        inst_colors = [
            "#e74c3c" if i == my_inst_name else "#2980b9"
            for i in inst_nodes
        ]
        node_colors = prog_colors + fy_colors + inst_colors

        sources, targets, values, link_colors = [], [], [], []

        # Build index lookups
        fy_idx = {fy: n_prog + i for i, fy in enumerate(fy_list)}
        inst_idx = {inst: n_prog + n_fy + i for i, inst in enumerate(inst_nodes)}

        # Aggregate: Program → FY links
        prog_fy = df_sk.groupby(["program_abbr", "fiscal_year"])[val_col].sum().reset_index()
        for _, row in prog_fy.iterrows():
            prog = row["program_abbr"]
            if prog not in programs_sk:
                continue
            val = float(row[val_col])
            if val > 0:
                sources.append(programs_sk.index(prog))
                targets.append(fy_idx[row["fiscal_year"]])
                values.append(val)
                link_colors.append("rgba(142, 68, 173, 0.3)")

        # Aggregate: FY → Institution links
        fy_inst = df_sk.groupby(["fiscal_year", "institution"])[val_col].sum().reset_index()
        for _, row in fy_inst.iterrows():
            inst = row["institution"]
            if inst not in inst_idx:
                continue
            val = float(row[val_col])
            if val > 0:
                sources.append(fy_idx[row["fiscal_year"]])
                targets.append(inst_idx[inst])
                values.append(val)
                link_colors.append(
                    "rgba(231, 76, 60, 0.35)" if inst == my_inst_name
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
        _pdf_fig_sk = fig_sk
        _pdf_sk_h   = max(600, 28 * n_prog + 200)

# ---------------------------------------------------------------------------
# PDF export — lazy generation (only renders charts on click)
# ---------------------------------------------------------------------------

st.divider()

_pdf_fname = (
    f"federal_radar_{scope_label.replace(' / ', '_').replace(' ', '_')}"
    f"_{fy_start}-{fy_end}.pdf"
)

_include_charts = st.checkbox("Include charts in PDF", value=False,
                               help="Adds bar chart, heatmap, and Sankey. Takes ~10 sec extra.")


def _build_pdf(with_charts: bool = False) -> bytes:
    """Build the PDF report. Called only on button click."""
    _pi_df = None
    if agency in ("nsf", "nih"):
        _pi_df = get_scoped_pis(
            my_inst_name, agency, fy_start, fy_end,
            dir_filter, subdiv_filter, institute_filter,
        )
        if _pi_df is not None and not _pi_df.empty:
            _pi_df = _pi_df.copy()

            def _pi_scope(row, _agency):
                parts = [_agency.upper()]
                for col in ["nih_institute", "dir_abbr", "div_abbr", "pgm_ele_name", "activity_code"]:
                    if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
                        parts.append(str(row[col]).strip())
                return " / ".join(parts)

            _pi_df.insert(1, "Scope", _pi_df.apply(lambda r: _pi_scope(r, agency), axis=1))
            _pi_df.drop(
                columns=["nih_institute", "dir_abbr", "div_abbr", "pgm_ele_name", "activity_code"],
                errors="ignore", inplace=True,
            )

    _charts: list[tuple[str, bytes]] | None = None
    if with_charts:
        _charts = []
        if _pdf_fig_bar is not None:
            _png = _to_png(_pdf_fig_bar, height=min(900, max(400, 28 * len(bar_data))))
            if _png:
                _charts.append(("Total Funding by Institution", _png))
        if _pdf_fig_hm is not None:
            _png = _to_png(_pdf_fig_hm, height=min(900, _pdf_hm_h))
            if _png:
                _charts.append(("Program Activity Heatmap", _png))
        if _pdf_fig_sk is not None:
            _png = _to_png(_pdf_fig_sk, height=min(900, _pdf_sk_h))
            if _png:
                _charts.append(("Funding Flow: Programs to Institutions", _png))

    _df_fy = get_raw_comparison_by_fy(
        my_ueis, peer_ueis, agency, fy_start, fy_end,
        dir_filter, subdiv_filter, institute_filter,
        cfda_filter, ed_exclude_cfdas,
    )
    fy_peer = (
        _df_fy.groupby(["institution", "fiscal_year"])["funding_m"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    ) if not _df_fy.empty else None

    return generate_gap_report(
        scope_label     = scope_label,
        fy_start        = fy_start,
        fy_end          = fy_end,
        peer_set        = peer_set,
        unt_awards      = unt_total_awards,
        unt_funding     = unt_total_funding,
        unt_rank        = unt_rank,
        n_ranked        = n_ranked,
        n_gaps          = n_gaps,
        headline        = _headline,
        gap_df          = display,
        peer_funding    = totals,
        fy_peer_funding = fy_peer,
        pi_df           = _pi_df,
        charts          = _charts or None,
    )


if st.button("Export PDF Report", type="primary"):
    _label = "Rendering charts and building PDF..." if _include_charts else "Building PDF..."
    with st.spinner(_label):
        st.session_state["_pdf_bytes"] = _build_pdf(with_charts=_include_charts)

if st.session_state.get("_pdf_bytes"):
    st.download_button(
        "Download PDF",
        st.session_state["_pdf_bytes"],
        file_name=_pdf_fname,
        mime="application/pdf",
    )

# ---------------------------------------------------------------------------
# Validation footer
# ---------------------------------------------------------------------------

st.divider()
_vstats = get_validation_stats(agency, fy_start, fy_end)
_warnings = []
if _vstats["negative_excluded"] and _vstats["negative_excluded"] > 0:
    _warnings.append(f"{_vstats['negative_excluded']:,} negative-amount records excluded from gap analysis")
if _vstats["zero_count"] and _vstats["zero_count"] > 0:
    _warnings.append(f"{_vstats['zero_count']:,} zero-amount records in dataset")

_last_checked = (_vstats["last_checked"] or "")[:10]
_last_record = (_vstats["last_new_record"] or "")[:10]
_freshness = (
    f"Last checked: {_last_checked or 'unknown'} · "
    f"Last new record: {_last_record or 'unknown'}"
)
st.caption(
    f"**Data Quality** · {_vstats['total_records']:,} records · "
    f"${_vstats['total_funding_m']:,.1f}M total funding · "
    f"{_freshness}"
    + (f" · Warnings: {'; '.join(_warnings)}" if _warnings else "")
)
