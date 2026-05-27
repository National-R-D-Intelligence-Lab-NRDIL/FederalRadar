# Federal Radar — Technical Context & Decision Log

**Last updated:** 2026-05-27
**Purpose:** Single source of truth for every significant technical decision made during
development. Anyone picking up this project — new developer, stakeholder, or future self —
should be able to read this and understand not just what we built, but why.

---

## 0. Quick Context (Read This First)

> **For Claude or any new session:** Read this section before anything else. It tells you exactly where the project stands and what to do next without reading the full file.

### What This Is
Federal Radar is a grants intelligence tool for university research offices (VPR/VPRI). It pulls federal award data from multiple agencies into a single SQLite database so research administrators can track funding trends, benchmark institutions, and eventually get forward-looking opportunity alerts.

### Tech Stack
- **Language:** Python 3.11
- **Database:** SQLite (`data/federal_awards.db`, WAL mode, ~2GB)
- **Deployment:** Railway (APScheduler daily refresh)
- **No API or UI yet** — DB is queried directly

### Current DB State (as of 2026-05-27)
410,797 records · $503.17B · FY2019–2026 · 12 sources

| Source | Records | Funding | Complete? |
|--------|---------|---------|-----------|
| NIH | 156,439 | $223.1B | Yes (deduplicated) |
| NSF | 83,845 | $50.0B | Yes |
| ED | 74,901 | $126.9B | Yes (includes formula/relief grants) |
| USDA | 27,276 | $18.4B | Yes |
| DOD | 26,408 | $31.7B | Yes |
| NASA | 17,424 | $10.6B | Yes |
| DOE | 10,395 | $24.4B | Yes |
| Commerce | 6,749 | $11.6B | Yes |
| DOT | 2,912 | $3.4B | Yes |
| NEH | 2,703 | $0.4B | Yes |
| EPA | 1,595 | $2.5B | Yes |
| DHS | 150 | $0.3B | FY2019 only — slow download |
| HHS (non-NIH) | — | — | Not loaded — slow download |

### Key Files
| File | Purpose |
|------|---------|
| `src/db.py` | Schema, upsert logic, indexes, SQLite pragmas |
| `scripts/usaspending_api_fetcher.py` | USASpending bulk download + load (ED, DOT, NEH, DOD, etc.) |
| `scripts/nih_api_fetcher.py` | NIH RePORTER API fetcher |
| `scripts/nih_deduplicate.py` | NIH deduplication (one row per project, sum of annual budgets) |
| `scripts/nsf_etl.py` | NSF bulk ZIP loader |
| `scripts/nsf_api_fetcher.py` | NSF incremental daily sync |
| `scheduler.py` | APScheduler — daily NSF + NIH refresh on Railway |
| `data/raw/usaspending/` | Raw ZIPs, CSVs, JOSONLs, .done sentinels by year/agency |

### What's Done
- [x] Data pipeline: NSF, NIH, DOD, USDA, NASA, DOE, Commerce, EPA, ED, DOT, NEH
- [x] NIH deduplication (453K → 156K rows, funding preserved)
- [x] Upsert logic: fiscal_year never overwritten, awd_amount takes MAX
- [x] Crash-safe .done sentinel system for downloads
- [x] 12 DB indexes covering all common VPR query patterns
- [x] Daily refresh scheduler (NSF + NIH) deployed on Railway

### What's Next (in order)
1. **REST API** — FastAPI, search by institution / agency / FY / keyword
2. **Internal dashboard** — table view, filters, export to CSV
3. **Grants.gov opportunity feed** — forward-looking alerts (the "radar" part)

### Post-MVP (deferred)
- **DHS FY2020–2026** — same pipeline, ~20+ min/year, run as overnight job
- **HHS (non-NIH) FY2020–2026** — same issue as DHS, overnight job

### Geographic Data (for future map feature)
- **State** (`inst_state_code`) — already mapped, 99%+ populated, index exists. Ready for choropleth today.
- **City + ZIP + County** — in `raw_json` for all USASpending sources. Needs extraction to new columns.
- **Lat/Lon** — NIH has exact coords in `raw_json → geo_lat_lon`. USASpending needs ZIP geocoding.
- See Section 8 for full details.

