# Federal Radar — Technical Context & Decision Log

**Last updated:** 2026-07-07
**Purpose:** Single source of truth for every significant technical decision. New developers, stakeholders, and future Claude sessions should read Section 0 first.

---

## 0. Quick Context (Read This First)

### What This Is
Federal Radar is a grants intelligence platform for university research offices (VPR/AVP-Research). It pulls federal award data from 13 agencies into a single SQLite database and surfaces competitive gap analysis — showing where peers are winning and by how much.

**Primary question it answers:** "In [agency/program], where are peers beating us and by how much?"

### Tech Stack
- **Language:** Python 3.11
- **Database:** SQLite (`data/federal_awards.db`, WAL mode, ~2GB)
- **UI:** Streamlit multipage app (`app/Home.py` + `app/pages/`)
- **Deployment:** Railway (APScheduler daily refresh)

### Current DB State (as of 2026-07-07)
424,097 awards · $541B · FY2019–2026 · 13 sources

| Source | Records | Funding | Notes |
|--------|---------|---------|-------|
| NIH | 156,908 | $223.5B | Deduplicated by core_project_num |
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

**Additional tables:**
- `institutions` — 19,433 rows, UEI-keyed, canonical names, peer flags
- `herd_institutions` — 1,108 rows, IPEDS research universities + freestanding health science
  centers mapped to awards UEIs (95.6% matched — see Section 3)
- `opportunities` — Grants.gov daily extract (posted + forecasted NOFOs)
- `opportunity_cfdas` — junction table linking opportunities to CFDA codes
- `refresh_log` — audit trail of every scheduled refresh run (source, status, records fetched/upserted, timestamps)

### Key Files
| File | Purpose |
|------|---------|
| `src/db.py` | Schema, upsert logic, indexes, pragmas |
| `app/queries.py` | All cached queries; peer config; institution picker; ED exclusion |
| `app/Home.py` | Competitive gap analysis (main page) |
| `app/pages/1_Portfolio_Risk.py` | Agency concentration, what-if, peer HHI |
| `app/pages/2_Expiring_Awards.py` | Funding cliff, expiring awards table |
| `app/pages/3_Action_Dashboard.py` | Cross-agency YTD, missed opportunities, lapsed capacity |
| `app/pages/4_Data_Dictionary.py` | Field definitions, peer sets, coverage stats |
| `app/pages/5_Open_Opportunities.py` | Grants.gov opportunity finder (peer gaps + UNT revisits) |
| `app/pdf_export.py` | PDF report generator (fpdf2 + kaleido) |
| `scripts/build_herd_crosswalk.py` | Build IPEDS → awards UEI crosswalk (run to regenerate) |
| `scripts/load_herd_crosswalk.py` | Load crosswalk CSV into herd_institutions table |
| `scripts/fetch_grantsgov.py` | Download daily Grants.gov XML extract → JSONL |
| `scripts/load_grantsgov.py` | Upsert Grants.gov JSONL into opportunities table |
| `scheduler.py` | APScheduler — daily NSF + NIH + USASpending refresh on Railway |

### What's Done
- [x] Data pipeline: 13 agencies, 424K records, FY2019–2026
- [x] NIH deduplication (453K → 156K rows, funding preserved at $223.1B)
- [x] ED non-research filter (35 CFDA codes excluded at query time)
- [x] UEI enrichment pipeline (all sources — extracted from raw_json)
- [x] Institutions reference table (19,433 rows, UEI key, canonical names, peer flags)
- [x] HERD institution crosswalk (1,108 IPEDS institutions incl. health science centers → awards UEIs, 95.6% match)
- [x] Institution picker queries (`get_herd_institutions`, `get_herd_states`, `get_institution_summary`)
- [x] Grants.gov daily pipeline (fetch → load → validate scripts)
- [x] Opportunities + opportunity_cfdas tables in DB schema
- [x] 5 Streamlit pages: Home, Portfolio Risk, Expiring Awards, Action Dashboard, Data Dictionary
- [x] Page 5: Open Opportunities (Grants.gov — peer gaps + UNT revisits)
- [x] PDF export (fpdf2 + kaleido — tables, bar, heatmap, Sankey) — currently disabled in UI
- [x] APScheduler daily refresh: NSF (08:00 UTC), NIH (08:05 UTC), USASpending — all 11
      non-NSF/NIH agencies via incremental Advanced Search API (08:10 UTC)
