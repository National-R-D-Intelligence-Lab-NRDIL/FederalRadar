"""
Generate NIH FY2025-2026 PDF reports for Texas and National peers.
All charts use Funding ($M) metric.
"""
import sys, os, copy
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "app"))

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from queries import (
    MY_INSTITUTION, PEER_SHORT,
    get_my_ueis, get_peer_institutions, get_raw_comparison, get_field_wide_stats,
    get_raw_comparison_by_fy, get_heatmap_data, get_scoped_pis,
    get_validation_stats,
)
from pdf_export import generate_gap_report

# NSF name cleaning
_NSF_PREFIXES = (
    "Directorate for ", "Directorate, ", "Directorate - ",
    "Division of ", "Division for ", "Division - ",
    "Office of ", "Office for ",
)
def _clean_name(name):
    for prefix in _NSF_PREFIXES:
        if isinstance(name, str) and name.startswith(prefix):
            return name[len(prefix):]
    return name

def _fmt_dollars(m: float) -> str:
    """Auto-format a value in millions: $1.2B, $435M, $12.3M, $0.4M."""
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


def _to_png(fig, width=1000, height=700):
    try:
        fig_copy = copy.deepcopy(fig)
        cur_margin = fig_copy.layout.margin or {}
        cur_l = getattr(cur_margin, "l", None) or 10
        cur_b = getattr(cur_margin, "b", None) or 10
        fig_copy.update_layout(margin=dict(l=max(cur_l, 180), b=max(cur_b, 60)))
        return pio.to_image(fig_copy, format="png", width=width, height=height, scale=1)
    except Exception as e:
        print(f"  PNG export failed: {e}")
        return None