### Critical Gotchas
- **NIH `awd_amount`** = total project value (post-dedup sum of annual budgets) — comparable to NSF/USASpending
- **ED `awd_amount`** is large ($90B+ in 2020/2021) due to COVID CARES Act relief — not pure research
- **USASpending**: always use `total_obligated_amount`, never sum `federal_action_obligation` (transactions can be missing)
- **HHS bulk download** excludes NIH (filtered by `awarding_sub_agency_name`) to avoid double-counting
- **`fiscal_year`** = federal FY (Oct 1 – Sep 30); Oct 2022 action → FY2023
- **Load order**: years loaded ascending so earliest transaction sets `fiscal_year` correctly

---

## 1. What Is Federal Radar

Federal Radar is an internal grants intelligence tool for university research offices
(VPR/VPRI). It aggregates federal award data from multiple agencies into a single
searchable database, allowing research administrators to:

- Track what federal agencies are funding at their institution
- Benchmark funding trends over time
- Identify patterns in awards by agency, discipline, and fiscal year
- Eventually: surface new funding opportunities before deadlines pass (the "radar" part)

**Current phase:** Internal validation tool for a single VPR office. Not public-facing.
The data integrity bar is extremely high — wrong data undermines institutional trust
immediately. Accuracy before features.

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
    └── awards table (unified, all sources)