- [x] Ingestion validation UI (`get_recent_ingestion_activity`) — per-agency/per-day new-record
      counts on Home page, using `created_at` (true first-insert) not `updated_at`

### What's Next (in priority order)
1. **Any-institution benchmarking UI** — wire institution picker into app pages (UNT is currently hardcoded)
2. **Data governance footer** — freshness bar + disclaimer on every page
3. **APScheduler integration for Grants.gov** — daily refresh alongside NSF + NIH + USASpending
4. **DHS full load (FY2020–2026)** — overnight job for slow-download agency
5. **Trend/history view** — FY-by-FY chart for a single program × institution

### Critical Gotchas
- **NIH `awd_amount`** = total project value (post-dedup sum of annual budgets) — comparable to NSF/USASpending
- **ED funding** — raw DB has $126.9B but 89% is non-research. All queries exclude 35 CFDAs via `_ed_exclusion_clause()`. Raw preserved.
- **HHS bulk download** excludes NIH sub-agency to avoid double-counting
- **`fiscal_year`** = federal FY (Oct 1 – Sep 30); Oct 2022 action → FY2023
- **Pivot on `program_abbr`** not program — long names vary slightly between institutions in raw_json
- **UNT dual-UEI:** `G47WN1XZNWX9` (primary) + `JSV3KA8HHBB5` (NIH historical). Both map to canonical name "University of North Texas"
- **USASpending:** use `total_obligated_amount`, never sum `federal_action_obligation`
- **IPEDS UEI ≠ Awards UEI** — institutions often file awards under a different SAM.gov entity than their IPEDS registration (research foundations, system offices). The HERD crosswalk resolves this.
- **Health science centers are separate institutions, not sub-units.** UNT Health Science Center
  (`JE8AKPCR2KA4`) is a distinct research entity from University of North Texas main campus
  (`G47WN1XZNWX9` / `JSV3KA8HHBB5`), even though both fall under the "UNT System" umbrella.
  They are never merged in this tool — `is_my_institution` is only `1` for the main campus UEIs.
  This same logic applies to all Carnegie-25 institutions (UT Southwestern vs. UT Austin,
  Texas Tech HSC vs. Texas Tech, etc.) — see Section 3.

---

## 1. Database Design

### 1.1 Single unified `awards` table
One table for all agencies with a `source` discriminator. Cross-agency queries ("all awards to UNT regardless of agency") are trivial. Some columns are agency-specific and NULL for other sources (`activity_code`, `nih_institute` are NIH-only; `dir_abbr` is NSF-only).

### 1.2 `awd_id` as primary key
One row per base award, not per transaction. USASpending has two ID fields — we use `assistance_award_unique_key` (stable base award) not `assistance_transaction_unique_key` (changes every year).

### 1.3 `fiscal_year` never overwritten
On upsert conflict, `fiscal_year = awards.fiscal_year` (first insert wins). A FY2023 grant that has a $0 revision in FY2026 stays under FY2023. Load order: years ascending so earliest transaction is always inserted first.

### 1.4 `awd_amount` takes MAX on conflict
`total_obligated_amount` is a running cumulative total — only grows over time. MAX(incoming, stored) always gives the most accurate total.

| Source | `awd_amount` meaning |
|---|---|
| NSF | Total award for full grant lifespan |
| NIH | Sum of all annual budget periods = total project value (post-dedup) |
| USASpending | Cumulative total obligated to date |

### 1.5 `inst_uei` and `inst_canonical_name`
Added post-MVP. UEI (SAM.gov Unique Entity Identifier) is the only reliable cross-source deduplication key. `inst_canonical_name` is the normalized display name tied to the UEI, indexed for fast exact-match queries.

---

## 2. UEI Enrichment Pipeline (Completed)

All three source types already had UEI in `raw_json` — no external API calls needed for enrichment.