def build_report(peer_set: str, agency="nih", fy_start=2025, fy_end=2026):
    print(f"\n=== Building {peer_set} peers report ===")

    my_ueis = tuple(get_my_ueis())
    peer_items = get_peer_institutions(peer_set)
    peer_ueis = tuple(uei for _, uei in peer_items)

    df_raw = get_raw_comparison(my_ueis, peer_ueis, agency, fy_start, fy_end)
    df_field = get_field_wide_stats(agency, fy_start, fy_end)

    if df_raw.empty:
        print("  No data found!")
        return

    # Pivots
    pivot_n = df_raw.pivot_table(index="program_abbr", columns="institution", values="awards", aggfunc="sum", fill_value=0)
    pivot_m = df_raw.pivot_table(index="program_abbr", columns="institution", values="funding_m", aggfunc="sum", fill_value=0)
    abbr_to_name = df_raw[["program_abbr", "program"]].drop_duplicates("program_abbr").set_index("program_abbr")["program"].map(_clean_name).to_dict()

    if MY_INSTITUTION not in pivot_n.columns:
        pivot_n[MY_INSTITUTION] = 0
        pivot_m[MY_INSTITUTION] = 0.0

    peer_cols = [c for c in pivot_n.columns if c != MY_INSTITUTION]

    # Scorecard
    unt_df = df_raw[df_raw["institution"] == MY_INSTITUTION]
    unt_total_awards = int(unt_df["awards"].sum())
    unt_total_funding = round(unt_df["funding_m"].sum(), 1)
    totals = df_raw.groupby("institution")["funding_m"].sum().sort_values(ascending=False).reset_index()
    rank_list = totals["institution"].tolist()
    unt_rank = rank_list.index(MY_INSTITUTION) + 1 if MY_INSTITUTION in rank_list else None
    n_ranked = len(rank_list)

    peer_avg_funding = pivot_m[peer_cols].mean(axis=1)
    peer_avg_awards = pivot_n[peer_cols].mean(axis=1)
    dollar_gap = peer_avg_funding - pivot_m[MY_INSTITUTION]
    n_gaps = int((dollar_gap > 0).sum())

    # Headline
    gap_programs = dollar_gap[dollar_gap > 0].sort_values(ascending=False)
    _headline = ""
    if not gap_programs.empty:
        top_prog = gap_programs.index[0]
        top_prog_label = abbr_to_name.get(top_prog, top_prog)
        unt_awards_top = int(pivot_n.loc[top_prog, MY_INSTITUTION])
        peer_avg_top = round(float(peer_avg_awards.loc[top_prog]), 1)
        gap_m_top = round(float(dollar_gap[top_prog]), 2)
        top_peer_awards = pivot_n.loc[top_prog, peer_cols].sort_values(ascending=False)
        top_peer_name = PEER_SHORT.get(top_peer_awards.index[0], top_peer_awards.index[0])
        top_peer_count = int(top_peer_awards.iloc[0])
        _headline = (
            f"**Biggest gap: {top_prog_label}** — "
            f"In this program, UNT has **{unt_awards_top} awards**, "
            f"peers average **{peer_avg_top:.0f}** "
            f"({top_peer_name} leads with **{top_peer_count}**). "
            f"If UNT matched the peer average, it would represent "
            f"an additional **${gap_m_top:.1f}M** in funding."
        )

    # Gap table
    field_lookup = {}
    if not df_field.empty:
        for _, r in df_field.iterrows():
            field_lookup[r["program_abbr"]] = (
                int(r["field_awards"]), int(r["last_funded"]),
                int(r.get("awards_current", 0)), int(r.get("awards_prev", 0)), int(r.get("awards_two_ago", 0)),
            )

    top_peer_cols = pivot_n[peer_cols].sum().sort_values(ascending=False).index.tolist()
    rows = []
    for prog in pivot_n.index:
        full_name = abbr_to_name.get(prog, prog)
        if len(full_name) > 45:
            full_name = full_name[:42] + "..."
        unt_val = int(pivot_n.loc[prog, MY_INSTITUTION])
        peer_avg = float(pivot_n.loc[prog, peer_cols].mean())
        gap_m = round(float(pivot_m.loc[prog, peer_cols].mean()) - float(pivot_m.loc[prog, MY_INSTITUTION]), 2)
        field_awards, last_funded, cur, prev, two_ago = field_lookup.get(prog, (0, 0, 0, 0, 0))
        if prev == 0 and two_ago == 0: trend = "—"
        elif two_ago == 0: trend = "↑"
        elif prev == 0: trend = "↓"
        elif prev / two_ago >= 1.2: trend = "↑"
        elif prev / two_ago <= 0.8: trend = "↓"
        else: trend = "→"
        row = {"Program": full_name, "UNT": unt_val}
        for col in top_peer_cols:
            short = PEER_SHORT.get(col, col[:8])
            row[short] = int(pivot_n.loc[prog, col])
        row["Peer Avg"] = round(peer_avg, 1)
        row["Opportunity ($M)"] = gap_m
        row["Total Awards"] = field_awards
        row["Last Funded"] = last_funded if last_funded else "—"
        row["Trend"] = trend
        row[f"FY{fy_end}"] = "✓" if cur > 0 else ""
        rows.append(row)

    display = pd.DataFrame(rows).set_index("Program").sort_values("Opportunity ($M)", ascending=False)
    n_gaps = int((display["Opportunity ($M)"] > 0).sum())

    # Scope
    scope_label = "NIH"

    # --- Charts (all in Funding $M mode) ---
    print("  Building bar chart...")
    bar_data = totals.rename(columns={"institution": "Institution", "funding_m": "Funding ($M)"}).assign(
        Label=lambda d: d["Institution"].map(lambda x: PEER_SHORT.get(x, x)),
        IsUNT=lambda d: d["Institution"] == MY_INSTITUTION,
    ).sort_values("Funding ($M)", ascending=True)

    fig_bar = px.bar(bar_data, x="Funding ($M)", y="Label", orientation="h",
                     labels={"Label": "", "Funding ($M)": "Total Funding ($M)"},
                     color="IsUNT", color_discrete_map={True: "#e74c3c", False: "#2980b9"})
    fig_bar.update_traces(text=bar_data["Funding ($M)"].map(lambda x: f"${x:.1f}M"),
                          textposition="outside", textfont=dict(size=9), cliponaxis=False)
    _bar_label_w = max((len(str(lbl)) for lbl in bar_data["Label"]), default=10) * 7
    _bar_max = bar_data["Funding ($M)"].max() if not bar_data.empty else 1
    fig_bar.update_layout(showlegend=False, margin=dict(t=10, b=10, l=_bar_label_w, r=80),
                          height=max(300, 30 * len(bar_data)),
                          yaxis={"categoryorder": "total ascending", "automargin": True},
                          xaxis=dict(range=[0, _bar_max * 1.18]))

    # Heatmap — Funding ($M) mode
    print("  Building heatmap...")
    df_heatmap = get_heatmap_data(my_ueis, agency, fy_start, fy_end)
    fig_hm = None
    _hm_h = 700
    if not df_heatmap.empty:
        df_heatmap["label"] = df_heatmap["program"].map(_clean_name)
        abbr_label = df_heatmap[["program_abbr", "label"]].drop_duplicates("program_abbr").set_index("program_abbr")["label"].to_dict()
        hm_z = df_heatmap.pivot_table(index="program_abbr", columns="fiscal_year", values="field_funding_m", aggfunc="sum", fill_value=0)
        hm_unt = df_heatmap.pivot_table(index="program_abbr", columns="fiscal_year", values="unt_awards", aggfunc="sum", fill_value=0)
        row_order = hm_z.sum(axis=1).sort_values(ascending=True).index
        hm_z = hm_z.loc[row_order]
        hm_unt = hm_unt.loc[row_order]
        y_labels = [abbr_label.get(p, p) for p in row_order]
        x_labels = [str(int(y)) for y in hm_z.columns]
        text_vals = [[str(int(hm_unt.iloc[r, c])) if hm_unt.iloc[r, c] > 0 else "" for c in range(hm_unt.shape[1])] for r in range(hm_unt.shape[0])]

        z_raw = hm_z.values
        hm_unt_funding = None
        if "unt_funding_m" in df_heatmap.columns:
            hm_unt_funding = df_heatmap.pivot_table(index="program_abbr", columns="fiscal_year", values="unt_funding_m", aggfunc="sum", fill_value=0)
            hm_unt_funding = hm_unt_funding.reindex(index=row_order, columns=hm_z.columns, fill_value=0)
        if hm_unt_funding is not None:
            customdata = np.stack([z_raw, hm_unt_funding.values], axis=-1)
        else:
            customdata = np.stack([z_raw, np.zeros_like(z_raw)], axis=-1)

        fig_hm = go.Figure(go.Heatmap(
            z=hm_z.values, x=x_labels, y=y_labels, text=text_vals,
            texttemplate="%{text}", textfont={"size": 11}, colorscale="Blues",
            colorbar=dict(title="$M", thickness=14), customdata=customdata,
            hovertemplate="<b>%{y}</b><br>FY%{x}<br>Field: $%{customdata[0]:.1f}M<br>UNT: $%{customdata[1]:.1f}M (awards: %{text})<extra></extra>",
        ))
        _hm_label_w = max((len(lbl) for lbl in y_labels), default=10) * 7
        fig_hm.update_layout(margin=dict(t=30, b=10, l=_hm_label_w, r=10),
                             height=max(400, 26 * len(y_labels)),
                             xaxis=dict(side="top", title=""), yaxis=dict(title="", automargin=True))
        _hm_h = max(600, 32 * len(y_labels))

    # Sankey — Funding ($M) mode
    print("  Building Sankey...")
    df_sk = get_raw_comparison_by_fy(my_ueis, peer_ueis, agency, fy_start, fy_end)
    fig_sk = None
    _sk_h = 700
    if not df_sk.empty:
        val_col = "funding_m"
        prog_totals_sk = df_sk.groupby("program_abbr")[val_col].sum()
        programs_sk = prog_totals_sk.sort_values(ascending=False).index.tolist()
        n_prog = len(programs_sk)
        fy_list = sorted(df_sk["fiscal_year"].unique().tolist())
        n_fy = len(fy_list)
        inst_nodes = [MY_INSTITUTION] + peer_cols
        n_inst = len(inst_nodes)

        # Compute node totals for labels
        _prog_funding = df_sk.groupby("program_abbr")["funding_m"].sum()
        _fy_funding = df_sk.groupby("fiscal_year")["funding_m"].sum()
        _inst_funding = df_sk.groupby("institution")["funding_m"].sum()

        prog_labels = [
            f"{_clean_name(abbr_to_name.get(p, p))[:35]} ({_fmt_dollars(float(_prog_funding.get(p, 0)))})"
            for p in programs_sk
        ]
        fy_labels = [
            f"FY{fy} ({_fmt_dollars(float(_fy_funding.get(fy, 0)))})"
            for fy in fy_list
        ]
        inst_labels = [
            f"{'UNT' if i == MY_INSTITUTION else PEER_SHORT.get(i, i)} ({_fmt_dollars(float(_inst_funding.get(i, 0)))})"
            for i in inst_nodes
        ]
        all_labels = prog_labels + fy_labels + inst_labels

        prog_colors = ["rgba(142, 68, 173, 0.75)"] * n_prog
        fy_colors = ["rgba(39, 174, 96, 0.8)"] * n_fy
        inst_colors = ["#e74c3c" if i == MY_INSTITUTION else "#2980b9" for i in inst_nodes]
        node_colors = prog_colors + fy_colors + inst_colors

        sources, targets, values, link_colors = [], [], [], []
        fy_idx = {fy: n_prog + i for i, fy in enumerate(fy_list)}
        inst_idx = {inst: n_prog + n_fy + i for i, inst in enumerate(inst_nodes)}

        prog_fy = df_sk.groupby(["program_abbr", "fiscal_year"])[val_col].sum().reset_index()
        for _, row in prog_fy.iterrows():
            prog = row["program_abbr"]
            if prog not in programs_sk: continue
            val = float(row[val_col])
            if val > 0:
                sources.append(programs_sk.index(prog))
                targets.append(fy_idx[row["fiscal_year"]])
                values.append(val)
                link_colors.append("rgba(142, 68, 173, 0.3)")

        fy_inst = df_sk.groupby(["fiscal_year", "institution"])[val_col].sum().reset_index()
        for _, row in fy_inst.iterrows():
            inst = row["institution"]
            if inst not in inst_idx: continue
            val = float(row[val_col])
            if val > 0:
                sources.append(fy_idx[row["fiscal_year"]])
                targets.append(inst_idx[inst])
                values.append(val)
                link_colors.append("rgba(231, 76, 60, 0.35)" if inst == MY_INSTITUTION else "rgba(41, 128, 185, 0.25)")

        fig_sk = go.Figure(go.Sankey(
            node=dict(pad=14, thickness=20, label=all_labels, color=node_colors),
            link=dict(source=sources, target=targets, value=values, color=link_colors),
        ))
        fig_sk.update_layout(margin=dict(t=10, b=10, l=10, r=10),
                             height=max(500, 28 * n_prog + 200), font=dict(size=12))
        _sk_h = max(600, 28 * n_prog + 200)

    # --- Render PNGs ---
    print("  Rendering PNGs...")
    charts = []
    png = _to_png(fig_bar, height=min(900, max(400, 28 * len(bar_data))))
    if png: charts.append(("Total Funding by Institution", png))
    if fig_hm:
        png = _to_png(fig_hm, height=min(900, _hm_h))
        if png: charts.append(("Program Activity Heatmap", png))
    if fig_sk:
        png = _to_png(fig_sk, height=min(900, _sk_h))
        if png: charts.append(("Funding Flow: Programs to Institutions", png))

    # PI data
    pi_df = get_scoped_pis(MY_INSTITUTION, agency, fy_start, fy_end)
    if pi_df is not None and not pi_df.empty:
        pi_df = pi_df.copy()
        def _pi_scope(row):
            parts = [agency.upper()]
            for col in ["nih_institute", "dir_abbr", "div_abbr", "pgm_ele_name", "activity_code"]:
                if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
                    parts.append(str(row[col]).strip())
            return " / ".join(parts)
        pi_df.insert(1, "Scope", pi_df.apply(_pi_scope, axis=1))
        pi_df.drop(columns=["nih_institute", "dir_abbr", "div_abbr", "pgm_ele_name", "activity_code"],
                   errors="ignore", inplace=True)

    # FY peer funding
    fy_peer = (
        df_sk.groupby(["institution", "fiscal_year"])["funding_m"].sum().unstack(fill_value=0).reset_index()
    ) if not df_sk.empty else None

    # --- Generate PDF ---
    print("  Writing PDF...")
    pdf_bytes = generate_gap_report(
        scope_label=scope_label, fy_start=fy_start, fy_end=fy_end, peer_set=peer_set,
        unt_awards=unt_total_awards, unt_funding=unt_total_funding,
        unt_rank=unt_rank, n_ranked=n_ranked, n_gaps=n_gaps, headline=_headline,
        gap_df=display, peer_funding=totals, fy_peer_funding=fy_peer,
        pi_df=pi_df, charts=charts,
    )

    peer_tag = peer_set.lower().replace(" ", "_")
    fname = f"NIH_VPR_Report_FY{fy_start}-{fy_end}_{peer_tag}_peers.pdf"
    out_path = os.path.join(os.path.dirname(__file__), "..", fname)
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"  Saved: {fname} ({len(pdf_bytes)//1024} KB)")


if __name__ == "__main__":
    build_report("Texas")
    build_report("National")
    print("\nDone!")
