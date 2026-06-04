# Federal Radar — Technical Context & Decision Log

**Last updated:** 2026-06-04
**Purpose:** Single source of truth for every significant technical decision made during
development. Anyone picking up this project — new developer, stakeholder, or future self —
should be able to read this and understand not just what we built, but why.

---

## 0. Quick Context (Read This First)

> **For Claude or any new session:** Read this section before anything else. It tells you exactly where the project stands and what to do next without reading the full file.

### What This Is
Federal Radar is a grants intelligence tool for university research offices (VPR/AVP-Research). It pulls federal award data from multiple agencies into a single SQLite database and surfaces competitive gap analysis through a Streamlit dashboard — showing research administrators where peers are beating them and by how much.

### Tech Stack
- **Language:** Python 3.11
- **Database:** SQLite (`data/federal_awards.db`, WAL mode, ~2GB)
- **UI:** Streamlit (`app/Home.py`) — single-page competitive gap analysis
- **Deployment:** Railway (APScheduler daily refresh)

### Current DB State (as of 2026-06-04)
423,756 records · $541B · FY2019–2026 · 13 sources · 19,433 institutions (UEI-deduped)

| Source | Records | Funding | Complete? |
|--------|---------|---------|-----------|
| NIH | 156,908 | $223.5B | Yes (deduplicated by core project) |
| NSF | 84,077 | $50.1B | Yes |
| ED | 74,901 (8,266 after filter) | $126.9B ($13.8B research-only) | Yes — non-research excluded at query time |
| USDA | 27,276 | $18.4B | Yes |
| DOD | 26,408 | $31.7B | Yes |
| NASA | 17,424 | $10.6B | Yes |
| HHS (non-NIH) | 12,248 | $37.6B | Yes (HRSA, CDC, SAMHSA, ACF) |
| DOE | 10,395 | $24.4B | Yes |
| Commerce | 6,749 | $11.5B | Yes |
| DOT | 2,912 | $3.4B | Yes |
| NEH | 2,703 | $0.4B | Yes |
| EPA | 1,595 | $2.5B | Yes |
| DHS | 159 | $0.3B | FY2019 only — slow download |

**ED filtering:** 35 non-research CFDA codes (HEERF/CARES Act + TRIO/Impact Aid/Title III formula grants) are excluded at query time via `_ed_exclusion_clause()`. Raw data preserved in DB.

### Key Files
| File | Purpose |
|------|---------|
| `src/db.py` | Schema, upsert logic, indexes, SQLite pragmas |
| `app/Home.py` | Streamlit UI — competitive gap analysis (main page) |
| `app/pages/1_Portfolio_Risk.py` | Portfolio Risk — agency concentration, what-if, peer HHI |
| `app/pages/2_Expiring_Awards.py` | Expiring Awards — funding cliff, expiring awards table |
| `app/pages/3_Action_Dashboard.py` | Action Dashboard — cross-agency YTD, missed opportunities, lapsed capacity |
| `app/pages/4_Data_Dictionary.py` | Data Dictionary — agency abbreviations, field definitions, peer sets |
| `app/queries.py` | All DB queries with 1-hour cache; peer config constants; ED exclusion filter |
| `app/pdf_export.py` | PDF report generator (fpdf2 + kaleido) — tables, charts, PI breakdown |
| `scripts/usaspending_api_fetcher.py` | USASpending bulk download + load (ED, DOT, NEH, DOD, etc.) |
| `scripts/nih_api_fetcher.py` | NIH RePORTER API fetcher |
| `scripts/nih_deduplicate.py` | NIH deduplication (one row per project, sum of annual budgets) |
| `scripts/nsf_etl.py` | NSF bulk ZIP loader |
| `scripts/nsf_api_fetcher.py` | NSF incremental daily sync |
| `scripts/phase4_canonical_names.py` | Rebuild institutions table + populate inst_canonical_name |
| `scheduler.py` | APScheduler — daily NSF + NIH refresh on Railway |