| Source | JSON path | Coverage |
|---|---|---|
| NSF | `$.inst.org_uei_num` | 99.9% |
| NIH | `$.organization.primary_uei` | 99.98% |
| USASpending | `$.recipient_uei` | 100% |

**Four phases:**
1. **USASpending UEI extraction** — extracted `recipient_uei` from raw_json (~170K records)
2. **Institutions table** — built from all UEI-keyed records; canonical name = most frequent `inst_name` per UEI
3. **NSF + NIH UEI enrichment** — raw_json extraction + cross-match against institutions table
4. **Canonical names** — rebuilt institutions table, applied 25 peer flags, set `canonical_name = peer_label` for peers

**Lesson:** Always check raw_json before calling external APIs. 37,575 of 37,609 "missing" NIH UEIs were already in raw_json.

---

## 3. HERD Institution Crosswalk

### Problem
The awards DB has 19,434 unique UEIs — a mix of universities, corporations, school districts, nonprofits. To support any-institution benchmarking, we need to identify which entities are research universities and map them to their correct awards UEI.

### Solution
`data/herd_ipeds_crosswalk.csv` — maps 1,108 IPEDS Carnegie 15–20 (doctoral + masters) and
Carnegie 25 (freestanding medical schools / health science centers) institutions to their
correct `awards_uei`.

**Match priority (applied in order):**
1. `direct` — IPEDS primary UEI matches awards DB exactly (959 institutions)
2. `secondary_uei` — one of the pipe-separated IPEDS UEI variants matches (12)
3. `case_fix` — IPEDS UEI matches after UPPER() normalization (5 — IPEDS sometimes stores lowercase)
4. `manual` — hardcoded override for known entity filing differences (46 — see below)
5. `name_match` — keyword search of awards DB, ≥2 keyword hits required (37)
6. `no_awards` — not in awards DB; confirmed small/for-profit schools (49)

**Total matched: 1,059 / 1,108 = 95.6%**
- All 131 R1 and 134 R2 institutions are 100% matched
- 54 / 55 Carnegie-25 medical schools/HSCs matched (only Mayo Clinic College of Medicine and
  Science has no presence in the awards DB)
- 49 unmatched are for-profits (Capella, DeVry, Full Sail), theological colleges (Bob Jones, Bethel), and small schools with no federal R&D

### 3.1 Business decision — Carnegie 25 (medical schools / HSCs) added, 2026-07-07

**Trigger:** User asked why UNT Health Science Center didn't appear in the institution
picker, despite submitting its own HERD survey and having its own UEI (`JE8AKPCR2KA4`) with
real award data in the DB.

**Root cause:** The original crosswalk scope (`RESEARCH_CODES = {15,16,17,18,19,20}`) only
covered doctoral/master's-granting universities. UNT HSC's actual Carnegie classification is
`25` ("Special Focus Four-Year: Medical Schools & Health Science Centers"), which was outside
that filter — not a UNT-specific bug. Verified against raw IPEDS (`data/ipeds/HD2023.csv`)
that this excluded all 55 freestanding HSCs/medical schools nationally, several of which are
health-science arms of peer institutions (UT Southwestern, UT Health San Antonio, UT Health
Houston, Texas Tech HSC, Oklahoma HSC, etc.).

**Decision:** Add Carnegie 25 to `RESEARCH_CODES`. HSCs become independently selectable in
the institution picker — **not** merged into their parent university's record. Rationale:
even where an HSC and its main campus share a system name (e.g., "UNT System"), they are
distinct legal entities with separate award portfolios, separate PIs, and separate
competitive positioning. Collapsing them into one row would understate the main campus's
performance (diluted by a much larger/smaller HSC portfolio) and make it impossible to
benchmark an HSC against peer HSCs specifically.

**Explicitly unaffected by this change:**
- `is_my_institution` in the `institutions` table (UNT HSC stays `0`; only the two main-campus
  UEIs are `1`)
- The `awards` table (no rows touched — this is a picker/lookup-table change only)
- Any existing peer-set definitions

