# Federal Radar

A grants intelligence tool for university research offices (VPR/AVP-Research).
Pulls federal award data from 12 agencies into a single SQLite database and surfaces
competitive gap analysis — showing where peers are winning and by how much.

**Current state:** 410,797 awards · $503.17B · FY2019–2026 · NSF, NIH, DOD, DOE,
NASA, USDA, ED, DOT, NEH, Commerce, EPA, DHS

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Running the Streamlit App](#running-the-streamlit-app)
4. [Database Schema](#database-schema)
5. [Data Sources](#data-sources)
6. [Setup](#setup)
7. [Loading Data](#loading-data)
8. [UEI Enrichment Pipeline](#uei-enrichment-pipeline)
9. [Validating the Data](#validating-the-data)
10. [Project Structure](#project-structure)
11. [Quick Reference](#quick-reference)

---

## Overview

Federal Radar answers one primary question for VPR/AVP-Research offices:

> **In [agency/program], where are peers beating us, and by how much?**

The Streamlit dashboard has three pages:

**Home — Competitive Gap Analysis**
- A 4-metric scorecard (UNT awards, funding, rank among peers, programs with gaps)
- A program breakdown table sorted by funding gap (all programs, peers side by side)
- A bar chart comparing all peer institutions by total funding
- Program activity heatmap and funding flow Sankey diagram

**Portfolio Risk**
- Agency concentration donut chart with warnings when a single agency > 50%
- What-if scenario: model the impact of a 10–50% cut to any agency
- Peer diversification table with HHI scores (sorted by concentration risk)
- Agency funding trend by fiscal year

**Expiring Awards**
- Scorecard: awards expiring, funding at risk, largest expiration, PIs affected
- Quarterly funding cliff chart (stacked by agency)
- Sortable awards table with CSV download
- Agency breakdown of expiring funding

Peers are pre-configured in the database — two sets available:
- **Texas peers:** Texas A&M, UT Austin, UT Arlington, UT Dallas, UTSA, UTEP, UTRGV, Texas State, Texas Tech, University of Houston
- **National peers:** Arizona State, Purdue, Georgia State, University of South Florida, UCF, University of Utah, University of Memphis, University of Illinois Chicago, Tulane, UC Riverside

---

## Architecture

```
Data Sources
    │
    ├── NSF API (nsf_api_fetcher.py)          → daily incremental
    ├── NSF Bulk ZIP (nsf_etl.py)             → historical backfill
    ├── NIH RePORTER API (nih_api_fetcher.py) → fiscal year download
    └── USASpending Bulk Download             → fiscal year download
            (usaspending_api_fetcher.py)        per agency, parallel
    │
    ▼
SQLite DB (federal_awards.db)
    │
    ├── awards table (unified, all sources, 410K rows)
    └── institutions table (UEI reference, 19,433 rows, peer flags)
    │
    ▼
Streamlit App (app/Home.py)
    └── queries.py (cached queries, peer constants, NSF name lookups)
```

**Deployment:** Railway. APScheduler runs daily NSF + NIH refresh.

---

## Running the Streamlit App

```bash
cd app
streamlit run Home.py
```

The app opens at `http://localhost:8501`.

**Sidebar controls:**
- **Agency** — NSF, NIH, DOD, DOE, NASA, USDA, ED, Commerce
- **Directorate / Division** (NSF) or **Institute** (NIH) — optional drill-down
- **Peer Set** — Texas, National, or Both
- **Fiscal Years** — slider, defaults to last 3 years

**What you see (Home page):**
1. Scorecard row: UNT Awards · UNT Funding · Rank Among Peers · Programs with Gaps
2. Headline: one-sentence summary of the biggest gap program
3. Program Breakdown table: all programs sorted by Opportunity ($M), peers side by side
4. Bar chart: total funding comparison across all institutions
5. Program activity heatmap and funding flow Sankey diagram

**Navigation:** Sidebar shows all 3 pages — Home, Portfolio Risk, Expiring Awards

**PDF Export (Home page only):** "Export PDF Report" button at the bottom of the Home page generates a shareable PDF of the current analysis — includes all tables and embeds the bar chart, heatmap, and Sankey as full-page images. Useful for sending to leadership while the app is hosted locally.

**Reading the table:**
- **Opportunity ($M)** = how much more funding UNT would receive if it matched the peer average. Negative = UNT is already at or above peer average.
- **UNT column color:** green = competitive/leading, orange = within reach (<75% of peer avg), red = significantly behind (<40%), dark red = zero awards
- **Field Total** = count of awards in this program across ALL US institutions (not just peers) — context for whether it's a large or niche program
- **Last Funded** = most recent fiscal year with an award in this program — distinguishes active from dormant programs

---

## Database Schema

### `awards` table (unified, all sources)

| Column | Type | Description |
|---|---|---|
| `awd_id` | TEXT PK | Base award ID (stable across all transactions) |
| `source` | TEXT | Data source: `nsf`, `nih`, `ed`, `dod`, etc. |
| `awd_titl_txt` | TEXT | Award title |
| `inst_name` | TEXT | Raw institution name from source |
| `inst_uei` | TEXT | SAM.gov Unique Entity Identifier (dedup key) |
| `inst_canonical_name` | TEXT | Normalized institution name (from institutions table) |
| `inst_state_code` | TEXT | 2-letter state code |
| `awd_amount` | REAL | Total award value in USD (see note below) |
| `fiscal_year` | INTEGER | Federal fiscal year (Oct 1 – Sep 30) |
| `dir_abbr` | TEXT | NSF directorate / NIH institute abbreviation |
| `div_abbr` | TEXT | NSF division abbreviation |
| `pgm_ele_name` | TEXT | Program element name |
| `pi_name` | TEXT | Principal investigator |
| `raw_json` | TEXT | Original source JSON (audit trail) |
| `created_at` | DATETIME | First insert timestamp — never updated |
| `updated_at` | DATETIME | Most recent upsert timestamp |

**`awd_amount` by source:**
- NSF: total award for full grant lifespan
- NIH: sum of all annual budget periods = true total project value (post-dedup)
- USASpending: cumulative total obligated to date

### `institutions` table (reference, UEI-keyed)

| Column | Type | Description |
|---|---|---|
| `inst_uei` | TEXT PK | SAM.gov UEI |
| `canonical_name` | TEXT | Normalized display name |
| `inst_state_code` | TEXT | State |
| `is_my_institution` | INTEGER | 1 = University of North Texas |
| `is_peer_texas` | INTEGER | 1 = Texas peer institution |
| `is_peer_national` | INTEGER | 1 = National peer institution |
| `peer_label` | TEXT | Short display name for peers |

---

## Data Sources

| Source | Records | Funding | Pipeline |
|---|---|---|---|
| NIH | 156,439 | $223.1B | `nih_api_fetcher.py` → `nih_deduplicate.py` |
| NSF | 83,845 | $50.0B | `nsf_etl.py` (bulk) + `nsf_api_fetcher.py` (daily) |
| ED | 74,901 | $126.9B | `usaspending_api_fetcher.py` |
| USDA | 27,276 | $18.4B | `usaspending_api_fetcher.py` |
| DOD | 26,408 | $31.7B | `usaspending_api_fetcher.py` |
| NASA | 17,424 | $10.6B | `usaspending_api_fetcher.py` |
| DOE | 10,395 | $24.4B | `usaspending_api_fetcher.py` |
| Commerce | 6,749 | $11.6B | `usaspending_api_fetcher.py` |
| DOT | 2,912 | $3.4B | `usaspending_api_fetcher.py` |
| NEH | 2,703 | $0.4B | `usaspending_api_fetcher.py` |
| EPA | 1,595 | $2.5B | `usaspending_api_fetcher.py` |
| DHS | 150 | $0.3B | FY2019 only (slow download) |

**Notes:**
- ED includes COVID CARES Act formula/relief grants — `awd_amount` is large ($90B+ in 2020/2021) and not directly comparable to research grants
- Federal fiscal year = October 1 – September 30 (Oct 2022 action = FY2023)
- HHS (non-NIH) not loaded — same slow download issue as DHS

---

## Setup

### Prerequisites

- Python 3.11
- Dependencies: `pip install streamlit pandas plotly fpdf2 kaleido`
- For data pipeline: no additional dependencies (standard library only for core ETL)

### Initialize the database

```bash
python src/db.py
```

Creates `data/federal_awards.db` with schema, WAL mode, and all indexes. Safe to re-run.

### Directory structure

```
data/raw/
├── nsf/
│   ├── 2016.zip through 2026.zip
└── usaspending/
    ├── 2019/
    │   ├── ED_FY2019.zip
    │   ├── ED_FY2019.csv
    │   ├── ED_FY2019.jsonl
    │   └── ED_FY2019.done        ← sentinel: only present when fully processed
    └── ...
```

---

## Loading Data

### NSF (bulk ZIPs)

```bash
python scripts/nsf_etl.py
```

Processes all ZIPs in `data/raw/nsf/`. First full load takes 10–20 minutes. Idempotent.

### NSF (incremental daily sync)

```bash
python scripts/nsf_api_fetcher.py           # last 1 day
python scripts/nsf_api_fetcher.py --days 30  # last 30 days
```

### NIH

```bash
python scripts/nih_api_fetcher.py    # download by fiscal year
python scripts/nih_deduplicate.py    # deduplicate (one row per project)
```

### USASpending (ED, DOD, DOE, NASA, USDA, Commerce, DOT, NEH, EPA)

```bash
python scripts/usaspending_api_fetcher.py
```

Downloads all agencies in parallel for each fiscal year. Saves `.zip`, `.csv`, `.jsonl`,
and `.done` sentinel. Skips years with existing `.done` files. Loads into DB automatically.

---

## UEI Enrichment Pipeline

UEI (Unique Entity Identifier) is the SAM.gov-assigned 12-character ID used as a
cross-source deduplication key. Run these phases in order after loading all data.

```bash
python scripts/phase1_usaspending_uei.py     # extract UEIs from USASpending raw_json
python scripts/phase2_build_institutions_table.py  # build institutions reference table
python scripts/phase3a_nsf_uei_extract.py    # extract UEIs from NSF raw_json
python scripts/phase3b_nih_uei_enrich.py     # NIH UEI enrichment
python scripts/phase4_canonical_names.py     # rebuild institutions + canonical names
```

After Phase 4, all awards have `inst_canonical_name` populated. The Streamlit app
uses this column for all institution queries.

**To add or change peer institutions:** Edit `PEER_FLAGS` in
`scripts/phase4_canonical_names.py` and re-run Phase 4. It rebuilds from scratch safely.

---

## Validating the Data

### Quick DB health check

```bash
sqlite3 data/federal_awards.db "PRAGMA integrity_check;"
# Expected: ok

sqlite3 data/federal_awards.db "SELECT COUNT(*), ROUND(SUM(awd_amount)/1e9,2) FROM awards;"
# Expected: ~410797|503.17

sqlite3 data/federal_awards.db "SELECT COUNT(*) FROM institutions WHERE is_my_institution=1 OR is_peer_texas=1 OR is_peer_national=1;"
# Expected: 27+ (UNT has 2 UEIs)
```

### Verify peer configuration

```bash
sqlite3 data/federal_awards.db "
  SELECT peer_label, inst_uei, is_my_institution, is_peer_texas, is_peer_national
  FROM institutions
  WHERE is_my_institution=1 OR is_peer_texas=1 OR is_peer_national=1
  ORDER BY is_my_institution DESC, is_peer_texas DESC, peer_label;
"
```

### Verify inst_canonical_name coverage

```bash
sqlite3 data/federal_awards.db "
  SELECT COUNT(*) as total,
         COUNT(inst_canonical_name) as with_canonical,
         ROUND(COUNT(inst_canonical_name)*100.0/COUNT(*),1) as pct
  FROM awards;
"
# Expected: ~99.7%+ coverage
```

---

## Project Structure

```
Federal Radar/
├── app/
│   ├── Home.py                        Streamlit app — competitive gap analysis
│   ├── pages/
│   │   ├── 1_Portfolio_Risk.py        Agency concentration, what-if, peer HHI
│   │   └── 2_Expiring_Awards.py       Funding cliff, expiring awards table
│   ├── pdf_export.py                  PDF report generator (fpdf2 + kaleido)
│   └── queries.py                     DB queries, peer config, NSF name constants
├── data/
│   ├── federal_awards.db              SQLite, WAL mode, ~2GB
│   └── raw/
│       ├── nsf/                       NSF bulk ZIPs (2016–2026)
│       └── usaspending/               Per-year, per-agency raw downloads
├── scripts/
│   ├── nsf_etl.py                     NSF bulk ZIP loader
│   ├── nsf_api_fetcher.py             NSF incremental API sync
│   ├── nih_api_fetcher.py             NIH RePORTER API fetcher
│   ├── nih_deduplicate.py             NIH deduplication (one row per project)
│   ├── usaspending_api_fetcher.py     USASpending bulk download + load
│   ├── phase1_usaspending_uei.py      UEI extraction from USASpending raw_json
│   ├── phase2_build_institutions_table.py  Institutions reference table
│   ├── phase3a_nsf_uei_extract.py     UEI extraction from NSF raw_json
│   ├── phase3b_nih_uei_enrich.py      NIH UEI enrichment
│   └── phase4_canonical_names.py      Rebuild institutions + canonical names
├── src/
│   └── db.py                          Schema, upsert logic, indexes
├── tests/
│   ├── test_data_governance.py        Governance test suite
│   └── baselines.json                 Expected counts/totals
├── scheduler.py                       APScheduler daily refresh (NSF + NIH)
├── railway.toml                       Railway deployment config
├── CONTEXT.md                         Full technical decision log
└── README.md                          This file
```

---

## Quick Reference

| Task | Command |
|---|---|
| **Run the app** | `cd app && streamlit run Home.py` |
| Initialize DB | `python src/db.py` |
| Load NSF ZIPs | `python scripts/nsf_etl.py` |
| NSF daily sync | `python scripts/nsf_api_fetcher.py` |
| Load NIH | `python scripts/nih_api_fetcher.py` |
| Deduplicate NIH | `python scripts/nih_deduplicate.py` |
| Load USASpending | `python scripts/usaspending_api_fetcher.py` |
| Run UEI pipeline | `python scripts/phase4_canonical_names.py` |
| DB integrity check | `sqlite3 data/federal_awards.db "PRAGMA integrity_check;"` |
| Record count | `sqlite3 data/federal_awards.db "SELECT COUNT(*), ROUND(SUM(awd_amount)/1e9,2) FROM awards;"` |