### What's Done
- [x] Data pipeline: NSF, NIH, DOD, USDA, NASA, DOE, Commerce, EPA, ED, DOT, NEH, DHS, HHS (423K records, 13 agencies)
- [x] NIH deduplication (453K → 156K rows, funding preserved)
- [x] HHS (non-NIH) full load — 12,248 records, $37.6B
- [x] ED non-research filter — 35 CFDA codes excluded at query time ($126.9B → $13.8B research-only)
- [x] UEI enrichment pipeline (all 3 sources — extracted from raw_json)
- [x] Institutions reference table (19,433 rows, UEI as key, canonical names)
- [x] Peer institution configuration (25 UEIs flagged across Texas + National peers)
- [x] Streamlit competitive gap analysis dashboard (Home.py)
- [x] Portfolio Risk page — agency concentration donut, what-if scenario, peer HHI table, agency trend
- [x] Expiring Awards page — scorecard, quarterly funding cliff chart, awards table with CSV, agency breakdown
- [x] Action Dashboard — cross-agency YTD money movement, missed opportunities, lapsed capacity
- [x] Data Dictionary — agency abbreviations, field definitions, planned agencies, peer sets
- [x] PDF export — full-page report with tables + embedded bar chart, heatmap, Sankey (kaleido + fpdf2)
- [x] Upsert logic: fiscal_year never overwritten, awd_amount takes MAX
- [x] Crash-safe .done sentinel system for downloads
- [x] Daily refresh scheduler (NSF + NIH) deployed on Railway

### What's Next (in order)
1. **Data governance footer** — freshness bar + disclaimer on every page
2. **Grants.gov opportunity feed** — forward-looking alerts (the "radar" part)
3. **DHS full load (FY2020-2026)** — overnight job for slow-download agency
4. **Trend/history view** — FY-by-FY chart for a single program × institution

### Streamlit App
- Run with: `streamlit run app/Home.py` (from the `app/` directory)
- 5 pages via Streamlit multipage: Home (gap analysis), Portfolio Risk, Expiring Awards, Action Dashboard, Data Dictionary
- Home: agency/program selector → scorecard → gap table → bar chart → heatmap → Sankey → PDF export
- Portfolio Risk: agency concentration donut → what-if cut scenario → peer HHI table → agency trend
- Expiring Awards: scorecard → quarterly cliff chart → sortable awards table (CSV) → agency breakdown
- Action Dashboard: cross-agency YTD bar chart → UNT comparison table → missed opportunities → lapsed capacity
- Data Dictionary: agency abbreviations, field definitions, planned agencies, peer sets
- Peers always visible — gap analysis is the primary interaction

### Critical Gotchas
- **NIH `awd_amount`** = total project value (post-dedup sum of annual budgets) — comparable to NSF/USASpending
- **ED `awd_amount`** — raw DB has $126.9B but 89% is non-research (HEERF/CARES $73B + formula grants $40B). All queries exclude 35 non-research CFDA codes via `_ed_exclusion_clause()` → $13.8B research-only. Raw data preserved.
- **USASpending**: always use `total_obligated_amount`, never sum `federal_action_obligation`
- **HHS bulk download** excludes NIH (filtered by `awarding_sub_agency_name`) to avoid double-counting
- **`fiscal_year`** = federal FY (Oct 1 – Sep 30); Oct 2022 action → FY2023
- **Load order**: years loaded ascending so earliest transaction sets `fiscal_year` correctly
- **Pivot on `program_abbr`** not `program` — long names vary slightly between institutions in raw_json

---

## 1. What Is Federal Radar

Federal Radar is an internal grants intelligence tool for university research offices
(VPR/AVP-Research). It aggregates federal award data from multiple agencies into a single
searchable database, allowing research administrators to:

- Answer: "For a given agency/program, where are peers beating us, and by how much?"
- Benchmark peer institutions (Texas peers + national peers) side by side
- Rank programs by opportunity size — dollar gap between UNT and peer average
- Identify active vs. dormant programs (Field Total + Last Funded context)
- Eventually: surface new funding opportunities before deadlines pass (the "radar" part)

**Primary user:** VPR/AVP-Research staff. Not public-facing. The data integrity bar is
extremely high — wrong data undermines institutional trust immediately.

---

## 2. Architecture Overview

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
    ├── awards table (unified, all sources, 423K rows)
    └── institutions table (UEI reference, 19,433 rows)
    │
    ▼
Streamlit App (app/Home.py)
    │
    └── queries.py (cached queries, peer config)