**Why manual overrides are needed:**
Institutions often register their awards-filing entity under a different SAM.gov UEI than their IPEDS registration:
- SUNY schools file under "Research Foundation of SUNY" (different UEI than the campus)
- University of Nevada-Reno files as "Board of Regents, NSHE, obo University of Nevada, Reno"
- Indiana University campuses roll up to the system-level UEI
- IPEDS occasionally has typos (UNT's IPEDS UEI has trailing `g` instead of `9`)

**To regenerate the crosswalk:**
```
python scripts/build_herd_crosswalk.py   # regenerates data/herd_ipeds_crosswalk.csv
python scripts/load_herd_crosswalk.py    # loads CSV into herd_institutions table
```

**`herd_institutions` table schema:**
```
unitid, ipeds_name, state, carnegie, ipeds_uei,
awards_uei, awards_name, awards_count, awards_total_m, match_type, note
```

### Institution Picker Queries (`app/queries.py`)
Three functions added for the institution picker UI:
- `get_herd_institutions(state, carnegie_codes)` — filtered DataFrame for dropdown
- `get_herd_states()` — distinct states for state filter
- `get_institution_summary(awards_uei)` — summary card for a selected institution

Typical Streamlit usage:
```python
df = get_herd_institutions()
options = dict(zip(df["ipeds_name"] + " (" + df["state"] + ")", df["awards_uei"]))
selected_uei = options[st.selectbox("Select institution", list(options))]
```

---

## 4. Grants.gov Pipeline (In Progress)

**Purpose:** Forward-looking intelligence — open solicitations where peers are winning and UNT is absent.

**Pipeline:**
1. `scripts/fetch_grantsgov.py` — downloads daily XML extract from Grants.gov AWS S3, parses to JSONL
2. `scripts/load_grantsgov.py` — upserts JSONL into `opportunities` + `opportunity_cfdas` tables
3. `scripts/validate_grantsgov.py` — spot-checks sample records against live API

**DB tables:** `opportunities` (36 fields including derived_status, award ceiling, CFDA) + `opportunity_cfdas` junction table.

**Two query functions in `queries.py`:**
- `get_peer_opportunity_gaps()` — open NOFOs where peers won (FY2023+) and UNT is absent
- `get_unt_open_revisits()` — open NOFOs in programs UNT has historically won

**Page 5 (`app/pages/5_Open_Opportunities.py`):** Two-panel UI — peer gaps + UNT revisits. Filters: peer set, status (posted/forecasted), lookback FY, agency.

**Status:** Scripts complete; APScheduler integration not yet wired.

---

## 5. App Pages

| Page | File | Question it answers |
|------|------|---------------------|
| Home | `Home.py` | Where are peers beating us and by how much? |
| Portfolio Risk | `1_Portfolio_Risk.py` | How exposed are we if an agency gets cut? |
| Expiring Awards | `2_Expiring_Awards.py` | What funding are we about to lose? |
| Action Dashboard | `3_Action_Dashboard.py` | Where is money moving right now? |
| Data Dictionary | `4_Data_Dictionary.py` | What do these fields mean? |
| Open Opportunities | `5_Open_Opportunities.py` | What open solicitations should we pursue? |

**Home page components:** Sidebar (agency/program/peer set/FY) → Scorecard (4 metrics) → Gap table (all programs sorted by Opportunity) → Bar chart → Heatmap → Sankey → PDF export

**Gap table columns:** Program · UNT · Top 7 peers (short names) · Peer Avg · Opportunity ($M) · Field Total · Last Funded

**UNT column color coding:**
- Green: Opportunity ≤ 0 (UNT at or above peer average)
- Dark red: UNT = 0 (no awards)
- Red: UNT / PeerAvg < 0.40
- Orange: UNT / PeerAvg < 0.75
- Green: UNT / PeerAvg ≥ 0.75

---

## 6. Peer Configuration

**Defined in:** `scripts/phase4_canonical_names.py` (flags) + `app/queries.py` (constants)

**My institution:** University of North Texas (2 UEIs: `G47WN1XZNWX9`, `JSV3KA8HHBB5`)

**Texas peers (is_peer_texas = 1):**
Texas A&M, UT Austin, UT Arlington, UT Dallas, UTSA, UTEP, UTRGV, Texas State, Texas Tech, University of Houston

**National peers (is_peer_national = 1):**
Arizona State, Purdue, Georgia State, USF, UCF, University of Utah, University of Memphis, UIC, Tulane, UC Riverside

**To add/change peers:** Edit `PEER_FLAGS` in `scripts/phase4_canonical_names.py` and re-run. It rebuilds the institutions table safely.

---

## 7. Performance Rules

1. **Batch everything.** `executemany` with batches of 500–1000. Never insert one record at a time.
2. **Indexes before bulk updates.** `WHERE UPPER(inst_name) = ?` on 156K rows without index = 147s. With index = seconds.
3. **Set-based SQL, not Python loops.** A single `UPDATE ... WHERE inst_uei IN (...)` beats any Python loop.
4. **Test with 100 records first.** Verify logic on a small sample before running on full dataset.
5. **Raw files first.** Before calling any external API, check if data is already in `raw_json`. It usually is.
6. **Estimate before running.** For any operation touching >10K rows, state estimated runtime first.
7. **LIKE queries are slow.** A `%keyword%` scan on 423K rows takes 60–90 seconds on this machine. Use indexed UEI lookups instead wherever possible.

---

## 8. File Structure

```
Federal Radar/
├── data/
│   ├── federal_awards.db              SQLite, WAL mode, ~2GB
│   ├── herd_ipeds_crosswalk.csv       IPEDS → awards UEI crosswalk (1,108 rows)
│   ├── ipeds/HD2023.csv               IPEDS institutional data (6,163 rows, latin-1)
│   └── raw/
│       ├── grants_gov/raw/            Daily Grants.gov JSONL extracts
│       └── usaspending/               {AGENCY}_FY{YEAR}.{zip,csv,jsonl,done}
├── app/
│   ├── Home.py                        Competitive gap analysis (main page)
│   ├── pages/
│   │   ├── 1_Portfolio_Risk.py        Agency concentration, what-if, peer HHI
│   │   ├── 2_Expiring_Awards.py       Funding cliff, expiring awards table
│   │   ├── 3_Action_Dashboard.py      Cross-agency YTD, missed opportunities
│   │   ├── 4_Data_Dictionary.py       Field definitions, peer sets, coverage
│   │   └── 5_Open_Opportunities.py    Grants.gov — peer gaps + UNT revisits
│   ├── pdf_export.py                  PDF report generator (fpdf2 + kaleido)
│   └── queries.py                     All cached queries, peer config, constants
├── scripts/
│   ├── nsf_etl.py                     NSF bulk ZIP loader
│   ├── nsf_api_fetcher.py             NSF incremental daily sync
│   ├── nih_api_fetcher.py             NIH RePORTER API fetcher
│   ├── nih_deduplicate.py             NIH deduplication (one row per project)
│   ├── usaspending_api_fetcher.py     USASpending bulk download + load
│   ├── phase2_build_institutions_table.py  Build institutions reference table
│   ├── phase3a_nsf_uei_extract.py     Extract UEIs from NSF raw_json
│   ├── phase3b_nih_uei_enrich.py      NIH UEI enrichment (raw_json + API)
│   ├── phase3_samgov_enrichment.py    SAM.gov API lookup pipeline (staging)
│   ├── phase3_review_staging.py       Review SAM.gov staging before commit
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
├── CONTEXT.md                         This file
├── FUTURE_FEATURES.txt                Roadmap
└── README.md                          Setup and quick-start guide
```

---

## 9. Known Gaps

| Gap | Plan |
|-----|------|
| DHS FY2020–2026 | Overnight job — 20+ min/year on USASpending's server |
| Grants.gov APScheduler | Wire daily fetch+load into scheduler.py (has a synchronous API, same pattern as NSF/NIH) |
| Any-institution benchmarking | App currently hardcoded to UNT; herd_institutions table + picker queries are ready |
| Data governance footer | `get_data_freshness()` query exists; needs UI integration on all pages |
| Private foundation grants | Not in federal systems — future phase |
| Subaward data | Separate FSRS data source required |