```

**No API layer yet.** The DB is queried directly. A REST API and UI are next-phase work.

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
for NSF records but NIH institute abbreviation for NIH records). This is acceptable for
an MVP.

### 3.2 `awd_id` as primary key — one record per base award

**Decision:** `awd_id` = the base award identifier. One row per award, not per transaction.

**Why:** Federal awards are multi-year. A $3M DOE grant awarded in 2023 will have annual
transactions (obligation, continuation, revision) in 2024, 2025, 2026. These are all the
same grant. Storing one row per transaction inflates counts and confuses users.

**The USASpending ID problem:** USASpending has two ID fields:
- `assistance_transaction_unique_key` — unique per transaction (changes every year)
- `assistance_award_unique_key` — stable base award ID across all transactions of a grant

We use `assistance_award_unique_key` as `awd_id`. This means later transactions update
the existing record rather than creating duplicates.

### 3.3 `fiscal_year` = year the grant was originally awarded (never overwritten)

**Decision:** On upsert conflict, `fiscal_year` is never updated — the first insert wins.

**Why:** A grant awarded in FY2023 that has a $0 administrative revision in FY2026 should
still appear under FY2023. The fiscal year tells users "when was this grant born," not
"when was the last paperwork filed." Overwriting `fiscal_year` would make old grants
appear as new ones, corrupting trend analysis.

**Implementation:** `ON CONFLICT DO UPDATE SET fiscal_year = awards.fiscal_year`
(keeping the stored value, ignoring the incoming value).

**Load order matters:** We load years in ascending order (FY2019 → FY2026). This ensures
the earliest transaction (typically action_type=A, NEW) is always inserted first, setting
the correct `fiscal_year`.

### 3.4 `awd_amount` = latest `total_obligated_amount` (takes the higher value)

**Decision:** On upsert conflict, `awd_amount = MAX(incoming, stored)`.

**Why:** `total_obligated_amount` in USASpending is a running cumulative total — it only
grows (or stays the same) over time. The latest transaction always has the most accurate
total. Using MAX ensures we never downgrade an amount due to out-of-order loading.

**What `awd_amount` means by source:**

| Source | `awd_amount` meaning |
|---|---|
| NSF | Total award for the entire grant lifespan |
| NIH | Budget period slice (one year's funding, NOT total) |
| USASpending | Cumulative total obligated to date |

**NSF and USASpending are comparable.** NIH is not — it's a per-year budget slice.
In the UI, NIH amounts should be labeled "Annual Budget" not "Total Award."
See FUTURE_FEATURES.txt for the NIH deduplication plan.

### 3.5 `fiscal_year` derivation

**Decision:** Use `action_date_fiscal_year` from the USASpending CSV directly. Fall back
to deriving from `period_of_performance_start_date` using the Oct 1 federal fiscal year
rule only if the direct field is missing.

**Why:** Early implementation derived FY from the performance start date. This was wrong
for grants where the start date falls in a different FY than the award action. USASpending
provides `action_date_fiscal_year` explicitly — always prefer the authoritative source.

---

## 4. Data Source Decisions

### 4.1 Why USASpending bulk download (not the USASpending search API)

**Decision:** Use the `/api/v2/bulk_download/awards/` endpoint, not
`/api/v2/search/spending_by_award/`.

**Why:**
- Bulk download returns a ZIP file with a complete CSV — one job, all data
- The search API is paginated (100 records/page), rate-limited, and would require
  thousands of API calls for 8 years × 7 agencies
- Bulk download is the recommended approach for large-volume historical data per
  USASpending's own documentation

**Trade-off:** Bulk download jobs can take time on USASpending's servers (especially DHS,
which takes 20+ minutes). Mitigated with parallel execution across agencies.

### 4.2 Why parallel downloads for USASpending

**Decision:** Use `ThreadPoolExecutor` to download all agencies simultaneously for a
given fiscal year.

**Why:** Each agency download is independent — submitting jobs in parallel cuts wall-clock
time from ~40 minutes to ~8 minutes for a full year run. USASpending's server handles
concurrent jobs fine.

### 4.3 Why DHS is skipped for MVP

**Decision:** DHS excluded from initial data load.

**Why:** DHS bulk download jobs consistently take 20+ minutes on USASpending's server
(vs. 1–4 minutes for other agencies). The root cause is data volume — DHS includes
a large number of non-university records that must be filtered server-side. One FY2019
DHS download was successfully retrieved (150 records, $0.32B) but the process is too
slow for automated multi-year runs. Deferred to a one-time overnight job post-MVP.

### 4.4 Why raw CSV is saved alongside JSONL

**Decision:** Each download saves three files: `.zip` (raw download), `.csv` (full raw
extracted), `.jsonl` (university-filtered, mapped records).

**Why:**
- `.zip` → audit trail, can re-process without re-downloading
- `.csv` → full agency data for any future analysis beyond universities
- `.jsonl` → pre-processed, ready to load into DB

Disk space is cheap. Reprocessing is expensive.

### 4.5 Crash-safe sentinel files (.done)

**Decision:** A `.done` file is written only after a JSONL file is fully processed and
verified. The loader skips files without a `.done` sentinel.

**Why:** If a download or extraction crashes mid-way, a partial JSONL could be loaded
into the DB, creating corrupt records. The sentinel ensures only complete, validated
files are ever loaded.

### 4.6 University filtering

**Decision:** Filter records to university/higher education recipients only using
`business_types_code` field values: H (Public/State Controlled IHE), 11, 12, 13
(private higher education variants), and a name-pattern fallback for records without
a business type code.

**Why:** Federal agencies award grants to companies, nonprofits, governments, and
individuals — not just universities. For a VPR tool, non-university records are noise.
Filtering at extraction time keeps the DB lean and queries fast.

---

## 5. Amount Field Clarification (Critical for Accuracy)

This was a significant discovery during development. The fields mean different things
across sources:

### USASpending
- `federal_action_obligation` — delta for this specific transaction only
  (UNRELIABLE: USASpending bulk download sometimes omits intermediate transactions,
  causing this field to not match what you'd expect)
- `total_obligated_amount` — cumulative running total across all transactions
  (RELIABLE: always accurate at the time of that transaction)

**We use `total_obligated_amount`.** Never attempt to sum `federal_action_obligation`
across transactions — missing transactions will cause understated totals.

### NIH RePORTER
- `award_amount` — the budget for the specific budget period (typically 1 year)
  This is NOT the total multi-year award value.
- `budget_start` / `budget_end` — confirm the budget period window

**Implication:** A 5-year R01 at $500K/year appears as 5 separate records in our DB,
each with `awd_amount = $500K`. Summing all NIH records for an institution over-counts
multi-year grants. This is a known limitation; NIH deduplication is a future feature.

### NSF
- `awd_amount` — total award across the full grant period
- One record per award, no annual transactions
- Clean and directly comparable to USASpending `total_obligated_amount`

---

## 6. NIH Deduplication (Completed)

NIH assigns a new `project_num` every year for the same ongoing grant:
- `1R01CA123456-01` = year 1 (prefix `1` = new award)
- `5R01CA123456-02` = year 2 (prefix `5` = continuation)
- `2R01CA123456-06` = renewal (prefix `2` = competing renewal)

**Problem:** Storing all years as separate rows inflated award counts and made
NIH `awd_amount` (a per-year budget slice) incomparable with NSF and USASpending
(which store total award values).

**Fix implemented in `scripts/nih_deduplicate.py`:**
- Groups all NIH rows by `core_project_num` from `raw_json`
- Canonical record = earliest `fiscal_year` (awd_id tiebreaker favours `1Rxx` new-award prefix)
- `awd_amount` = SUM of all annual budget slices = true total project value
- Non-canonical rows deleted
- Result: 453,631 rows → 156,439 unique projects (65.5% reduction)
- Total funding preserved: $223.135B before and after (validated)

**Why Python not SQL:** `json_extract()` on 453K rows without a column index requires
a full table scan with JSON parsing on every row. Doing it in SQL (GROUP BY + JOIN)
meant two full scans = prohibitively slow. The script instead streams rows once in
Python, builds the canonical map in memory O(n), then uses two indexed SQL operations
(executemany UPDATE on primary key + single DELETE via temp table).

**All three sources now consistently store total award value:**

| Source | `awd_amount` after fix |
|---|---|
| NSF | Total award, full lifespan (unchanged) |
| NIH | Sum of all annual budget periods = total project value |
| USASpending | Cumulative total obligated to date (unchanged) |

---

## 7. Fiscal Year Definition

Federal fiscal year runs October 1 through September 30.
- FY2023 = October 1, 2022 through September 30, 2023
- A grant with `action_date = 2022-11-15` is in FY2023

All sources use this definition. USASpending provides `action_date_fiscal_year` directly.
NSF provides `obligation_date` which we convert using the Oct 1 rule.

---

## 8. Geographic Data Availability

`inst_state_code` (2-letter USPS code) is mapped for every source and is 99%+ populated.
Richer geo fields are preserved in `raw_json` but not yet extracted to dedicated columns.

### Coverage summary

| Source | `inst_state_code` | City | ZIP | County | Lat/Lon |
|---|---|---|---|---|---|
| USASpending (ED, DOT, NEH, DOD, NASA, USDA, DOE, Commerce, EPA, DHS) | 100% | Yes — `recipient_city_name` | Yes — `recipient_zip_code` + `recipient_zip_last_4_code` | Yes — `recipient_county_name` + FIPS | No — ZIP geocoding needed |
| NIH | 99.3% | No | No | No | **Yes — `geo_lat_lon` `{lat, lon}`** |
| NSF | 99.9% | Yes — inside `inst` object | No | No | No |

### What's ready for a geographic chart today
- **State-level choropleth** — `inst_state_code` is already a mapped DB column with an index (`idx_awards_inst_state`). Works immediately, no changes needed.

### What would need extraction for richer maps
- **City-level map** — extract `recipient_city_name` (USASpending) and `inst.inst_city` (NSF) from `raw_json` into a new `inst_city` column.
- **Point map (lat/lon)** — NIH provides exact coordinates in `raw_json → geo_lat_lon`. USASpending sources would need ZIP-to-coordinates geocoding (ZIPs are available in `raw_json`).
- **County map** — extract `recipient_county_name` and `prime_award_transaction_recipient_county_fips_code` from `raw_json` (USASpending sources only).

### Implementation note
When building the map feature, extract geo fields via a migration script that reads `raw_json` and backfills new columns (`inst_city`, `inst_zip`, `inst_lat`, `inst_lon`). Do not re-download — all data is already in `raw_json`.

---

## 9. What Is NOT in the DB (Known Gaps)

| Gap | Reason | Plan |
|---|---|---|
| DHS FY2020–2026 | Slow download (~20+ min/year), deferred | Overnight job post-MVP |
| HHS (non-NIH) FY2020–2026 | Same slow download issue as DHS | Overnight job post-MVP |
| Grant opportunities (solicitations) | Different data type entirely | Grants.gov API, Phase 2 |
| Subaward data | Not in bulk download | Future |
| Private foundation grants | Not in federal systems | Phase 3 |
| Per-year disbursements | Not available in bulk download | Not planned |

---

## 10. Database Indexes

All indexes are created idempotently via `init_db()` in `src/db.py`.
SQLite connection pragmas set per-connection: `cache_size=-65536` (64MB), `temp_store=MEMORY`, `mmap_size=268435456` (256MB).

| Index | Columns | Purpose |
|---|---|---|
| `idx_awards_source` | `source` | Filter by data source |
| `idx_awards_fiscal_year` | `fiscal_year` | Filter by year |
| `idx_awards_source_fy` | `source, fiscal_year` | Agency + year (most common filter) |
| `idx_awards_source_inst` | `source, inst_name` | "All NIH awards to [institution]" |
| `idx_awards_inst_name` | `inst_name` | Institution search |
| `idx_awards_inst_fy` | `inst_name, fiscal_year` | Institution funding trend over time |
| `idx_awards_inst_state` | `inst_state_code` | Filter by state |
| `idx_awards_agcy_id` | `agcy_id` | Filter by agency ID |
| `idx_awards_opportunity_num` | `opportunity_number` | CFDA program queries |
| `idx_awards_obligation_date` | `obligation_date` | Date range queries |
| `idx_awards_activity_code` | `activity_code` | NIH activity code filter |
| `idx_awards_nih_institute` | `nih_institute` | NIH institute filter |

---

## 11. File Structure

```
Federal Radar/
├── data/
│   ├── federal_awards.db              SQLite, WAL mode, ~2GB
│   └── raw/
│       ├── nsf/                       NSF bulk ZIPs (2016–2026)
│       └── usaspending/
│           ├── 2019/                  {AGENCY}_FY{YEAR}.{zip,csv,jsonl,done}
│           ├── 2020/
│           ├── ...
│           └── 2026/
├── scripts/
│   ├── nsf_etl.py                     NSF bulk ZIP loader
│   ├── nsf_api_fetcher.py             NSF incremental API sync
│   ├── nih_api_fetcher.py             NIH RePORTER API fetcher
│   └── usaspending_api_fetcher.py     USASpending bulk download + load
├── src/
│   └── db.py                          Schema, upsert logic
├── tests/
│   ├── test_data_governance.py        Governance test suite (NSF-focused)
│   └── baselines.json                 Expected counts/totals
├── scheduler.py                       APScheduler daily refresh (NSF + NIH)
├── railway.toml                       Railway deployment config
├── FUTURE_FEATURES.txt                Deferred work log
└── CONTEXT.md                         This file
```

---

## 12. Current Database State (as of 2026-05-27)

NIH records reflect post-deduplication counts (one row per unique project).
HHS (non-NIH) downloaded for FY2019 and FY2023 only — full historical load pending (slow download, same issue as DHS).

| Source | Records | Total Funding | FY Range | Notes |
|---|---|---|---|---|
| NIH | 156,439 | $223.13B | FY2019–2026 | Deduplicated — one row per unique project |
| NSF | 83,845 | $49.95B | FY2019–2026 | |
| ED | 74,901 | $126.88B | FY2019–2026 | Includes formula/relief grants alongside research |
| USDA | 27,276 | $18.38B | FY2019–2026 | |
| DOD | 26,408 | $31.65B | FY2019–2026 | |
| NASA | 17,424 | $10.63B | FY2019–2026 | |
| DOE | 10,395 | $24.43B | FY2019–2026 | |
| Commerce | 6,749 | $11.55B | FY2019–2026 | |
| DOT | 2,912 | $3.37B | FY2019–2026 | |
| NEH | 2,703 | $0.42B | FY2019–2026 | |
| EPA | 1,595 | $2.46B | FY2019–2026 | |
| DHS | 150 | $0.32B | FY2019 only | Slow download deferred |
| HHS (non-NIH) | — | — | Not loaded | Downloaded FY2019+FY2023 only; full load pending |
| **TOTAL** | **410,797** | **$503.17B** | **FY2019–2026** | |
