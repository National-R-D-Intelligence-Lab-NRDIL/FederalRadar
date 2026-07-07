# Federal Radar

A grants intelligence platform for university research offices (VPR/AVP-Research).
Pulls federal award data from 13 agencies into a single SQLite database and surfaces
competitive gap analysis — showing where peers are winning and by how much.

**Current state:** 424,097 awards · $541B · FY2019–2026 · 13 agencies

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
9. [HERD Institution Crosswalk](#herd-institution-crosswalk)
10. [Grants.gov Pipeline](#grantsgov-pipeline)
11. [Validating the Data](#validating-the-data)
12. [Project Structure](#project-structure)
13. [Quick Reference](#quick-reference)

---

## Overview

Federal Radar answers one primary question for VPR/AVP-Research offices:

> **In [agency/program], where are peers beating us, and by how much?**

Any of 1,059 research universities and health science centers can be selected as the focal
institution. The analysis compares that institution against a pre-configured peer group
(Texas or National).

### Dashboard Pages

**Home — Competitive Gap Analysis**
- Institution picker: select any HERD research university or freestanding health science center
  (1,059 institutions, filterable by state)
- 4-metric scorecard: awards, funding, rank among peers, programs with gaps
- Program breakdown table sorted by funding gap (all programs, peers side by side)
- Bar chart, program activity heatmap, and funding flow Sankey diagram
- PDF export

**Portfolio Risk**
- Agency concentration donut chart (warning when single agency > 50%)
- What-if scenario: model the impact of a 10–50% cut to any agency
- Peer diversification table with HHI scores
- Agency funding trend by fiscal year

**Expiring Awards**
- Scorecard: awards expiring, funding at risk, largest expiration, PIs affected
- Quarterly funding cliff chart (stacked by agency)
- Sortable awards table with CSV download

**Action Dashboard**
- Cross-agency YTD comparison (apples-to-apples current-year snapshot)
- "How Does My Institution Compare?" table
- Peer missed opportunities
- Lapsed capacity analysis

**Data Dictionary**
- Agency abbreviations and field definitions
- Peer set composition
- Data coverage stats by agency

**Open Opportunities**
- Open Grants.gov solicitations where peers have historically won and the focal institution is absent
- Programs where the focal institution has a track record (revisit candidates)
- Filters: peer set, status (posted/forecasted), lookback FY, agency

### Peer Sets

Two pre-configured sets (UNT's official institutional peer lists):
- **Texas:** Texas A&M, UT Austin, UT Arlington, UT Dallas, UTSA, UTEP, UTRGV, Texas State, Texas Tech, University of Houston
- **National:** Arizona State, Purdue, Georgia State, University of South Florida, UCF, University of Utah, University of Memphis, University of Illinois Chicago, Tulane, UC Riverside

---

## Architecture

```
Data Sources
    │
    ├── NSF API (nsf_api_fetcher.py)          → daily incremental
    ├── NSF Bulk ZIP (nsf_etl.py)             → historical backfill
    ├── NIH RePORTER API (nih_api_fetcher.py) → fiscal year download + daily incremental
    ├── USASpending Bulk Download             → fiscal year, per agency (historical backfill)
    │       (usaspending_api_fetcher.py)
    ├── USASpending Advanced Search API       → daily incremental (all 11 non-NSF/NIH agencies,
    │       (usaspending_api_fetcher.py)          one paginated call, rolling date window)
    └── Grants.gov XML Extract (fetch_grantsgov.py) → daily (manual — not yet scheduled)
    │
    ▼
SQLite DB (federal_awards.db)
    │
    ├── awards             — 424K rows, all agencies, UEI-keyed
    ├── institutions       — 19,433 rows, canonical names, peer flags
    ├── herd_institutions  — 1,108 IPEDS institutions → awards UEIs (1,059 matched)
    ├── opportunities      — Grants.gov NOFOs (posted + forecasted)
    ├── opportunity_cfdas  — junction: opportunities ↔ CFDA codes
    └── refresh_log        — audit trail of every scheduled refresh run
    │
    ▼
Streamlit App (app/Home.py + app/pages/)
    └── queries.py (all cached queries, peer constants, institution picker)
```

**Deployment:** Railway. APScheduler runs daily refresh: NSF (08:00 UTC), NIH (08:05 UTC),
USASpending (08:10 UTC). Grants.gov is still a manual/one-time load — not yet on the scheduler.

---

## Running the Streamlit App

```bash
cd app
streamlit run Home.py
```

The app opens at `http://localhost:8501`.

### Sidebar controls

| Control | Options |
|---------|---------|
| **State** | Filter institution list by state (optional) |
| **Institution** | Any of 1,059 matched HERD research universities / health science centers |
| **Agency** | nsf, nih, dod, doe, nasa, usda, ed, hhs, commerce, dot, neh, epa, dhs |
| **Directorate / Division** | NSF only — optional drill-down |
| **Institute** | NIH only — optional drill-down |
| **Peer Set** | Texas, National, or Both |
| **Fiscal Years** | Slider, defaults to last 3 years |

### Home page layout

1. Scorecard: Awards · Funding · Rank Among Peers · Programs with Gaps
2. Headline: one-sentence summary of the biggest gap program
3. Program Breakdown table: all programs sorted by Opportunity ($M), peers side by side
4. Bar chart: total funding by institution
5. Program Activity Heatmap: field-wide activity with focal institution's counts annotated
6. Funding Flow Sankey: Programs → Fiscal Year → Institutions

### Reading the gap table

- **Opportunity ($M)** — how much more the focal institution would receive if it matched the peer average. Negative = already at or above peer average.
- **Column color:** green = competitive/leading · orange = within reach (<75% of peer avg) · red = significantly behind (<40%) · dark red = zero awards
- **Total Awards** — count across ALL US institutions (not just peers) in this program and FY range
- **Last Funded** — most recent FY with an award in this program
- **Trend** — field-wide award count direction: ↑ growing · → flat · ↓ declining

---

## Database Schema

### `awards` table

| Column | Type | Description |
|--------|------|-------------|
| `awd_id` | TEXT PK | Base award ID (stable across transactions) |
| `source` | TEXT | `nsf`, `nih`, `ed`, `dod`, etc. |
| `awd_titl_txt` | TEXT | Award title |
| `inst_name` | TEXT | Raw institution name from source |
| `inst_uei` | TEXT | SAM.gov Unique Entity Identifier (dedup key) |
| `inst_canonical_name` | TEXT | Normalized institution name |
| `awd_amount` | REAL | Total award value in USD |
| `fiscal_year` | INTEGER | Federal fiscal year (Oct 1 – Sep 30) |
| `dir_abbr` | TEXT | NSF directorate / NIH institute abbreviation |
| `div_abbr` | TEXT | NSF division abbreviation |
| `pgm_ele_name` | TEXT | Program element name |
| `pi_name` | TEXT | Principal investigator |
| `raw_json` | TEXT | Original source JSON (audit trail) |

**`awd_amount` by source:**
- NSF: total award for full grant lifespan
- NIH: sum of all annual budget periods = true total project value (post-dedup)
- USASpending: cumulative total obligated to date

### `institutions` table

| Column | Type | Description |
|--------|------|-------------|
| `inst_uei` | TEXT PK | SAM.gov UEI |
| `canonical_name` | TEXT | Normalized display name |
| `inst_state_code` | TEXT | State |
| `is_my_institution` | INTEGER | 1 = University of North Texas |
| `is_peer_texas` | INTEGER | 1 = Texas peer |
| `is_peer_national` | INTEGER | 1 = National peer |
| `peer_label` | TEXT | Short display name |

### `herd_institutions` table

| Column | Type | Description |
|--------|------|-------------|
| `unitid` | TEXT PK | IPEDS unit ID |
| `ipeds_name` | TEXT | IPEDS institution name |
| `state` | TEXT | State abbreviation |
| `carnegie` | TEXT | C18BASIC code (15=R1, 16=R2, 17=D/PU, 18–20=Master's, 25=Medical School/HSC) |
| `awards_uei` | TEXT | Matched UEI in awards DB |
| `awards_name` | TEXT | Canonical name in awards DB |
| `match_type` | TEXT | `direct`, `secondary_uei`, `case_fix`, `manual`, `name_match`, `no_awards` |

### `opportunities` table

Grants.gov NOFOs — key fields: `opportunity_id` (PK), `opportunity_number`, `agency_code`,
`opportunity_title`, `derived_status` (posted/forecasted/closed), `award_ceiling`,
`close_date`, `posted_date`, `cfda_numbers`.

---

## Data Sources

| Source | Records | Funding | Notes |
|--------|---------|---------|-------|
| NIH | 156,908 | $223.5B | Deduplicated by `core_project_num` |
| NSF | 84,077 | $50.1B | Complete |
| ED | 74,901 raw / 8,266 research | $126.9B / $13.8B | 35 non-research CFDAs excluded at query time |
| USDA | 27,276 | $18.4B | Complete |
| DOD | 26,408 | $31.7B | Complete |
| NASA | 17,424 | $10.6B | Complete |
| HHS (non-NIH) | 12,248 | $37.6B | HRSA, CDC, SAMHSA, ACF |
| DOE | 10,395 | $24.4B | Complete |
| Commerce | 6,749 | $11.5B | Complete |
| DOT | 2,912 | $3.4B | Complete |
| NEH | 2,703 | $0.4B | Complete |
| EPA | 1,595 | $2.5B | Complete |
| DHS | 159 | $0.3B | FY2019 only — slow download |

**Notes:**
- ED raw data includes HEERF/CARES formula grants. All queries exclude 35 non-research CFDAs via `_ed_exclusion_clause()`. Raw data preserved.
- Federal fiscal year = October 1 – September 30 (Oct 2022 action = FY2023)

---

## Setup

### Prerequisites

```bash
pip install streamlit pandas plotly fpdf2 kaleido requests
```

Python 3.11 required. No additional dependencies for core ETL.

### Initialize the database

```bash
python src/db.py
```

Creates `data/federal_awards.db` with schema, WAL mode, and all indexes. Safe to re-run.

### IPEDS data

Download `HD2023.csv` from [NCES IPEDS](https://nces.ed.gov/ipeds/use-the-data) and place at `data/ipeds/HD2023.csv`. Required for the HERD crosswalk.

---

## Loading Data

### NSF

```bash
python scripts/nsf_etl.py                    # bulk ZIPs (historical)
python scripts/nsf_api_fetcher.py            # incremental daily sync
python scripts/nsf_api_fetcher.py --days 30  # last 30 days
```

### NIH

```bash
python scripts/nih_api_fetcher.py   # download by fiscal year
python scripts/nih_deduplicate.py   # deduplicate (one row per project)
```

### USASpending (ED, DOD, DOE, NASA, USDA, HHS, Commerce, DOT, NEH, EPA, DHS)

```bash
python scripts/usaspending_api_fetcher.py
```

Downloads all agencies in parallel for each fiscal year. Saves `.zip`, `.csv`, `.jsonl`,
and `.done` sentinel. Skips years with existing `.done` files. Loads into DB automatically.

### Grants.gov (open opportunities)

```bash
python scripts/fetch_grantsgov.py    # download daily XML extract → JSONL
python scripts/load_grantsgov.py     # upsert into opportunities table
python scripts/validate_grantsgov.py # spot-check against live API
```

---

## UEI Enrichment Pipeline

UEI (Unique Entity Identifier) is the SAM.gov-assigned 12-character ID used as a
cross-source deduplication key. Run in order after loading all raw data:

```bash
python scripts/phase2_build_institutions_table.py  # build institutions reference table
python scripts/phase3a_nsf_uei_extract.py          # extract UEIs from NSF raw_json
python scripts/phase3b_nih_uei_enrich.py           # NIH UEI enrichment
python scripts/phase4_canonical_names.py           # rebuild institutions + canonical names + peer flags
```

After Phase 4, all awards have `inst_canonical_name` populated.

**To add or change peer institutions:** Edit `PEER_FLAGS` in `scripts/phase4_canonical_names.py` and re-run Phase 4.

---

## HERD Institution Crosswalk

Maps 1,108 IPEDS Carnegie 15–20 (doctoral + master's) and Carnegie 25 (freestanding medical
schools / health science centers) institutions to their correct `inst_uei` in the awards
database. Institutions often file under a different SAM.gov entity than their IPEDS
registration (research foundations, system offices, etc.).

**Business decision — HSCs are independently selectable, never merged into a parent
university.** Many university systems (UNT, UT, Texas A&M, Texas Tech, Oklahoma, etc.) have
a health science center that is legally, financially, and competitively distinct from the
main campus, even though both fall under one system name. Carnegie code 25 institutions were
originally excluded from the crosswalk (scope was doctoral/master's only), which meant
UNT Health Science Center — and every other freestanding HSC nationally — had no way to be
selected as its own focal institution, even though it is a separate line item in the awards
data with its own UEI. Adding Carnegie 25 makes HSCs selectable as standalone institutions;
it does **not** roll their awards up into the parent university, and `is_my_institution` in
the `institutions` table is unaffected.

```bash
python scripts/build_herd_crosswalk.py  # regenerates data/herd_ipeds_crosswalk.csv
python scripts/load_herd_crosswalk.py   # loads CSV into herd_institutions table
```

**Match rate:** 1,059 / 1,108 = 95.6%. All R1 (131) and R2 (134) institutions matched;
54 / 55 Carnegie-25 medical schools/HSCs matched (only Mayo Clinic College of Medicine has
no awards-DB presence). Remaining 49 unmatched are for-profits, theological colleges, and
schools with no federal R&D.

**Match priority:** direct UEI → secondary UEI → case normalization → manual override → keyword name search → no match

---

## Validating the Data

```bash
# DB integrity
sqlite3 data/federal_awards.db "PRAGMA integrity_check;"

# Record counts
sqlite3 data/federal_awards.db "SELECT COUNT(*), ROUND(SUM(awd_amount)/1e9,2) FROM awards;"
# Expected: ~424097 | 541.xx

# HERD crosswalk
sqlite3 data/federal_awards.db "SELECT COUNT(*), COUNT(awards_uei) FROM herd_institutions;"
# Expected: 1108 | 1059

# Peer configuration
sqlite3 data/federal_awards.db "
  SELECT peer_label, inst_uei, is_my_institution, is_peer_texas, is_peer_national
  FROM institutions
  WHERE is_my_institution=1 OR is_peer_texas=1 OR is_peer_national=1
  ORDER BY is_my_institution DESC, is_peer_texas DESC, peer_label;
"
```

---

## Project Structure

```
Federal Radar/
├── app/
│   ├── Home.py                        Competitive gap analysis (institution picker)
│   ├── pages/
│   │   ├── 1_Portfolio_Risk.py        Agency concentration, what-if, peer HHI
│   │   ├── 2_Expiring_Awards.py       Funding cliff, expiring awards table
│   │   ├── 3_Action_Dashboard.py      Cross-agency YTD, missed opportunities
│   │   ├── 4_Data_Dictionary.py       Field definitions, peer sets, coverage stats
│   │   └── 5_Open_Opportunities.py    Grants.gov — peer gaps + revisit candidates
│   ├── pdf_export.py                  PDF report generator (fpdf2 + kaleido)
│   └── queries.py                     All cached queries, peer config, HERD picker
├── data/
│   ├── federal_awards.db              SQLite, WAL mode, ~2GB
│   ├── herd_ipeds_crosswalk.csv       IPEDS → awards UEI crosswalk (1,108 rows)
│   ├── ipeds/HD2023.csv               IPEDS institutional data (not in repo — download separately)
│   └── raw/
│       ├── grants_gov/                Daily Grants.gov JSONL extracts
│       └── usaspending/               {AGENCY}_FY{YEAR}.{zip,csv,jsonl,done}
├── scripts/
│   ├── nsf_etl.py                     NSF bulk ZIP loader
│   ├── nsf_api_fetcher.py             NSF incremental daily sync
│   ├── nih_api_fetcher.py             NIH RePORTER API fetcher
│   ├── nih_deduplicate.py             NIH deduplication (one row per project)
│   ├── usaspending_api_fetcher.py     USASpending bulk download + load
│   ├── phase2_build_institutions_table.py  Build institutions reference table
│   ├── phase3a_nsf_uei_extract.py     Extract UEIs from NSF raw_json
│   ├── phase3b_nih_uei_enrich.py      NIH UEI enrichment
│   ├── phase4_canonical_names.py      Rebuild institutions + peer flags
│   ├── build_herd_crosswalk.py        Build IPEDS → awards UEI crosswalk
│   ├── load_herd_crosswalk.py         Load crosswalk into herd_institutions table
│   ├── fetch_grantsgov.py             Download Grants.gov daily extract
│   ├── load_grantsgov.py              Load Grants.gov into opportunities table
│   └── validate_grantsgov.py          Spot-check Grants.gov data vs live API
├── src/
│   └── db.py                          Schema, upsert logic, indexes, pragmas
├── tests/
│   ├── test_data_governance.py        Governance test suite
│   └── baselines.json                 Expected counts/totals
├── scheduler.py                       APScheduler daily refresh (NSF + NIH + USASpending)
├── railway.toml                       Railway deployment config
├── CONTEXT.md                         Full technical decision log
└── README.md                          This file
```

---

## Quick Reference

| Task | Command |
|------|---------|
| **Run the app** | `cd app && streamlit run Home.py` |
| Initialize DB | `python src/db.py` |
| Load NSF ZIPs | `python scripts/nsf_etl.py` |
| NSF daily sync | `python scripts/nsf_api_fetcher.py` |
| Load NIH | `python scripts/nih_api_fetcher.py && python scripts/nih_deduplicate.py` |
| Load USASpending | `python scripts/usaspending_api_fetcher.py` |
| Load Grants.gov | `python scripts/fetch_grantsgov.py && python scripts/load_grantsgov.py` |
| Rebuild institutions | `python scripts/phase4_canonical_names.py` |
| Rebuild HERD crosswalk | `python scripts/build_herd_crosswalk.py && python scripts/load_herd_crosswalk.py` |
| DB integrity check | `sqlite3 data/federal_awards.db "PRAGMA integrity_check;"` |
| Record count | `sqlite3 data/federal_awards.db "SELECT COUNT(*), ROUND(SUM(awd_amount)/1e9,2) FROM awards;"` |