```

**Deployment:** Railway. Scheduler runs daily NSF + NIH refresh via APScheduler.

---

## 3. Database Design Decisions

### 3.1 Single unified `awards` table

**Decision:** One table for all agencies (NSF, NIH, DOE, DOD, NASA, USDA, EPA, Commerce, DHS).

**Why:** VPR offices need cross-agency queries — "show all awards to UNT regardless of
agency." A single table with a `source` discriminator column makes this trivial. Separate
tables per agency would require UNIONs everywhere.

**Trade-off accepted:** Some fields are agency-specific and will be NULL for other sources
(e.g., `activity_code`, `nih_institute` are NIH-only; `dir_abbr` means NSF directorate
for NSF records but NIH institute abbreviation for NIH records). Acceptable for MVP.

### 3.2 `awd_id` as primary key — one record per base award

**Decision:** `awd_id` = the base award identifier. One row per award, not per transaction.

**Why:** Federal awards are multi-year. A $3M DOE grant awarded in 2023 will have annual
transactions in 2024, 2025, 2026. These are all the same grant. Storing one row per
transaction inflates counts and confuses users.

**The USASpending ID problem:** USASpending has two ID fields:
- `assistance_transaction_unique_key` — unique per transaction (changes every year)
- `assistance_award_unique_key` — stable base award ID across all transactions

We use `assistance_award_unique_key` as `awd_id`. Later transactions update the existing
record rather than creating duplicates.

### 3.3 `fiscal_year` = year the grant was originally awarded (never overwritten)

**Decision:** On upsert conflict, `fiscal_year` is never updated — the first insert wins.

**Why:** A grant awarded in FY2023 that has a $0 revision in FY2026 should still appear
under FY2023. The fiscal year tells users "when was this grant born," not "when was the
last paperwork filed." Implementation: `ON CONFLICT DO UPDATE SET fiscal_year = awards.fiscal_year`.

**Load order matters:** Years loaded ascending (FY2019 → FY2026) so the earliest
transaction (action_type=A, NEW) is always inserted first.

### 3.4 `awd_amount` = latest total obligated (takes MAX on conflict)

**Decision:** On upsert conflict, `awd_amount = MAX(incoming, stored)`.

**Why:** `total_obligated_amount` in USASpending is a running cumulative total — it only
grows over time. The latest transaction always has the most accurate total.

| Source | `awd_amount` meaning |
|---|---|
| NSF | Total award for the entire grant lifespan |
| NIH | Sum of all annual budget periods = total project value (post-dedup) |
| USASpending | Cumulative total obligated to date |

### 3.5 `inst_uei` and `inst_canonical_name` columns (added post-MVP)

**Decision:** Added two new columns to `awards`: `inst_uei TEXT` and `inst_canonical_name TEXT`.

**Why:** Institution names vary significantly across sources and even within the same source.
"University of North Texas", "UNIVERSITY OF NORTH TEXAS", "U NORTH TEXAS" are the same
institution. UEI (Unique Entity Identifier) is the SAM.gov-assigned stable ID — the only
reliable cross-source deduplication key. See Section 9 for full UEI pipeline details.

---

## 4. Data Source Decisions

### 4.1 Why USASpending bulk download (not the search API)

**Decision:** Use `/api/v2/bulk_download/awards/`, not `/api/v2/search/spending_by_award/`.

**Why:** Bulk download returns a complete ZIP — one job, all data. The search API is
paginated (100/page), rate-limited, and would require thousands of calls for 8 years × 7 agencies.

### 4.2 Why parallel downloads for USASpending

**Decision:** `ThreadPoolExecutor` to download all agencies simultaneously per fiscal year.

**Why:** Each agency download is independent. Parallel cuts wall-clock time from ~40 min
to ~8 min for a full year. USASpending handles concurrent jobs fine.

### 4.3 Why DHS is skipped for MVP

**Decision:** DHS excluded from initial data load (FY2019 only exists).

**Why:** DHS bulk downloads consistently take 20+ minutes on USASpending's server vs. 1–4
minutes for other agencies. Deferred to overnight job post-MVP.

### 4.4 Raw files saved alongside JSONL

**Decision:** Each download saves `.zip` (raw), `.csv` (full extract), `.jsonl` (filtered).

**Why:** Disk is cheap. Reprocessing is expensive. The `.done` sentinel ensures only
complete files are loaded. This principle was validated during UEI enrichment — all UEIs
were already in `raw_json`, no re-download needed.

### 4.5 University filtering

**Decision:** Filter to university recipients using `business_types_code`: H, 11, 12, 13
plus name-pattern fallback.

**Why:** Federal agencies award to companies, nonprofits, governments, individuals.
Non-university records are noise for a VPR tool.

---

## 5. Amount Field Clarification (Critical for Accuracy)

### USASpending
- `federal_action_obligation` — delta for this transaction (UNRELIABLE: bulk download sometimes omits intermediate transactions)
- `total_obligated_amount` — cumulative running total (RELIABLE)

**We use `total_obligated_amount`.** Never sum `federal_action_obligation`.

### NIH RePORTER
- `award_amount` — budget for specific budget period (1 year), NOT total multi-year value
- Post-deduplication: `awd_amount` = sum of all budget periods = true total project value

### NSF
- `awd_amount` — total award across full grant period. Clean, directly comparable to USASpending.

---

## 6. NIH Deduplication (Completed)

NIH assigns a new `project_num` every year for the same ongoing grant:
- `1R01CA123456-01` = year 1 (prefix `1` = new award)
- `5R01CA123456-02` = year 2 (prefix `5` = continuation)

**Problem:** Multiple rows per grant inflated counts and made NIH `awd_amount` (per-year
budget) incomparable with NSF/USASpending (total award).

**Fix (`scripts/nih_deduplicate.py`):**
- Groups all NIH rows by `core_project_num` from `raw_json`
- Canonical record = earliest `fiscal_year` (awd_id tiebreaker favours `1Rxx` prefix)
- `awd_amount` = SUM of all annual budget slices = true total project value
- Result: 453,631 rows → 156,439 unique projects (65.5% reduction)
- Total funding preserved: $223.135B before and after (validated)

---

## 7. Fiscal Year Definition

Federal fiscal year runs October 1 through September 30.
- FY2023 = October 1, 2022 through September 30, 2023

All sources use this definition. USASpending provides `action_date_fiscal_year` directly.
NSF provides `obligation_date` which we convert using the Oct 1 rule.

---

## 8. Geographic Data Availability

`inst_state_code` (2-letter USPS code) is mapped for every source and is 99%+ populated.
Richer geo fields are preserved in `raw_json` but not yet extracted.

| Source | `inst_state_code` | City | ZIP | Lat/Lon |
|---|---|---|---|---|
| USASpending | 100% | `recipient_city_name` | `recipient_zip_code` | No |
| NIH | 99.3% | No | No | **Yes — `geo_lat_lon`** |
| NSF | 99.9% | `inst.inst_city` | No | No |

When building map features, extract from `raw_json` via migration script — do not re-download.

---

## 9. UEI Enrichment Pipeline (Completed)

### 9.1 Why UEI

**Problem:** Institution names are inconsistent across 12 sources. "University of North Texas",
"UNIVERSITY OF NORTH TEXAS", and "U North Texas" are the same institution. Raw string matching
produces false mismatches and inflated institution counts.

**Solution:** UEI (Unique Entity Identifier) — a 12-character SAM.gov-assigned ID stable
across all federal award systems. Every award recipient that receives federal funding has one.
Used as the universal deduplication key across all sources.

### 9.2 Raw JSON First Principle

**Key lesson:** All three source types already have UEI in their `raw_json`. No external API
calls needed for enrichment.

| Source | JSON path | Coverage |
|---|---|---|
| NSF | `$.inst.org_uei_num` | 99.9% |
| NIH | `$.organization.primary_uei` | 99.98% (after raw_json extraction) |
| USASpending | `$.recipient_uei` | 100% (direct CSV field) |

**Lesson applied:** Always check raw files before calling external APIs. The NIH enrichment
initially attempted API lookups, but 37,575 of 37,609 missing UEIs were already in `raw_json`.

### 9.3 Four-Phase Pipeline

**Phase 1 — USASpending UEI extraction (`phase1_usaspending_uei.py`)**
- Extracted `recipient_uei` from raw_json for all USASpending sources
- ~170K records updated

**Phase 2 — Institutions table (`phase2_build_institutions_table.py`)**
- Built reference table from all records with UEIs
- One row per UEI, canonical_name = most frequent inst_name per UEI (window function)

**Phase 3a — NSF UEI extraction (`phase3a_nsf_uei_extract.py`)**
- Extracted `$.inst.org_uei_num` from NSF raw_json
- ~83K records updated

**Phase 3b — NIH UEI enrichment (`phase3b_nih_uei_enrich.py`)**
- Step 1: Extracted `$.organization.primary_uei` from NIH raw_json → 37,575 records
- Step 2: Cross-matched 785 NIH institution names against institutions table (UPPER join)
- Step 3: NIH API lookups for 369 remaining unmatched institutions
- Total coverage: 99.98% (up from 76%)
- **Lesson:** Test with 100 records first. The UPPER() join without an index caused full
  table scans (147s for 785 queries × 156K rows). Identified before full run.

**Phase 4 — Canonical names (`scripts/phase4_canonical_names.py`)**
- Rebuilt `institutions` table (DROP + CREATE): 19,433 rows
- Applied 25 peer flags (see Section 10)
- Set `canonical_name = peer_label` for all peer institutions (override most-frequent name)
- `UPDATE awards SET inst_canonical_name = (SELECT canonical_name FROM institutions WHERE inst_uei = awards.inst_uei)` — 409,009 records in 547s

### 9.4 UNT Dual-UEI Situation

UNT has two UEIs in the data:
- `G47WN1XZNWX9` — primary (parent entity, SAM.gov main record)
- `JSV3KA8HHBB5` — secondary (NIH's historical UEI for UNT)

**How identified:** `raw_json → parent_uei = G47WN1XZNWX9` on NIH records confirms G47 is
the parent entity. Zero overlapping `awd_id` values between the two UEIs — no double counting.

**Resolution:** Both UEIs get `canonical_name = "University of North Texas"` via peer_label
override. The app queries `inst_canonical_name = 'University of North Texas'` which picks
up both UEIs transparently.

---

## 10. Institutions Table Design

```sql
CREATE TABLE institutions (
    inst_uei            TEXT PRIMARY KEY,
    canonical_name      TEXT NOT NULL,
    inst_state_code     TEXT,
    uei_source          TEXT DEFAULT 'awards',
    is_my_institution   INTEGER DEFAULT 0,
    is_peer_texas       INTEGER DEFAULT 0,
    is_peer_national    INTEGER DEFAULT 0,
    peer_label          TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

**Canonical name strategy:** Most frequent `inst_name` per UEI wins (via `ROW_NUMBER()
OVER PARTITION BY inst_uei ORDER BY COUNT(*) DESC`). Exception: peer institutions use
`peer_label` as canonical_name for consistent display regardless of how frequently their
name appears in the awards data.

### Peer Configuration (as of 2026-05-28)

**Texas peers (is_peer_texas = 1):**
Texas A&M University, UT Austin (2 UEIs), UT Arlington, UT Dallas, UTSA, UTEP, UTRGV,
Texas State University, Texas Tech University, University of Houston (2 UEIs)

**National peers (is_peer_national = 1):**
Arizona State University, Purdue University, Georgia State University (2 UEIs),
University of South Florida, UCF, University of Utah, University of Memphis,
University of Illinois Chicago, Tulane University, UC Riverside

**My institution (is_my_institution = 1):**
University of North Texas (2 UEIs: G47WN1XZNWX9, JSV3KA8HHBB5)

**How to add/change peers:** Edit `PEER_FLAGS` in `scripts/phase4_canonical_names.py`
and re-run the script. It rebuilds the institutions table safely from scratch.

---

## 11. Query Architecture Changes

### 11.1 Old approach (broken for multi-source)

```sql
WHERE UPPER(inst_name) = UPPER('University of North Texas')
```

**Problem:** UPPER() comparison is case-insensitive but still fails on name variants
("UNIVERSITY OF NORTH TEXAS" ≠ "U North Texas"). Also has no index — full table scan
on every query.

### 11.2 New approach

```sql
WHERE inst_canonical_name = 'University of North Texas'
```

**Why:** Exact match on an indexed column. `inst_canonical_name` is already normalized —
populated from the `institutions` table via UEI join. All name variants for the same
institution map to one consistent string.

**Index:** `idx_awards_inst_uei` on `inst_uei`, `idx_awards_canonical_name` on
`inst_canonical_name`.

### 11.3 `get_my_ueis()` vs. institution name

Queries use `inst_canonical_name = MY_INSTITUTION` (string constant defined in
`queries.py`). For UNT this correctly picks up both UEIs because both map to the
same canonical_name.

---

## 12. Streamlit App Design Decisions

### 12.1 Product framing

**Primary question the app answers:**
> "In [agency/program], where are peers beating us, and by how much?"

**Primary user:** VPR/AVP-Research staff reviewing competitive positioning, not individual PIs.

**Use case that drove the redesign:** VPR was looking at NSF BIO/IOS awards, saw a peer
institution had won 8 awards to UNT's 4, and needed to understand the gap and its dollar value.
The old multi-page explorer was too noisy — users had to navigate away from peers to get context.

### 12.2 Single-page design

**Decision:** One page, scroll down. Dropped the Institution Breakdown page.

**Why:** The VPR needs to see the competitive gap immediately. Separate pages for "my
institution" and "peers" force navigation that breaks the mental model. The gap IS the insight.

**What's on the page:**
1. Sidebar: agency → directorate/division → peer set → FY range
2. Scorecard (4 metrics): UNT Awards, UNT Funding, Rank Among Peers, Programs with Gaps
3. Headline sentence: auto-generated, names the biggest gap and its dollar value
4. Program Breakdown table (all programs, sorted by Opportunity desc)
5. Total Funding by Institution bar chart (horizontal, UNT in red)

### 12.3 Gap table design

**Decision:** Show ALL programs (gaps at top sorted by Opportunity, competitive programs green at bottom).

**Why:** Early version only showed programs where UNT was behind. This caused confusion
when the scorecard showed "4 awards" but the table appeared empty — the 4 awards were
in programs where UNT was competitive. Showing all programs with green highlighting for
competitive ones is more honest.

**Columns:**
- Program (full name, capped 45 chars)
- UNT (award count, color-coded)
- Top 7 peers by total awards (short names, award counts)
- Peer Avg (average award count across all peers)
- Opportunity ($M) = peer_avg_funding - unt_funding (negative = UNT leading)
- Field Total (all institutions nationally, not just peers)
- Last Funded (max fiscal year in field — distinguishes active from dormant programs)

### 12.4 UNT column color coding

| Condition | Color | Meaning |
|---|---|---|
| Opportunity ≤ 0 | Green | UNT at or above peer average |
| UNT = 0 | Dark red | UNT has no awards in this program |
| UNT / PeerAvg < 0.40 | Red | Significantly behind |
| UNT / PeerAvg < 0.75 | Orange | Within reach |
| UNT / PeerAvg ≥ 0.75 | Green | Competitive |

### 12.5 Field Total and Last Funded columns

**Why added:** A program with 4 field-wide awards last funded in 2020 is very different
from one with 4 field-wide awards last funded in 2025. Without this context, VPR might
prioritize dead programs. These columns let the user distinguish:
- "This is a dormant program — don't bother" vs.
- "This is a small but active program — real opportunity"

### 12.6 NSF full names (not abbreviations)

**Decision:** Display full names everywhere. Abbreviations (BIO, IOS, MPS) are internal
NSF codes, not meaningful to VPR.

**Implementation:**
- `NSF_DIR_NAMES` dict in `queries.py`: `{"BIO": "Biological Sciences", ...}` (14 entries)
- `NSF_DIV_NAMES` dict: `{"IOS": "Integrative Organismal Systems", ...}` (30+ entries)
- Sidebar uses `format_func` to display "BIO — Biological Sciences" in dropdowns
- `get_raw_comparison()` extracts `org_dir_long_name` / `org_div_long_name` from `raw_json`
  for full names in the gap table

### 12.7 Pivot on `program_abbr`, not `program`

**Critical bug and fix:**

Early version pivoted on the full program name (`org_dir_long_name`). This caused UNT
rows to appear in different pivot rows than peer rows because long names vary slightly
between institutions in raw_json (e.g., trailing spaces, minor capitalization differences).

**Fix:** Always pivot on `program_abbr` (abbreviation — always consistent across institutions).
Build `abbr_to_name` dict from the data after the fact for display purposes only.

```python
# In get_raw_comparison(), GROUP BY prog_col (abbreviation)
# SELECT long name separately — take any one, they're ~equivalent
abbr_to_name = (
    df_raw[["program_abbr", "program"]]
    .drop_duplicates("program_abbr")
    .set_index("program_abbr")["program"]
    .to_dict()
)
```

### 12.8 PEER_SHORT mapping

`PEER_SHORT` in `queries.py` maps full canonical institution names to short display names
for table columns and chart labels. Example: `"Texas A&M University": "TAMU"`. Without
this, column headers overflow the table width.

---

## 13. Portfolio Risk & Expiring Awards Pages (Added 2026-05-29)

### 13.1 Portfolio Risk (`app/pages/1_Portfolio_Risk.py`)

**Question it answers:** "How exposed are we if an agency gets cut?"

**Audience:** Provost/board meetings — strategic planning.

**Components:**
1. **Donut chart** — UNT funding by agency with percentages. Red warning if any single agency > 50%.
2. **What-If Scenario** — Pick agency + cut percentage (10–50%). Shows before/after funding impact. Simple math on the donut data, no new query.
3. **Peer Diversification Table** — Institution | Top Agency | Top Agency % | # Agencies | HHI. Sorted by concentration (most at-risk first). UNT row highlighted yellow.
4. **Agency Trend** — Grouped bar chart showing UNT's funding by FY per agency.

**New queries:**
- `get_portfolio_by_agency(inst_name, fy_start, fy_end)` — GROUP BY source for one institution
- `get_portfolio_trend(inst_name, fy_start, fy_end)` — GROUP BY fiscal_year, source
- `get_peer_diversification(inst_names, fy_start, fy_end)` — HHI + top agency share per institution

### 13.2 Expiring Awards (`app/pages/2_Expiring_Awards.py`)

**Question it answers:** "What funding are we about to lose?"

**Audience:** Operational — drives action this week (PI outreach, renewal planning).

**Components:**
1. **Scorecard** — Awards expiring | Funding at risk ($M) | Largest expiration | PIs affected
2. **Funding Cliff Chart** — Stacked bar by quarter showing how much expires when, colored by agency.
3. **Expiring Awards Table** — End Date | PI | Agency | Program | Amount | Title. Sorted by end date. CSV download.
4. **Agency Breakdown** — Horizontal bar: which agencies have the most expiring funding.

**New queries:**
- `get_expiring_awards(inst_name, horizon_date, agency)` — awards where project_end_date BETWEEN today AND horizon
- `get_expiring_summary(inst_name, horizon_date, agency)` — aggregate stats for scorecard

**Data notes:**
- 99% of awards have `project_end_date` (406K of 410K)
- PI names available for NSF/NIH only; shows "—" for others
- UNT has ~200 awards with end dates from 2025 onward

---

## 14. PDF Export (`app/pdf_export.py`) — Added 2026-05-29

### Why

The app is hosted locally and cannot be shared as a URL. VPR/AVP users need to send analysis to leadership (provost, board, deans) as a standalone document. The PDF export bridges that gap until the app is hosted online.

### Implementation

**Dependencies:**
- `fpdf2>=2.8` — pure Python PDF layout engine, no system dependencies, latin-1 font safe
- `kaleido>=0.2` — Plotly's PNG export engine; renders any Plotly figure to bytes

**How it works:**
1. `generate_gap_report()` in `pdf_export.py` accepts all pre-computed data from `Home.py`
2. Tables (scorecard, gap breakdown, peer funding, PI list) are drawn with `fpdf2` cells
3. Charts are passed as `(title, png_bytes)` tuples — each rendered via `kaleido` in `Home.py`
4. Each chart gets its own page with a section header
5. Returns `bytes` — passed directly to `st.download_button(mime="application/pdf")`

**PDF contents (in order):**
1. Title block: scope label, FY range, peer set, institution
2. 4-metric scorecard
3. Biggest gap headline sentence
4. Program breakdown table — Opportunity colored red (gap) / green (leading)
5. Peer funding comparison — UNT row highlighted yellow
6. UNT PI breakdown (NSF and NIH scopes only)
7. Bar chart page — Total Funding by Institution
8. Heatmap page — Program Activity Over Time
9. Sankey page — Funding Flow: Programs to Institutions

**Filename convention:** `federal_radar_{SCOPE}_{FY_START}-{FY_END}.pdf`
Example: `federal_radar_NSF_BIO_IOS_2022-2025.pdf`

**Placement:** "Export PDF Report" (primary blue button) sits at the bottom of `Home.py` after all charts are rendered — ensures all three figures are available when the button is clicked.

**Latin-1 safety:** Helvetica is the PDF core font and is latin-1 only. A `_safe()` function in `pdf_export.py` replaces em dashes, smart quotes, and other non-latin-1 characters before passing any string to fpdf2. Arrow trend indicators (↑↓→) are converted to "Growing" / "Declining" / "Flat".

**Chart height scaling:**
- Bar chart: `max(400, 32 × n_institutions)` px
- Heatmap: `max(600, 32 × n_programs)` px — scales with number of program rows
- Sankey: `max(600, 28 × n_programs + 200)` px

**Graceful degradation:** Each `_to_png()` call in `Home.py` is wrapped in try/except. If kaleido fails for any chart, that chart is silently omitted from the PDF — tables are always included.

### Usage

Select any filter combination (agency, directorate, division, FY range, peer set), scroll to the bottom of the Home page, click **Export PDF Report**. The PDF reflects exactly the current filter state and whatever metric is selected in the heatmap/Sankey radio buttons.

---

## 15. What Was Dropped

| Item | Reason |
|---|---|
| `pages/2_Institution_Breakdown.py` | Single-page design decision — VPR needs gap analysis, not institution explorer. Can be rebuilt later as a drill-down from the gap table. |
| UPPER(inst_name) queries | Replaced by inst_canonical_name. Fragile, no index, name variants break it. |
| Separate peer set tables | Handled via `is_peer_texas` / `is_peer_national` flags on institutions table. No separate tables needed. |
| Per-record NIH API UEI lookups | 99.9% of needed UEIs already in raw_json. API lookups only needed for 369 edge cases. |

---

## 16. Performance Rules and Lessons

1. **Batch everything.** Never insert/update one record at a time. Use `executemany` with batches of 500–1000.
2. **Indexes before bulk updates.** A `WHERE UPPER(inst_name) = UPPER(?)` on 156K rows without an index = 147s for 785 queries. With index = seconds.
3. **Test with 100 records first.** Before running any bulk operation, verify the logic on a small sample.
4. **Raw files first.** Before calling any external API, check if the data is already in `raw_json`. It usually is.
5. **Set-based SQL, not Python loops.** A single `UPDATE ... WHERE inst_uei IN (...)` is always faster than looping in Python.
6. **Estimate before running.** For any operation touching >10K rows, state estimated runtime before starting.

---

## 17. Database Indexes

All created idempotently via `init_db()` in `src/db.py`.

| Index | Columns | Purpose |
|---|---|---|
| `idx_awards_source` | `source` | Filter by data source |
| `idx_awards_fiscal_year` | `fiscal_year` | Filter by year |
| `idx_awards_source_fy` | `source, fiscal_year` | Agency + year (most common filter) |
| `idx_awards_source_inst` | `source, inst_name` | "All NIH awards to [institution]" |
| `idx_awards_inst_name` | `inst_name` | Institution search |
| `idx_awards_inst_fy` | `inst_name, fiscal_year` | Institution funding trend |
| `idx_awards_inst_state` | `inst_state_code` | Filter by state |
| `idx_awards_agcy_id` | `agcy_id` | Filter by agency ID |
| `idx_awards_opportunity_num` | `opportunity_number` | CFDA program queries |
| `idx_awards_obligation_date` | `obligation_date` | Date range queries |
| `idx_awards_activity_code` | `activity_code` | NIH activity code filter |
| `idx_awards_nih_institute` | `nih_institute` | NIH institute filter |
| `idx_awards_inst_uei` | `inst_uei` | UEI-based institution lookup |
| `idx_awards_canonical_name` | `inst_canonical_name` | Canonical name queries (replaces UPPER join) |
| `idx_inst_uei` | `institutions.inst_uei` | PK on institutions table |
| `idx_inst_canonical` | `institutions.canonical_name` | Institution name search |
| `idx_inst_state` | `institutions.inst_state_code` | State filter on institutions |

---

## 18. File Structure

```
Federal Radar/
├── data/
│   ├── federal_awards.db              SQLite, WAL mode, ~2GB
│   └── raw/
│       ├── nsf/                       NSF bulk ZIPs (2016–2026)
│       └── usaspending/
│           ├── 2019/                  {AGENCY}_FY{YEAR}.{zip,csv,jsonl,done}
│           └── ...
├── app/
│   ├── Home.py                        Streamlit — competitive gap analysis
│   ├── pages/
│   │   ├── 1_Portfolio_Risk.py        Agency concentration, what-if, peer HHI
│   │   ├── 2_Expiring_Awards.py       Funding cliff, expiring awards table
│   │   ├── 3_Action_Dashboard.py      Cross-agency YTD, missed opportunities, lapsed
│   │   └── 4_Data_Dictionary.py       Agency abbreviations, field defs, peer sets
│   ├── pdf_export.py                  PDF report generator (fpdf2 + kaleido)
│   └── queries.py                     All DB queries, peer config, constants
├── scripts/
│   ├── nsf_etl.py                     NSF bulk ZIP loader
│   ├── nsf_api_fetcher.py             NSF incremental API sync
│   ├── nih_api_fetcher.py             NIH RePORTER API fetcher
│   ├── nih_deduplicate.py             NIH deduplication
│   ├── usaspending_api_fetcher.py     USASpending bulk download + load
│   ├── phase1_usaspending_uei.py      Phase 1: extract UEIs from USASpending raw_json
│   ├── phase2_build_institutions_table.py  Phase 2: build institutions reference table
│   ├── phase3a_nsf_uei_extract.py     Phase 3a: extract UEIs from NSF raw_json
│   ├── phase3b_nih_uei_enrich.py      Phase 3b: NIH UEI enrichment (raw_json + API)
│   └── phase4_canonical_names.py      Phase 4: rebuild institutions + canonical names
├── src/
│   └── db.py                          Schema, upsert logic, indexes
├── tests/
│   ├── test_data_governance.py        Governance test suite
│   └── baselines.json                 Expected counts/totals
├── scheduler.py                       APScheduler daily refresh (NSF + NIH)
├── railway.toml                       Railway deployment config
├── CONTEXT.md                         This file
└── README.md                          Setup and quick-start guide
```

---

## 19. What Is NOT in the DB (Known Gaps)

| Gap | Reason | Plan |
|---|---|---|
| DHS FY2020–2026 | Slow download (~20+ min/year); only 159 records (FY2019) loaded | Overnight job |
| Grant opportunities (solicitations) | Different data type entirely | Grants.gov API, Phase 2 |
| Subaward data | Not in bulk download | Future |
| Private foundation grants | Not in federal systems | Phase 3 |

**Resolved gaps:**
- ~~HHS (non-NIH)~~ — Loaded 2026-06-04: 12,248 records, $37.6B
- ~~ED non-research inflation~~ — 35 CFDA codes excluded at query time (2026-06-04)

---

## 20. Future Features

| Feature | Current State | Target | Notes |
|---|---|---|---|
| High-quality PDF export | fpdf2 + kaleido (PNG raster, slow) | WeasyPrint + SVG vector charts | Eliminates headless Chromium dependency, vector = infinite zoom, faster render. HTML templating replaces cell-by-cell layout. Plotly `.to_image(format="svg")` for charts. |
