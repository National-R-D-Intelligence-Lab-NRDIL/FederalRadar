"""
Action Dashboard — Federal Radar
Where's the money and where do we submit?

Cross-agency, forward-looking view fixed to FY2025-2026.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from queries import (
    MY_INSTITUTION,
    PEER_SHORT,
    get_my_ueis,
    get_peer_institutions,
    get_agency_money_movement,
    get_missed_opportunities,
    get_lapsed_programs,
    get_data_freshness,
)

st.set_page_config(page_title="Action Dashboard — Federal Radar", layout="wide")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Action Dashboard")
    st.caption(MY_INSTITUTION)
    st.divider()

    peer_set = st.radio("Peer Set", ["Texas", "National", "Both"], index=0)

    st.divider()
    st.caption("All panels fixed to FY2025–2026 (current administration).")

# ---------------------------------------------------------------------------
# Load UEIs
# ---------------------------------------------------------------------------

my_ueis = tuple(get_my_ueis())
peer_items = get_peer_institutions(peer_set)
peer_ueis = tuple(uei for _, uei in peer_items)

if not my_ueis:
    st.error("No UEIs found for UNT. Check the institutions table.")
    st.stop()

st.markdown("# Action Dashboard")
st.caption("FY2025–2026 · Cross-Agency · Where's the money?")

# =========================================================================
# Panel 1: Where's the Money Moving?
# =========================================================================

st.divider()
st.subheader("Where's the Money Moving?")
st.caption(
    "Apples-to-apples: both years compared through the same Oct–May window. "
    "The faded portion shows what FY2025 awarded Jun–Sep (still ahead for FY2026)."
)

df_move = get_agency_money_movement(my_ueis, peer_ueis)

if df_move.empty:
    st.info("No FY2025/2026 award data found.")
else:
    # Build horizontal grouped bar chart — 3 segments
    df_plot = df_move.sort_values("change_m", ascending=True).copy()
    df_plot["source_upper"] = df_plot["source"].str.upper()

    # Color FY26 bars by direction vs FY25 YTD
    colors_26 = ["#2ecc71" if v >= 0 else "#e74c3c" for v in df_plot["change_m"]]

    fig = go.Figure()

    # FY25 YTD (Oct–May) — solid gray
    fig.add_trace(go.Bar(
        y=df_plot["source_upper"],
        x=df_plot["fy25_ytd_m"],
        name="FY25 Oct–May",
        orientation="h",
        marker_color="#7f8c8d",
    ))

    # FY25 Rest (Jun–Sep) — faded gray, stacked feel via separate trace
    fig.add_trace(go.Bar(
        y=df_plot["source_upper"],
        x=df_plot["fy25_rest_m"],
        name="FY25 Jun–Sep (ahead)",
        orientation="h",
        marker_color="#bdc3c7",
        marker_line=dict(color="#95a5a6", width=1),
    ))

    # FY26 YTD (Oct–May) — green/red
    fig.add_trace(go.Bar(
        y=df_plot["source_upper"],
        x=df_plot["fy26_ytd_m"],
        name="FY26 Oct–May",
        orientation="h",
        marker_color=colors_26,
    ))

    # Annotate UNT share
    for _, row in df_plot.iterrows():
        unt_total = row["unt_fy25_m"] + row["unt_fy26_m"]
        if unt_total > 0:
            max_x = max(
                row["fy25_ytd_m"] + row["fy25_rest_m"],
                row["fy26_ytd_m"],
            )
            fig.add_annotation(
                y=row["source_upper"],
                x=max_x,
                text=f"UNT: ${unt_total:.1f}M",
                showarrow=False,
                xanchor="left",
                xshift=8,
                font=dict(size=10, color="#2c3e50"),
            )

    fig.update_layout(
        barmode="group",
        height=max(350, len(df_plot) * 70),
        margin=dict(t=20, b=20, l=0, r=80),
        xaxis_title="Funding ($M)",
        legend=dict(orientation="h", y=1.05),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Auto-generated insight — now based on same-period comparison
    growing = df_move[df_move["pct_change"].notna() & (df_move["pct_change"] > 0)]
    shrinking = df_move[df_move["pct_change"].notna() & (df_move["pct_change"] < 0)]
    no_unt = df_move[(df_move["unt_fy25_m"] == 0) & (df_move["unt_fy26_m"] == 0)]

    insights = []
    if not growing.empty:
        parts = [f"{r['source'].upper()} (+{r['pct_change']:.0f}%)"
                 for _, r in growing.head(3).iterrows()]
        insights.append(f"**Growing (same period):** {', '.join(parts)}")
    if not shrinking.empty:
        parts = [f"{r['source'].upper()} ({r['pct_change']:.0f}%)"
                 for _, r in shrinking.head(3).iterrows()]
        insights.append(f"**Slower YTD:** {', '.join(parts)}")

    # Show how much FY25 rest-of-year is still ahead
    total_rest = df_move["fy25_rest_m"].sum()
    if total_rest > 0:
        insights.append(
            f"FY2025 awarded **${total_rest:,.0f}M** in Jun–Sep — "
            f"that spending window is still ahead for FY2026."
        )

    if not no_unt.empty:
        agencies = ", ".join(no_unt["source"].str.upper().tolist())
        insights.append(f"UNT has **no awards** in FY2025-2026 from: {agencies}")

    if insights:
        st.info("  \n".join(insights))

    # ----- "How Does UNT Compare?" summary table -----
    st.markdown("#### How Does UNT Compare?")
    st.caption(
        "UNT FY25 = full year (Oct '24–Sep '25). "
        "UNT FY26 = YTD (Oct '25–May '26). "
        "Field trend compares the same Oct–May window."
    )

    df_unt = df_move.copy()
    df_unt["Agency"] = df_unt["source"].str.upper()
    df_unt["Field Trend"] = df_unt["pct_change"].apply(
        lambda v: f"+{v:.0f}%" if pd.notna(v) and v > 0
        else (f"{v:.0f}%" if pd.notna(v) else "new")
    )
    # Show full-year FY25 so VPR sees the complete picture
    df_unt["UNT FY25"] = df_unt["unt_fy25_full_m"].apply(
        lambda v: f"${v:.1f}M" if v > 0 else "—"
    )
    df_unt["UNT FY26 YTD"] = df_unt["unt_fy26_m"].apply(
        lambda v: f"${v:.1f}M" if v > 0 else "—"
    )

    # Signal: what should the VPR pay attention to?
    def _signal(r):
        has_fy25 = r["unt_fy25_full_m"] > 0
        has_fy26 = r["unt_fy26_m"] > 0
        field_pct = r["pct_change"] if pd.notna(r["pct_change"]) else 0

        if not has_fy25 and not has_fy26:
            if field_pct > 20:
                return "Growing — UNT absent"
            return "Not competing"
        if has_fy25 and not has_fy26:
            return "Had FY25, nothing yet FY26"
        if not has_fy25 and has_fy26:
            return "New entry"
        # Both years present — compare UNT YTD to its own FY25 YTD
        if r["unt_fy25_m"] > 0:
            unt_pct = (r["unt_fy26_m"] - r["unt_fy25_m"]) / r["unt_fy25_m"] * 100
            if unt_pct > field_pct + 10:
                return "Outpacing field"
            if unt_pct < field_pct - 10:
                return "Falling behind"
            return "Tracking field"
        return "New entry"

    df_unt["Signal"] = df_unt.apply(_signal, axis=1)

    display_cols = ["Agency", "Field Trend", "UNT FY25", "UNT FY26 YTD", "Signal"]
    df_table = df_unt[display_cols].sort_values("Agency").reset_index(drop=True)
    df_table.index = range(1, len(df_table) + 1)

    # Color-code the Signal column
    def _signal_color(val):
        colors = {
            "Outpacing field": "color: #2ecc71; font-weight: bold",
            "New entry": "color: #2ecc71",
            "Tracking field": "color: #f39c12",
            "Falling behind": "color: #e74c3c",
            "Had FY25, nothing yet FY26": "color: #e74c3c; font-weight: bold",
            "Growing — UNT absent": "color: #e67e22; font-weight: bold",
            "Not competing": "color: #95a5a6",
        }
        return colors.get(val, "")

    styled_table = df_table.style.map(_signal_color, subset=["Signal"])
    st.dataframe(styled_table, use_container_width=True,
                 height=55 + 38 * len(df_table))

# =========================================================================
# Panel 2: Peer Wins You're Missing
# =========================================================================

st.divider()
st.subheader("Peer Wins You're Missing")
st.caption("Programs where peers won FY2025-2026 awards but UNT got nothing.")

df_missed = get_missed_opportunities(my_ueis, peer_ueis)

if df_missed.empty:
    st.success("No missed opportunities found — UNT competes everywhere peers do.")
else:
    total_missed_m = df_missed["peer_funding_m"].sum()
    n_programs = len(df_missed)

    st.warning(
        f"Your {peer_set} peers won **${total_missed_m:.1f}M** across "
        f"**{n_programs} programs** where UNT got nothing."
    )

    # Shorten peer names for display
    df_display = df_missed.copy()
    df_display["peer_names"] = df_display["peer_names"].apply(
        lambda s: ", ".join(PEER_SHORT.get(n.strip(), n.strip()) for n in s.split(",")) if pd.notna(s) else ""
    )
    df_display["source"] = df_display["source"].str.upper()
    df_display.columns = ["Agency", "Program ID", "Peer Awards", "Peer $M",
                          "# Peers", "Peers Who Won"]
    df_display.index = range(1, len(df_display) + 1)

    st.dataframe(
        df_display,
        use_container_width=True,
        height=min(600, 55 + 38 * len(df_display)),
    )

# =========================================================================
# Panel 3: Lapsed Capacity
# =========================================================================

st.divider()
st.subheader("Lapsed Capacity")
st.caption("Programs where UNT last won FY2022 or earlier — truly dormant, not pending. Min $500K, excludes ED student aid.")

df_lapsed = get_lapsed_programs(my_ueis)

if df_lapsed.empty:
    st.success("No lapsed programs — UNT is active in all historical programs.")
else:
    total_lapsed_m = df_lapsed["past_funding_m"].sum()
    n_lapsed = len(df_lapsed)

    st.warning(
        f"UNT previously won **{n_lapsed} programs** worth **${total_lapsed_m:.1f}M** "
        f"that have gone dormant."
    )

    df_lapsed_display = df_lapsed.copy()
    df_lapsed_display["source"] = df_lapsed_display["source"].str.upper()
    df_lapsed_display["last_fy"] = df_lapsed_display["last_fy"].astype(int)
    df_lapsed_display.columns = ["Agency", "Program", "Past Awards", "Past $M", "Last Won"]
    df_lapsed_display.index = range(1, len(df_lapsed_display) + 1)

    st.dataframe(
        df_lapsed_display,
        use_container_width=True,
        height=min(600, 55 + 38 * len(df_lapsed_display)),
        column_config={"Last Won": st.column_config.NumberColumn(format="%d")},
    )

# =========================================================================
# Data Freshness
# =========================================================================

st.divider()

with st.expander("Data Coverage & Freshness"):
    df_fresh = get_data_freshness()

    if df_fresh.empty:
        st.info("No data freshness information available.")
    else:
        df_fresh_display = df_fresh.copy()
        df_fresh_display["source"] = df_fresh_display["source"].str.upper()
        df_fresh_display.columns = ["Source", "Records", "Last Refresh", "Status"]

        # Color-code status
        def _style_status(val):
            if val == "success":
                return "color: #2ecc71"
            elif val == "never":
                return "color: #e74c3c"
            return ""

        styled = df_fresh_display.style.map(
            _style_status, subset=["Status"]
        ).format({"Records": "{:,}"})

        st.dataframe(styled, use_container_width=True)

        total_records = df_fresh["record_count"].sum()
        st.caption(f"Total: {total_records:,} award records across {len(df_fresh)} sources.")
